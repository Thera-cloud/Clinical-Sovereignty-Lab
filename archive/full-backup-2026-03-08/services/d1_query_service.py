"""
D1 Query Service — Edge-fast reads from Cloudflare D1

Provides typed query methods for hot transactional data stored in D1.
Falls back to PostgreSQL if D1 is unavailable.

Usage:
    d1 = D1QueryService(db_pool)
    roster = await d1.get_coach_roster("COACH_COACHN_ID")
    schedule = await d1.get_coach_schedule("COACH_COACHN_ID")
    online = await d1.get_online_users()
"""

import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger("d1_query")

_CF_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
_CF_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
_D1_DATABASE_ID = os.getenv("D1_DATABASE_ID", "8dcd53ad-a6fb-49f4-8ca9-5a5843489cd0")


class D1QueryService:
    """Edge-fast reads from Cloudflare D1 with PostgreSQL fallback."""

    def __init__(self, db_pool=None):
        self._db_pool = db_pool
        self._session: Optional[aiohttp.ClientSession] = None
        self._enabled = bool(_CF_API_TOKEN and _CF_ACCOUNT_ID and _D1_DATABASE_ID)
        self._d1_api_base = (
            f"https://api.cloudflare.com/client/v4/accounts/{_CF_ACCOUNT_ID}"
            f"/d1/database/{_D1_DATABASE_ID}/query"
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {_CF_API_TOKEN}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _d1_query(self, sql: str, params: list = None) -> list[dict]:
        """Execute a read query against D1."""
        session = await self._get_session()
        payload = [{"sql": sql, "params": params or []}]

        async with session.post(self._d1_api_base, json=payload) as resp:
            if resp.status != 200:
                raise RuntimeError(f"D1 query failed: {resp.status}")
            data = await resp.json()
            results = data.get("result", [])
            if results and results[0].get("results"):
                return results[0]["results"]
            return []

    # -------------------------------------------------------------------
    # Client Roster
    # -------------------------------------------------------------------

    async def get_coach_roster(self, coach_id: str) -> list[dict]:
        """Get all active clients for a coach."""
        if self._enabled:
            try:
                return await self._d1_query(
                    "SELECT * FROM client_roster WHERE coach_id = ? AND is_active = 1 ORDER BY display_name",
                    [coach_id],
                )
            except Exception as e:
                logger.warning("D1 roster query failed, falling back to PG: %s", e)

        if self._db_pool:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT username, profile_data->>'name' AS display_name,
                           profile_data->>'coach_id' AS coach_id, tier,
                           subscription_status, profile_data->>'family_id' AS family_id,
                           company_id::text, profile_data->>'company_name' AS company_name,
                           COALESCE(token_balance, 0) AS token_balance
                    FROM users WHERE role = 'CLIENT'
                      AND profile_data->>'coach_id' = $1
                      AND subscription_status IN ('ACTIVE', 'TRIAL_ACTIVE')
                    ORDER BY profile_data->>'name'
                """, coach_id)
                return [dict(r) for r in rows]
        return []

    async def get_client_info(self, username: str) -> Optional[dict]:
        """Get a single client's roster entry."""
        if self._enabled:
            try:
                rows = await self._d1_query(
                    "SELECT * FROM client_roster WHERE username = ?", [username]
                )
                return rows[0] if rows else None
            except Exception:
                pass

        if self._db_pool:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT username, profile_data->>'name' AS display_name, tier, subscription_status FROM users WHERE username = $1",
                    username,
                )
                return dict(row) if row else None
        return None

    # -------------------------------------------------------------------
    # Coach Schedules
    # -------------------------------------------------------------------

    async def get_coach_schedule(self, coach_id: str, status: str = None) -> list[dict]:
        """Get upcoming sessions for a coach."""
        if self._enabled:
            try:
                if status:
                    return await self._d1_query(
                        "SELECT * FROM coach_schedules WHERE coach_id = ? AND status = ? ORDER BY scheduled_at",
                        [coach_id, status],
                    )
                return await self._d1_query(
                    "SELECT * FROM coach_schedules WHERE coach_id = ? ORDER BY scheduled_at",
                    [coach_id],
                )
            except Exception as e:
                logger.warning("D1 schedule query failed: %s", e)

        if self._db_pool:
            async with self._db_pool.acquire() as conn:
                if status:
                    rows = await conn.fetch(
                        "SELECT id::text AS session_id, client_id, coach_id, status, scheduled_at::text FROM coaching_sessions WHERE coach_id = $1 AND status = $2 ORDER BY scheduled_at",
                        coach_id, status,
                    )
                else:
                    rows = await conn.fetch(
                        "SELECT id::text AS session_id, client_id, coach_id, status, scheduled_at::text FROM coaching_sessions WHERE coach_id = $1 ORDER BY scheduled_at",
                        coach_id,
                    )
                return [dict(r) for r in rows]
        return []

    async def get_client_schedule(self, client_id: str) -> list[dict]:
        """Get upcoming sessions for a client."""
        if self._enabled:
            try:
                return await self._d1_query(
                    "SELECT * FROM coach_schedules WHERE client_id = ? ORDER BY scheduled_at",
                    [client_id],
                )
            except Exception:
                pass

        if self._db_pool:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id::text AS session_id, client_id, coach_id, status, scheduled_at::text FROM coaching_sessions WHERE client_id = $1 ORDER BY scheduled_at",
                    client_id,
                )
                return [dict(r) for r in rows]
        return []

    # -------------------------------------------------------------------
    # Presence & Live Sessions
    # -------------------------------------------------------------------

    async def get_online_users(self, role: str = None) -> list[dict]:
        """Get currently online users."""
        if self._enabled:
            try:
                if role:
                    return await self._d1_query(
                        "SELECT * FROM user_presence WHERE is_online = 1 AND role = ?", [role]
                    )
                return await self._d1_query("SELECT * FROM user_presence WHERE is_online = 1")
            except Exception:
                pass
        return []

    async def get_online_count(self) -> dict:
        """Get count of online users by role."""
        if self._enabled:
            try:
                rows = await self._d1_query(
                    "SELECT role, COUNT(*) AS count FROM user_presence WHERE is_online = 1 GROUP BY role"
                )
                result = {"CLIENT": 0, "COACH": 0, "ADMIN": 0, "total": 0}
                for r in rows:
                    result[r["role"]] = r["count"]
                    result["total"] += r["count"]
                return result
            except Exception:
                pass
        return {"CLIENT": 0, "COACH": 0, "ADMIN": 0, "total": 0}

    async def get_live_sessions(self) -> list[dict]:
        """Get currently active coaching sessions."""
        if self._enabled:
            try:
                return await self._d1_query(
                    "SELECT * FROM live_sessions WHERE status IN ('WAITING', 'IN_PROGRESS') ORDER BY started_at"
                )
            except Exception:
                pass
        return []

    # -------------------------------------------------------------------
    # Token Balances
    # -------------------------------------------------------------------

    async def get_token_balance(self, username: str) -> Optional[dict]:
        """Get a user's current token balance."""
        if self._enabled:
            try:
                rows = await self._d1_query(
                    "SELECT * FROM token_balances WHERE username = ?", [username]
                )
                return rows[0] if rows else None
            except Exception:
                pass

        if self._db_pool:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT username, COALESCE(token_balance, 0) AS balance FROM users WHERE username = $1",
                    username,
                )
                return dict(row) if row else None
        return None

    # -------------------------------------------------------------------
    # Tier Gates
    # -------------------------------------------------------------------

    async def check_tier_gate(self, username: str) -> Optional[dict]:
        """Get a user's tier/role/subscription for feature gating."""
        if self._enabled:
            try:
                rows = await self._d1_query(
                    "SELECT * FROM tier_gates WHERE username = ?", [username]
                )
                return rows[0] if rows else None
            except Exception:
                pass

        if self._db_pool:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT username, role, tier, subscription_status FROM users WHERE username = $1",
                    username,
                )
                return dict(row) if row else None
        return None

    # -------------------------------------------------------------------
    # Coach Availability
    # -------------------------------------------------------------------

    async def get_available_slots(self, coach_id: str, date: str = None) -> list[dict]:
        """Get available booking slots for a coach."""
        if self._enabled:
            try:
                if date:
                    return await self._d1_query(
                        "SELECT * FROM coach_availability WHERE coach_id = ? AND slot_date = ? AND is_available = 1 AND is_booked = 0 ORDER BY start_time",
                        [coach_id, date],
                    )
                return await self._d1_query(
                    "SELECT * FROM coach_availability WHERE coach_id = ? AND is_available = 1 AND is_booked = 0 ORDER BY slot_date, start_time",
                    [coach_id],
                )
            except Exception:
                pass
        return []

    def get_status(self) -> dict:
        return {
            "enabled": self._enabled,
            "database_id": _D1_DATABASE_ID[:8] + "..." if _D1_DATABASE_ID else None,
            "source": "d1" if self._enabled else "postgresql",
        }
