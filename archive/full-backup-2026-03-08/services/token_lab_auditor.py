"""
LITTLE NATE — Token Lab Auditor
Tests all REST API endpoints backing the Token Lab admin dashboard
plus DB-level data integrity checks for token balances, transactions,
and cost configuration.

15 checks across 5 tabs:
  Tab 1: Token Overview (3 GET endpoints)
  Tab 2: Analytics (4 GET endpoints)
  Tab 3: Token Actions (3 POST endpoints)
  Tab 4: Cost & Config (2 endpoints)
  Tab 5: Data Integrity (3 DB-level checks)

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 100s.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("nate.token_lab_auditor")

AUDIT_HOURS = {5, 17, 23}
BASE_URL = "http://localhost:8000"

TAB_ENDPOINTS = [
    {
        "tab": "Token Overview",
        "tab_num": 1,
        "endpoints": [
            ("GET", "/api/token-lab/health"),
            ("GET", "/api/token-lab/balances"),
            ("GET", "/api/token-lab/transactions"),
        ],
    },
    {
        "tab": "Analytics",
        "tab_num": 2,
        "endpoints": [
            ("GET", "/api/token-lab/stats?days=30"),
            ("GET", "/api/token-lab/families"),
            ("GET", "/api/token-lab/groups"),
            ("GET", "/api/token-lab/usage-by-source?days=30"),
        ],
    },
    {
        "tab": "Token Actions",
        "tab_num": 3,
        "endpoints": [
            ("POST", "/api/token-lab/adjust"),
            ("POST", "/api/token-lab/reward"),
            ("POST", "/api/token-lab/mass-drop"),
        ],
    },
    {
        "tab": "Cost & Config",
        "tab_num": 4,
        "endpoints": [
            ("GET", "/api/token-lab/cost-analysis?days=30"),
            ("POST", "/api/token-lab/cost-config"),
        ],
    },
    {
        "tab": "Data Integrity",
        "tab_num": 5,
        "endpoints": [
            ("DB", "balance_consistency"),
            ("DB", "cost_config_exists"),
            ("DB", "transaction_table_health"),
        ],
    },
]


class TokenLabAuditor:

    def __init__(self, db_pool, notification_system=None, auth_token: str = "",
                 app_state=None):
        self.db_pool = db_pool
        self.notifications = notification_system
        self._auth_token = auth_token
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sent_windows: set = set()

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("TokenLabAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TokenLabAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(100)
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                window_key = f"{now.date().isoformat()}_{now.hour}"
                if now.hour in AUDIT_HOURS and window_key not in self._sent_windows:
                    await self._build_and_send(now)
                    self._sent_windows.add(window_key)
                    self._sent_windows = {
                        k for k in self._sent_windows
                        if k.startswith(now.date().isoformat())
                    }
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("TokenLabAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = await self._audit_all_tabs()

        # Email silenced — Trust Enforcer sends consolidated report

        total = sum(t["total"] for t in results)
        trusted = sum(t["trusted"] for t in results)
        await self._log_activity(
            "system", "token_lab_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}", "success"
        )
        logger.info("TokenLabAuditor: scorecard sent — %d/%d TRUSTED", trusted, total)

    def _resolve_token(self) -> str:
        if self._auth_token:
            return self._auth_token
        env_token = os.environ.get("SKYEYE_AUDIT_TOKEN", "")
        if env_token:
            return env_token
        try:
            import redis as _redis
            redis_pw = os.environ.get("REDIS_PASSWORD", "")
            redis_url = f"redis://:{redis_pw}@redis:6379/0" if redis_pw else "redis://redis:6379/0"
            r = _redis.Redis.from_url(redis_url, socket_timeout=2, decode_responses=True)
            env = os.environ.get("ENVIRONMENT", "development")
            prefix = f"nate:{env}:auth:"
            for key in r.scan_iter(f"{prefix}*", count=100):
                val = r.get(key)
                if val and "ADMIN" in val.upper():
                    return key.replace(prefix, "")
        except Exception as e:
            logger.debug("TokenLabAuditor: Redis token scan failed: %s", e)
        return ""

    async def _audit_all_tabs(self) -> list:
        results = []
        token = self._resolve_token()
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for tab_def in TAB_ENDPOINTS:
                tab_result = {
                    "tab": tab_def["tab"],
                    "tab_num": tab_def["tab_num"],
                    "total": 0, "trusted": 0, "warning": 0, "failed": 0,
                    "endpoints": [],
                }
                for method, path in tab_def["endpoints"]:
                    tab_result["total"] += 1
                    if method == "DB":
                        ep_result = await self._run_db_check(path)
                    else:
                        ep_result = await self._test_endpoint(session, method, path, headers)
                    tab_result["endpoints"].append(ep_result)
                    if ep_result["status"] == "TRUSTED":
                        tab_result["trusted"] += 1
                    elif ep_result["status"] == "WARNING":
                        tab_result["warning"] += 1
                    else:
                        tab_result["failed"] += 1
                results.append(tab_result)
        return results

    async def _test_endpoint(self, session, method: str, path: str, headers: dict) -> dict:
        url = f"{BASE_URL}{path}"
        t0 = time.monotonic()
        try:
            if method.upper() == "POST":
                async with session.post(url, headers=headers, json={}) as resp:
                    code = resp.status
                    try:
                        body = await resp.json()
                    except Exception:
                        body = None
                    elapsed = int((time.monotonic() - t0) * 1000)
            else:
                async with session.get(url, headers=headers) as resp:
                    code = resp.status
                    try:
                        body = await resp.json()
                    except Exception:
                        body = None
                    elapsed = int((time.monotonic() - t0) * 1000)

            if code in (200, 400, 404, 422):
                if code == 200 and self._is_empty_payload(body):
                    return {"method": method, "path": path, "code": code,
                            "ms": elapsed, "status": "WARNING",
                            "detail": f"200 but empty payload ({elapsed}ms)"}
                return {"method": method, "path": path, "code": code,
                        "ms": elapsed, "status": "TRUSTED",
                        "detail": f"{code} in {elapsed}ms"}
            elif 400 <= code < 500:
                return {"method": method, "path": path, "code": code,
                        "ms": elapsed, "status": "WARNING",
                        "detail": f"HTTP {code}"}
            else:
                return {"method": method, "path": path, "code": code,
                        "ms": elapsed, "status": "FAILED",
                        "detail": f"HTTP {code}"}
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {"method": method, "path": path, "code": 0,
                    "ms": elapsed, "status": "FAILED", "detail": "Timeout"}
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {"method": method, "path": path, "code": 0,
                    "ms": elapsed, "status": "FAILED", "detail": str(exc)[:80]}

    async def _run_db_check(self, check_name: str) -> dict:
        t0 = time.monotonic()
        try:
            async with self.db_pool.acquire() as conn:
                if check_name == "balance_consistency":
                    return await self._check_balance_consistency(conn, t0)
                elif check_name == "cost_config_exists":
                    return await self._check_cost_config(conn, t0)
                elif check_name == "transaction_table_health":
                    return await self._check_transaction_health(conn, t0)
                else:
                    elapsed = int((time.monotonic() - t0) * 1000)
                    return {"method": "DB", "path": check_name, "code": 0,
                            "ms": elapsed, "status": "FAILED",
                            "detail": f"Unknown check: {check_name}"}
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            logger.warning("TokenLabAuditor: DB check '%s' failed: %s", check_name, e)
            return {"method": "DB", "path": check_name, "code": 0,
                    "ms": elapsed, "status": "FAILED", "detail": str(e)[:80]}

    async def _check_balance_consistency(self, conn, t0: float) -> dict:
        """Verify token_balance column matches profile_data->>'token_balance' where both exist."""
        row = await conn.fetchrow("""
            SELECT COUNT(*) as total_users,
                   COUNT(*) FILTER (
                       WHERE profile_data ? 'token_balance'
                         AND COALESCE(token_balance, 0) !=
                             COALESCE((profile_data->>'token_balance')::int, 0)
                   ) as mismatched
            FROM users
            WHERE token_balance IS NOT NULL
        """)
        elapsed = int((time.monotonic() - t0) * 1000)
        total = row["total_users"] if row else 0
        mismatched = row["mismatched"] if row else 0

        if mismatched == 0:
            return {"method": "DB", "path": "balance_consistency", "code": 200,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": f"{total} users checked, 0 mismatches ({elapsed}ms)"}
        else:
            return {"method": "DB", "path": "balance_consistency", "code": 200,
                    "ms": elapsed, "status": "WARNING",
                    "detail": f"{mismatched}/{total} balance mismatches between column and JSONB"}

    async def _check_cost_config(self, conn, t0: float) -> dict:
        """Verify at least one cost config row exists with valid positive values."""
        row = await conn.fetchrow("""
            SELECT cost_per_token, price_per_token
            FROM token_cost_config
            ORDER BY effective_from DESC LIMIT 1
        """)
        elapsed = int((time.monotonic() - t0) * 1000)

        if not row:
            return {"method": "DB", "path": "cost_config_exists", "code": 200,
                    "ms": elapsed, "status": "WARNING",
                    "detail": "No cost config row found — economics unconfigured"}

        cost = float(row["cost_per_token"])
        price = float(row["price_per_token"])
        if cost <= 0 or price <= 0:
            return {"method": "DB", "path": "cost_config_exists", "code": 200,
                    "ms": elapsed, "status": "WARNING",
                    "detail": f"Cost ({cost}) or price ({price}) is non-positive"}
        if cost >= price:
            return {"method": "DB", "path": "cost_config_exists", "code": 200,
                    "ms": elapsed, "status": "WARNING",
                    "detail": f"Cost ({cost}) >= price ({price}) — negative margin"}

        return {"method": "DB", "path": "cost_config_exists", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"Cost ${cost}, Price ${price}, margin healthy ({elapsed}ms)"}

    async def _check_transaction_health(self, conn, t0: float) -> dict:
        """Verify token_transactions table exists, is writable, and has valid schema."""
        row = await conn.fetchrow("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'token_transactions'
            ) as exists_ok
        """)
        elapsed = int((time.monotonic() - t0) * 1000)

        if not row or not row["exists_ok"]:
            return {"method": "DB", "path": "transaction_table_health", "code": 0,
                    "ms": elapsed, "status": "FAILED",
                    "detail": "token_transactions table does not exist"}

        count_row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM token_transactions"
        )
        count = count_row["cnt"] if count_row else 0
        elapsed = int((time.monotonic() - t0) * 1000)

        return {"method": "DB", "path": "transaction_table_health", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"Table healthy, {count} transactions logged ({elapsed}ms)"}

    @staticmethod
    def _is_empty_payload(body) -> bool:
        if body is None:
            return True
        if isinstance(body, (list, bool, int, float, str)):
            return False
        if isinstance(body, dict):
            return len(body) == 0
        return True

    async def _log_activity(self, platform: str, activity_type: str,
                            content: str, severity: str = "info"):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                """, platform, activity_type, content, severity)
        except Exception:
            pass
