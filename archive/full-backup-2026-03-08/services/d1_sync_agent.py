"""
D1 Sync Agent — PostgreSQL → Cloudflare D1 hot cache

Syncs hot transactional data from PostgreSQL to D1 every 30 seconds:
  - Active client roster (denormalized per coach)
  - Coach schedules (next 14 days)
  - Token balances
  - Tier gate cache (role/tier/subscription for feature gating)
  - Coach availability slots

TTL Policies (auto-cleanup every cycle):
  - user_presence:    5 minutes after last_seen
  - coach_schedules:  24h after session end
  - token_balances:   5 minutes (re-synced every 30s)
  - tier_gates:       10 minutes (re-synced every 30s)
  - live_sessions:    4 hours after start (orphan safety net)
  - rate_limits:      window_seconds after window_start
  - client_roster:    10 minutes (re-synced every 30s)
  - coach_availability: end of slot date

D1 serves as a read-optimized edge cache. PostgreSQL remains the
source of truth. Writes always go to PostgreSQL first; this agent
propagates changes to D1 for sub-millisecond edge reads.

Architecture:
    PostgreSQL (source of truth)
      → D1SyncAgent (30s poll)
        → Cloudflare D1 REST API (batch SQL)
          → D1 edge replicas (global read)
            → Workers / backend queries
      → TTL sweeper (every cycle) → DELETE expired rows
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp

logger = logging.getLogger("d1_sync_agent")

_CF_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
_CF_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
_D1_DATABASE_ID = os.getenv("D1_DATABASE_ID", "8dcd53ad-a6fb-49f4-8ca9-5a5843489cd0")

D1_SYNC_INTERVAL = 30  # seconds

TTL_POLICIES = {
    "user_presence":     timedelta(minutes=5),
    "token_balances":    timedelta(minutes=5),
    "tier_gates":        timedelta(minutes=10),
    "client_roster":     timedelta(minutes=10),
    "live_sessions":     timedelta(hours=4),
    "coach_schedules":   timedelta(hours=24),
    "coach_availability": timedelta(days=0),  # expires at end of slot_date
    "rate_limits":       timedelta(seconds=0),  # uses window_seconds per row
}


class D1SyncAgent:
    """Syncs hot transactional data from PostgreSQL to Cloudflare D1."""

    def __init__(self, db_pool, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._cycle_count = 0
        self._total_rows_synced = 0
        self._d1_api_base = (
            f"https://api.cloudflare.com/client/v4/accounts/{_CF_ACCOUNT_ID}"
            f"/d1/database/{_D1_DATABASE_ID}/query"
        )

    async def start(self):
        if not _CF_API_TOKEN or not _CF_ACCOUNT_ID:
            logger.info("D1SyncAgent: CLOUDFLARE_API_TOKEN or CLOUDFLARE_ACCOUNT_ID not set — disabled")
            return
        if not self._db_pool:
            logger.warning("D1SyncAgent: no db_pool — disabled")
            return

        self._running = True
        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {_CF_API_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=30),
        )
        self._task = asyncio.create_task(self._run_loop())
        logger.info("D1SyncAgent: started (%ds cycle → D1 %s)", D1_SYNC_INTERVAL, _D1_DATABASE_ID[:8])

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
        logger.info("D1SyncAgent: stopped (%d rows synced across %d cycles)", self._total_rows_synced, self._cycle_count)

    async def _run_loop(self):
        await asyncio.sleep(10)
        while self._running:
            try:
                await self._sync_cycle()
                self._cycle_count += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("D1SyncAgent: cycle error: %s", e)
            await asyncio.sleep(D1_SYNC_INTERVAL)

    async def _sync_cycle(self):
        """Run all sync tasks + TTL sweep in parallel."""
        results = await asyncio.gather(
            self._sync_client_roster(),
            self._sync_coach_schedules(),
            self._sync_token_balances(),
            self._sync_tier_gates(),
            self._sweep_expired(),
            return_exceptions=True,
        )

        cycle_total = 0
        for i, label in enumerate(["roster", "schedules", "balances", "gates", "ttl_sweep"]):
            if isinstance(results[i], int):
                cycle_total += results[i]
            elif isinstance(results[i], Exception):
                logger.warning("D1SyncAgent: %s failed: %s", label, results[i])

        if cycle_total > 0:
            self._total_rows_synced += cycle_total
            if self._cycle_count % 20 == 0:
                logger.info("D1SyncAgent: cycle %d synced %d rows (%d cumulative)",
                            self._cycle_count + 1, cycle_total, self._total_rows_synced)

    async def _sweep_expired(self) -> int:
        """Delete all rows past their expires_at timestamp. Runs every cycle."""
        now = datetime.now(timezone.utc).isoformat()
        tables = [
            "user_presence", "coach_schedules", "token_balances",
            "tier_gates", "live_sessions", "rate_limits",
            "client_roster", "coach_availability",
        ]
        stmts = [
            {"sql": f"DELETE FROM {t} WHERE expires_at IS NOT NULL AND expires_at < ?", "params": [now]}
            for t in tables
        ]
        deleted = await self._d1_batch(stmts)
        if deleted and self._cycle_count % 60 == 0:
            logger.info("D1SyncAgent: TTL sweep cleaned expired rows across %d tables", len(tables))
        return 0  # don't count deletes in sync total

    async def _sync_client_roster(self) -> int:
        """Sync active client roster from PostgreSQL to D1."""
        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT username, role, tier, subscription_status,
                       profile_data->>'name' AS display_name,
                       profile_data->>'coach_id' AS coach_id,
                       profile_data->>'assigned_coach' AS coach_username,
                       profile_data->>'email' AS email,
                       profile_data->>'phone' AS phone,
                       profile_data->>'family_id' AS family_id,
                       company_id::text AS company_id,
                       profile_data->>'company_name' AS company_name,
                       profile_data->>'group_id' AS group_id,
                       COALESCE((profile_data->>'token_balance')::int, token_balance, 0) AS token_balance
                FROM users
                WHERE role = 'CLIENT' AND subscription_status IN ('ACTIVE', 'TRIAL_ACTIVE')
            """)

        if not rows:
            return 0

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires = (now + TTL_POLICIES["client_roster"]).isoformat()
        stmts = []
        for r in rows:
            stmts.append({
                "sql": """INSERT OR REPLACE INTO client_roster
                          (username, display_name, coach_id, coach_username, tier,
                           subscription_status, family_id, company_id, company_name,
                           group_id, email, phone, token_balance, is_active, updated_at, expires_at)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                "params": [
                    r["username"], r["display_name"], r["coach_id"], r["coach_username"],
                    r["tier"], r["subscription_status"], r["family_id"],
                    r["company_id"], r["company_name"], r["group_id"],
                    r["email"], r["phone"], r["token_balance"], now_iso, expires,
                ],
            })

        return await self._d1_batch(stmts)

    async def _sync_coach_schedules(self) -> int:
        """Sync upcoming coaching sessions (next 14 days) to D1 with TTL."""
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=1)).isoformat()
        future = (now + timedelta(days=14)).isoformat()

        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id::text AS session_id, client_id, coach_id, client_name,
                       status, session_type,
                       scheduled_at::text AS scheduled_at,
                       scheduled_start::text AS scheduled_start,
                       scheduled_end::text AS scheduled_end,
                       duration_minutes, zoom_link, payment_status,
                       family_id, updated_at::text AS updated_at
                FROM coaching_sessions
                WHERE (scheduled_at >= $1 OR scheduled_start >= $1)
                  AND (scheduled_at <= $2 OR scheduled_start <= $2)
                  AND status NOT IN ('CANCELLED')
                ORDER BY COALESCE(scheduled_start, scheduled_at) ASC
            """, cutoff, future)

        if not rows:
            return 0

        now_iso = now.isoformat()
        stmts = []
        for r in rows:
            end_str = r["scheduled_end"] or r["scheduled_at"] or now_iso
            try:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                end_dt = now
            expires = (end_dt + TTL_POLICIES["coach_schedules"]).isoformat()

            stmts.append({
                "sql": """INSERT OR REPLACE INTO coach_schedules
                          (session_id, coach_id, client_id, client_name, status,
                           session_type, scheduled_at, scheduled_start, scheduled_end,
                           duration_minutes, zoom_link, payment_status, family_id,
                           updated_at, expires_at)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                "params": [
                    r["session_id"], r["coach_id"], r["client_id"], r["client_name"],
                    r["status"], r["session_type"], r["scheduled_at"],
                    r["scheduled_start"], r["scheduled_end"],
                    r["duration_minutes"], r["zoom_link"], r["payment_status"],
                    r["family_id"], r["updated_at"] or now_iso, expires,
                ],
            })

        return await self._d1_batch(stmts)

    async def _sync_token_balances(self) -> int:
        """Sync current token balances to D1 with 5-min TTL."""
        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT username, tier,
                       COALESCE(token_balance, 0) AS balance,
                       COALESCE((profile_data->>'token_usage_today')::int, 0) AS usage_today,
                       COALESCE((profile_data->>'token_usage_month')::int, 0) AS usage_month
                FROM users
                WHERE subscription_status IN ('ACTIVE', 'TRIAL_ACTIVE')
            """)

        if not rows:
            return 0

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires = (now + TTL_POLICIES["token_balances"]).isoformat()
        stmts = []
        for r in rows:
            stmts.append({
                "sql": """INSERT OR REPLACE INTO token_balances
                          (username, balance, usage_today, usage_month, tier,
                           updated_at, expires_at)
                          VALUES (?, ?, ?, ?, ?, ?, ?)""",
                "params": [
                    r["username"], r["balance"], r["usage_today"],
                    r["usage_month"], r["tier"], now_iso, expires,
                ],
            })

        return await self._d1_batch(stmts)

    async def _sync_tier_gates(self) -> int:
        """Sync role/tier/subscription for feature gating with 10-min TTL."""
        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT username, role, tier, subscription_status,
                       profile_data->>'dojo_subscriptions' AS dojo_subscriptions,
                       CASE WHEN profile_data->>'has_coaching' = 'true' THEN 1 ELSE 0 END AS has_coaching,
                       CASE WHEN profile_data->>'founding_member' = 'true' THEN 1 ELSE 0 END AS is_founding,
                       profile_data->>'consent_version' AS consent_version
                FROM users
                WHERE subscription_status IN ('ACTIVE', 'TRIAL_ACTIVE')
            """)

        if not rows:
            return 0

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires = (now + TTL_POLICIES["tier_gates"]).isoformat()
        stmts = []
        for r in rows:
            stmts.append({
                "sql": """INSERT OR REPLACE INTO tier_gates
                          (username, role, tier, subscription_status,
                           dojo_subscriptions, has_coaching, is_founding,
                           consent_version, updated_at, expires_at)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                "params": [
                    r["username"], r["role"], r["tier"], r["subscription_status"],
                    r["dojo_subscriptions"], r["has_coaching"], r["is_founding"],
                    r["consent_version"], now_iso, expires,
                ],
            })

        return await self._d1_batch(stmts)

    async def update_presence(self, username: str, role: str, hw_id: str,
                               is_online: bool, portal: str = None,
                               device_type: str = None):
        """Called by the bridge on WebSocket connect/disconnect."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires = (now + TTL_POLICIES["user_presence"]).isoformat()
        stmt = {
            "sql": """INSERT OR REPLACE INTO user_presence
                      (username, role, hardware_id, is_online, last_seen_at,
                       connected_at, portal, device_type, expires_at)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            "params": [
                username, role, hw_id, 1 if is_online else 0,
                now_iso, now_iso if is_online else None, portal, device_type,
                expires,
            ],
        }
        await self._d1_batch([stmt])

    async def update_live_session(self, session_id: str, coach_id: str,
                                   client_id: str, status: str, **kwargs):
        """Called when a coaching session starts/updates/ends."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        if status in ("COMPLETED", "CANCELLED"):
            stmt = {"sql": "DELETE FROM live_sessions WHERE session_id = ?", "params": [session_id]}
        else:
            expires = (now + TTL_POLICIES["live_sessions"]).isoformat()
            stmt = {
                "sql": """INSERT OR REPLACE INTO live_sessions
                          (session_id, coach_id, client_id, status, started_at,
                           zoom_meeting_id, zoom_link, mood_at_start,
                           recording_consent, nate_active, updated_at, expires_at)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                "params": [
                    session_id, coach_id, client_id, status,
                    kwargs.get("started_at", now_iso),
                    kwargs.get("zoom_meeting_id"),
                    kwargs.get("zoom_link"),
                    kwargs.get("mood_at_start"),
                    1 if kwargs.get("recording_consent") else 0,
                    1 if kwargs.get("nate_active") else 0,
                    now_iso, expires,
                ],
            }
        await self._d1_batch([stmt])

    async def _d1_batch(self, statements: list[dict]) -> int:
        """Execute a batch of SQL statements against D1 via REST API."""
        if not self._session or not statements:
            return 0

        MAX_BATCH = 100
        total = 0

        for i in range(0, len(statements), MAX_BATCH):
            batch = statements[i:i + MAX_BATCH]
            try:
                async with self._session.post(self._d1_api_base, json=batch) as resp:
                    if resp.status == 200:
                        total += len(batch)
                    else:
                        body = await resp.text()
                        logger.warning("D1SyncAgent: batch failed (%d): %s", resp.status, body[:300])
            except Exception as e:
                logger.warning("D1SyncAgent: batch error: %s", e)

        return total

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "total_rows_synced": self._total_rows_synced,
            "database_id": _D1_DATABASE_ID[:8] + "...",
            "sync_interval_seconds": D1_SYNC_INTERVAL,
            "ttl_policies": {
                table: f"{int(ttl.total_seconds())}s"
                for table, ttl in TTL_POLICIES.items()
                if ttl.total_seconds() > 0
            },
        }
