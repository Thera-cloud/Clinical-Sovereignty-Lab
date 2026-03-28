"""
D1 Sync Agent — Push PostgreSQL tables to Cloudflare D1 every 5 minutes.

Keeps D1 as a sub-ms read replica for Edge Workers. Syncs:
  - users -> roster (username, role, tier, name)
  - coaching_sessions -> schedule
  - token_balance data -> balance
  - tier gates -> gate
  - api_keys -> api_keys_edge (enterprise API)
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger("d1_sync_agent")

_CF_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
_CF_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
_D1_DATABASE_ID = os.getenv("D1_DATABASE_ID", "8dcd53ad-a6fb-49f4-8ca9-5a5843489cd0").strip()

SYNC_INTERVAL_SECONDS = 300
D1_API_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{db_id}/query"

_D1_MAX_CONSECUTIVE_FAILURES = 3
_D1_BACKOFF_MULTIPLIER = 2


class D1SyncAgent:
    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_sync: Dict[str, float] = {}
        self._cycle_count = 0
        self._consecutive_failures = 0
        self._suspended = False
        self._auth_failed_this_cycle = False
        self._backoff_exponent = 0

    async def start(self):
        if not _CF_ACCOUNT_ID or not _CF_API_TOKEN or not _D1_DATABASE_ID:
            logger.warning("D1SyncAgent: Missing Cloudflare credentials, skipping")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("D1SyncAgent started (5-min sync cycle)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    "Authorization": f"Bearer {_CF_API_TOKEN}",
                    "Content-Type": "application/json",
                },
            )
        return self._session

    async def _run_loop(self):
        await asyncio.sleep(30)
        while self._running:
            if self._suspended:
                suspend_secs = SYNC_INTERVAL_SECONDS * 12
                logger.info("D1SyncAgent: suspended for %ds (check CLOUDFLARE_API_TOKEN)", suspend_secs)
                await asyncio.sleep(suspend_secs)
                self._suspended = False
                self._consecutive_failures = 0
                self._backoff_exponent = 0
                logger.info("D1SyncAgent: resuming after suspension cooldown")
                continue

            self._auth_failed_this_cycle = False
            try:
                await self._sync_all()
                self._cycle_count += 1
                self._consecutive_failures = 0
                self._backoff_exponent = 0
            except Exception as e:
                self._consecutive_failures += 1
                if self._consecutive_failures <= _D1_MAX_CONSECUTIVE_FAILURES:
                    logger.warning("D1SyncAgent cycle error (%d/%d): %s",
                                   self._consecutive_failures, _D1_MAX_CONSECUTIVE_FAILURES, e)
                if self._consecutive_failures >= _D1_MAX_CONSECUTIVE_FAILURES:
                    logger.warning(
                        "D1SyncAgent: %d consecutive failures — suspending "
                        "for 1 hour (check CLOUDFLARE_API_TOKEN)",
                        self._consecutive_failures,
                    )
                    self._suspended = True
                    continue

            delay = SYNC_INTERVAL_SECONDS * (_D1_BACKOFF_MULTIPLIER ** min(self._backoff_exponent, 4))
            if self._auth_failed_this_cycle:
                self._backoff_exponent += 1
                delay = min(delay, 3600)
            await asyncio.sleep(delay)

    async def _execute_d1(self, sql: str, params: Optional[List] = None) -> bool:
        if self._auth_failed_this_cycle:
            return False
        url = D1_API_URL.format(account_id=_CF_ACCOUNT_ID, db_id=_D1_DATABASE_ID)
        payload: Dict[str, Any] = {"sql": sql}
        if params:
            payload["params"] = params
        try:
            session = await self._get_session()
            async with session.post(url, json=payload) as resp:
                if resp.status in (401, 403):
                    self._auth_failed_this_cycle = True
                    self._consecutive_failures += 1
                    if self._consecutive_failures == 1:
                        body = await resp.text()
                        logger.warning("D1 auth failed (%d): %s", resp.status, body[:200])
                    return False
                if resp.status == 429:
                    self._auth_failed_this_cycle = True
                    retry_after = int(resp.headers.get("Retry-After", "60"))
                    logger.warning("D1 rate-limited (429) — backing off %ds", retry_after)
                    return False
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("D1 query failed (%d): %s", resp.status, body[:200])
                    return False
                return True
        except Exception as e:
            logger.warning("D1 query error: %s", e)
            return False

    async def _execute_d1_batch(self, statements: List[Dict[str, Any]]) -> bool:
        if self._auth_failed_this_cycle:
            return False
        url = D1_API_URL.format(account_id=_CF_ACCOUNT_ID, db_id=_D1_DATABASE_ID)
        try:
            session = await self._get_session()
            for stmt in statements:
                async with session.post(url, json=stmt) as resp:
                    if resp.status in (401, 403):
                        self._auth_failed_this_cycle = True
                        self._consecutive_failures += 1
                        if self._consecutive_failures == 1:
                            body = await resp.text()
                            logger.warning("D1 batch auth failed (%d): %s", resp.status, body[:200])
                        return False
                    if resp.status == 429:
                        self._auth_failed_this_cycle = True
                        logger.warning("D1 batch rate-limited (429)")
                        return False
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning("D1 batch statement failed (%d): %s", resp.status, body[:200])
            return True
        except Exception as e:
            logger.warning("D1 batch error: %s", e)
            return False

    async def _sync_all(self):
        if not self._db_pool:
            return

        ok = await self._ensure_d1_tables()
        if self._auth_failed_this_cycle:
            return

        sync_methods = [
            self._sync_roster,
            self._sync_schedule,
            self._sync_balances,
            self._sync_api_keys,
            self._sync_crystal_metadata,
            self._sync_trust_audit_status,
            self._sync_social_dashboard,
            self._sync_device_reputation,
            self._sync_compliance_rules,
        ]

        for method in sync_methods:
            if self._auth_failed_this_cycle:
                return
            await method()

        self._last_sync["all"] = time.time()

    async def _ensure_d1_tables(self) -> bool:
        if self._cycle_count > 0:
            return True
        tables = [
            """CREATE TABLE IF NOT EXISTS roster (
                username TEXT PRIMARY KEY, role TEXT, tier TEXT, name TEXT,
                coach_id TEXT, family_id TEXT, company_id TEXT, updated_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS schedule (
                id TEXT PRIMARY KEY, coach_id TEXT, client_id TEXT,
                session_type TEXT, scheduled_at TEXT, duration_minutes INTEGER,
                status TEXT, updated_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS balance (
                username TEXT PRIMARY KEY, token_balance INTEGER,
                tier TEXT, updated_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS api_keys_edge (
                api_key TEXT PRIMARY KEY, org_name TEXT, tier TEXT,
                rate_limit_per_minute INTEGER, daily_limit INTEGER, updated_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS voice_queue (
                session_id TEXT PRIMARY KEY, user_id TEXT,
                queue_position INTEGER, estimated_wait INTEGER, created_at TEXT
            )""",
        ]
        for sql in tables:
            ok = await self._execute_d1(sql)
            if not ok:
                return False
        return True

    async def _sync_roster(self):
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT username, role, tier,
                           profile_data->>'name' as name,
                           profile_data->>'coach_id' as coach_id,
                           family_id::text as family_id,
                           company_id::text as company_id
                    FROM users
                    WHERE role IN ('CLIENT', 'COACH')
                    ORDER BY username
                """)

            for row in rows:
                await self._execute_d1(
                    """INSERT OR REPLACE INTO roster (username, role, tier, name, coach_id, family_id, company_id, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    [row["username"], row["role"], row.get("tier", "TRIAL"),
                     row.get("name", ""), row.get("coach_id", ""),
                     row.get("family_id", ""), row.get("company_id", "")],
                )
            self._last_sync["roster"] = time.time()
        except Exception as e:
            logger.warning("D1 roster sync error: %s", e)

    async def _sync_schedule(self):
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT COALESCE(session_id, id::text) AS id,
                           coach_id::text, client_id::text,
                           COALESCE(session_type, 'COACH') AS session_type,
                           COALESCE(scheduled_at, scheduled_start) AS scheduled_at,
                           COALESCE(duration_minutes, 0) AS duration_minutes,
                           status
                    FROM coaching_sessions
                    WHERE COALESCE(scheduled_at, scheduled_start) > NOW() - INTERVAL '7 days'
                    ORDER BY COALESCE(scheduled_at, scheduled_start) DESC
                    LIMIT 500
                """)

            for row in rows:
                sched = row["scheduled_at"].isoformat() if row.get("scheduled_at") else ""
                await self._execute_d1(
                    """INSERT OR REPLACE INTO schedule (id, coach_id, client_id, session_type, scheduled_at, duration_minutes, status, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    [row["id"], row.get("coach_id", ""), row.get("client_id", ""),
                     row.get("session_type", ""), sched,
                     row.get("duration_minutes", 30), row.get("status", "")],
                )
            self._last_sync["schedule"] = time.time()
        except Exception as e:
            logger.warning("D1 schedule sync error: %s", e)

    async def _sync_balances(self):
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT username, COALESCE(token_balance, 0) as token_balance, tier
                    FROM users
                    WHERE role = 'CLIENT'
                """)

            for row in rows:
                await self._execute_d1(
                    """INSERT OR REPLACE INTO balance (username, token_balance, tier, updated_at)
                       VALUES (?, ?, ?, datetime('now'))""",
                    [row["username"], row["token_balance"], row.get("tier", "TRIAL")],
                )
            self._last_sync["balances"] = time.time()
        except Exception as e:
            logger.warning("D1 balance sync error: %s", e)

    async def _sync_api_keys(self):
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT api_key, org_name, tier, rate_limit_per_minute, daily_limit
                    FROM api_keys
                    WHERE active = true
                """)

            for row in rows:
                await self._execute_d1(
                    """INSERT OR REPLACE INTO api_keys_edge (api_key, org_name, tier, rate_limit_per_minute, daily_limit, updated_at)
                       VALUES (?, ?, ?, ?, ?, datetime('now'))""",
                    [row["api_key"], row["org_name"], row["tier"],
                     row["rate_limit_per_minute"], row["daily_limit"]],
                )
            self._last_sync["api_keys"] = time.time()
        except Exception as e:
            logger.debug("D1 api_keys sync (table may not exist yet): %s", e)

    # ── Phase 2: D1 Replication System Build Sync Methods ──

    async def _sync_crystal_metadata(self):
        """Push active crystal metadata to D1 for edge filtering before embedding."""
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id::text AS crystal_id, domain,
                           COALESCE(confidence, 0.5) AS confidence,
                           COALESCE(scope, 'global') AS scope,
                           superseded_by::text, content_hash,
                           last_recalled_at, recall_count
                    FROM nate_intelligence_crystals
                    WHERE scope != 'archived'
                      AND superseded_by IS NULL
                    ORDER BY confidence DESC
                    LIMIT 2000
                """)

            for row in rows:
                recalled = row.get("last_recalled_at")
                recalled_str = recalled.isoformat() if recalled else None
                await self._execute_d1(
                    """INSERT OR REPLACE INTO crystal_metadata
                       (crystal_id, domain, confidence, scope, superseded_by,
                        content_hash, last_recalled_at, recall_count, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    [row["crystal_id"], row["domain"], row["confidence"],
                     row["scope"], row.get("superseded_by"),
                     row.get("content_hash"), recalled_str,
                     row.get("recall_count", 0)],
                )
            self._last_sync["crystal_metadata"] = time.time()
        except Exception as e:
            logger.debug("D1 crystal_metadata sync: %s", e)

    async def _sync_trust_audit_status(self):
        """Push latest trust enforcer result to D1 for edge health awareness."""
        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT content, created_at
                    FROM skyeye_activity
                    WHERE type = 'trust_enforcer_sent'
                    ORDER BY created_at DESC LIMIT 1
                """)

            if not row:
                return

            content = row.get("content", "")
            trusted = 0
            total = 0
            color = "UNKNOWN"
            actions = 0
            pf_pass = 0
            pf_total = 0

            if content:
                import re
                m = re.search(r"(\d+)/(\d+) TRUSTED", content)
                if m:
                    trusted = int(m.group(1))
                    total = int(m.group(2))
                score = (trusted / total * 100) if total else 0
                if "GREEN" in content:
                    color = "GREEN"
                elif "RED" in content:
                    color = "RED"
                elif "YELLOW" in content:
                    color = "YELLOW"
                m2 = re.search(r"(\d+) actions", content)
                if m2:
                    actions = int(m2.group(1))
                m3 = re.search(r"Pre-flight (\d+)/(\d+)", content)
                if m3:
                    pf_pass = int(m3.group(1))
                    pf_total = int(m3.group(2))

            await self._execute_d1(
                """INSERT OR REPLACE INTO trust_audit_status
                   (id, total_checks, trusted_count, score_pct, color,
                    actions_count, preflight_pass, preflight_total, timestamp)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [total, trusted, (trusted / total * 100) if total else 0,
                 color, actions, pf_pass, pf_total,
                 row["created_at"].isoformat()],
            )
            self._last_sync["trust_audit_status"] = time.time()
        except Exception as e:
            logger.debug("D1 trust_audit_status sync: %s", e)

    async def _sync_social_dashboard(self):
        """Push last 7 days of post analytics to D1 for edge dashboard reads."""
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT platform, post_id,
                           COALESCE(likes, 0) AS likes,
                           COALESCE(reposts, 0) AS reposts,
                           COALESCE(comments, 0) AS comments,
                           COALESCE(impressions, 0) AS impressions,
                           captured_at::date::text AS captured_date
                    FROM skyeye_post_analytics
                    WHERE captured_at > NOW() - INTERVAL '7 days'
                    ORDER BY captured_at DESC
                    LIMIT 500
                """)

            await self._execute_d1(
                "DELETE FROM social_dashboard_cache WHERE captured_date < date('now', '-8 days')"
            )

            for row in rows:
                await self._execute_d1(
                    """INSERT OR REPLACE INTO social_dashboard_cache
                       (platform, post_id, likes, reposts, comments,
                        impressions, captured_date, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    [row["platform"], row.get("post_id", ""),
                     row["likes"], row["reposts"], row["comments"],
                     row["impressions"], row["captured_date"]],
                )
            self._last_sync["social_dashboard"] = time.time()
        except Exception as e:
            logger.debug("D1 social_dashboard sync: %s", e)

    async def _sync_device_reputation(self):
        """Push device reputation data to D1 for BLE/NFC mesh and auth-edge checks."""
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT device_id, COALESCE(trust_score, 1.0) AS trust_score,
                           COALESCE(quarantined, false) AS quarantined,
                           COALESCE(interaction_count, 0) AS interaction_count,
                           last_seen_at, flags
                    FROM device_reputation
                    WHERE last_seen_at > NOW() - INTERVAL '30 days'
                    ORDER BY last_seen_at DESC
                    LIMIT 1000
                """)

            for row in rows:
                seen = row.get("last_seen_at")
                seen_str = seen.isoformat() if seen else None
                await self._execute_d1(
                    """INSERT OR REPLACE INTO device_reputation_edge
                       (device_id, trust_score, quarantined, interaction_count,
                        last_seen_at, flags, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
                    [row["device_id"], row["trust_score"],
                     1 if row["quarantined"] else 0,
                     row["interaction_count"], seen_str,
                     row.get("flags", "")],
                )
            self._last_sync["device_reputation"] = time.time()
        except Exception as e:
            logger.debug("D1 device_reputation sync: %s", e)

    async def _sync_compliance_rules(self):
        """Push compliance rules to D1 for edge gating per jurisdiction."""
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT jurisdiction,
                           COALESCE(baa_required, false) AS baa_required,
                           COALESCE(crisis_path_required, true) AS crisis_path_required,
                           COALESCE(data_retention_days, 365) AS data_retention_days,
                           COALESCE(mandatory_reporting, true) AS mandatory_reporting,
                           COALESCE(hipaa_covered, false) AS hipaa_covered,
                           rules_json
                    FROM compliance_rules
                    ORDER BY jurisdiction
                """)

            for row in rows:
                await self._execute_d1(
                    """INSERT OR REPLACE INTO compliance_rules_edge
                       (jurisdiction, baa_required, crisis_path_required,
                        data_retention_days, mandatory_reporting, hipaa_covered,
                        rules_json, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    [row["jurisdiction"],
                     1 if row["baa_required"] else 0,
                     1 if row["crisis_path_required"] else 0,
                     row["data_retention_days"],
                     1 if row["mandatory_reporting"] else 0,
                     1 if row["hipaa_covered"] else 0,
                     row.get("rules_json", "")],
                )
            self._last_sync["compliance_rules"] = time.time()
        except Exception as e:
            logger.debug("D1 compliance_rules sync: %s", e)

    def health(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "suspended": self._suspended,
            "consecutive_failures": self._consecutive_failures,
            "cycle_count": self._cycle_count,
            "last_sync": self._last_sync,
            "interval_seconds": SYNC_INTERVAL_SECONDS,
        }
