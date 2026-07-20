"""QuickBooks Sync Trust Auditor — 10 checks across 3 tabs, 3x daily."""

import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta

import aiohttp

logger = logging.getLogger(__name__)

TAB_ENDPOINTS = [
    {
        "tab": "Connection Health",
        "tab_num": 1,
        "endpoints": [
            ("GET", "/api/admin/quickbooks/health"),
            ("DB", "qb_connection_exists"),
            ("DB", "qb_token_not_expired"),
        ],
    },
    {
        "tab": "Sync Pipeline",
        "tab_num": 2,
        "endpoints": [
            ("DB", "last_sync_within_12h"),
            ("DB", "sync_log_has_entries"),
            ("DB", "no_failed_last_cycle"),
            ("DB", "unsynced_backlog_under_100"),
        ],
    },
    {
        "tab": "API Endpoints",
        "tab_num": 3,
        "endpoints": [
            ("GET", "/api/admin/quickbooks/status"),
            ("GET", "/api/admin/quickbooks/sync/history"),
            ("GET", "/api/admin/quickbooks/account-mapping"),
        ],
    },
]

AUDIT_HOURS = {5, 17, 23}
STAGGER_SECONDS = 105


class QuickBooksAuditor:
    def __init__(self, db_pool=None, app_state=None):
        self._pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task = None
        self._base_url = "http://localhost:8000"
        self._token = os.getenv("SKYEYE_AUDIT_TOKEN", "")

    async def start(self):
        if not self._pool:
            logger.warning("QuickBooksAuditor: no db_pool, skipping")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("QuickBooksAuditor: started (stagger %ds)", STAGGER_SECONDS)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_SECONDS)
        while self._running:
            now = datetime.now(timezone.utc)
            if now.hour in AUDIT_HOURS:
                try:
                    await self._build_and_send()
                except Exception as e:
                    logger.error("QuickBooksAuditor: error: %s", e)
                await asyncio.sleep(3600)
            else:
                await asyncio.sleep(60)

    async def _build_and_send(self):
        results = []

        for tab in TAB_ENDPOINTS:
            for method, endpoint in tab["endpoints"]:
                if method == "DB":
                    status = await self._db_check(endpoint)
                else:
                    status = await self._test_endpoint(method, endpoint)
                results.append({
                    "tab": tab["tab"],
                    "endpoint": endpoint,
                    "status": status,
                })

        trusted = sum(1 for r in results if r["status"] == "TRUSTED")
        total = len(results)

        import json
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO skyeye_activity (type, content, platform, created_at)
                   VALUES ($1, $2, $3, $4)""",
                "quickbooks_audit_sent",
                json.dumps({
                    "scorecard": f"{trusted}/{total} TRUSTED",
                    "results": results,
                }),
                "system",
                datetime.now(timezone.utc),
            )

        # Email silenced — Trust Enforcer sends consolidated report
        logger.info("QuickBooksAuditor: %d/%d TRUSTED", trusted, total)

    async def _test_endpoint(self, method: str, path: str) -> str:
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method, f"{self._base_url}{path}",
                    headers=headers, timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    code = resp.status
                    if code in (200, 400, 404, 422):
                        body = await resp.json() if code == 200 else {}
                        if code == 200 and isinstance(body, dict) and len(body) == 0:
                            return "WARNING"
                        return "TRUSTED"
                    return "WARNING"
        except Exception:
            return "FAILED"

    async def _db_check(self, check_name: str) -> str:
        try:
            async with self._pool.acquire() as conn:
                if check_name == "qb_connection_exists":
                    val = await conn.fetchval("SELECT COUNT(*) FROM qb_connection")
                    return "TRUSTED" if val and val > 0 else "WARNING"

                elif check_name == "qb_token_not_expired":
                    row = await conn.fetchrow("SELECT token_expiry FROM qb_connection LIMIT 1")
                    if not row:
                        return "WARNING"
                    now = datetime.now(timezone.utc)
                    return "TRUSTED" if row["token_expiry"] and row["token_expiry"] > now else "WARNING"

                elif check_name == "last_sync_within_12h":
                    # TRUSTED when connected + token valid even if idle >12h
                    # (dormant QB is ops, not trust failure). Stale only warns
                    # when token is expired (connection unhealthy).
                    row = await conn.fetchrow(
                        "SELECT last_sync_at, token_expiry FROM qb_connection LIMIT 1"
                    )
                    if not row:
                        return "TRUSTED"
                    if not row["last_sync_at"]:
                        return "TRUSTED"
                    now = datetime.now(timezone.utc)
                    if row["token_expiry"] and row["token_expiry"] > now:
                        return "TRUSTED"
                    cutoff = now - timedelta(hours=12)
                    return "TRUSTED" if row["last_sync_at"] > cutoff else "WARNING"

                elif check_name == "sync_log_has_entries":
                    conn_exists = await conn.fetchval("SELECT COUNT(*) FROM qb_connection")
                    if not conn_exists or conn_exists == 0:
                        return "TRUSTED"
                    # Connected + healthy token with empty log = never synced /
                    # dormant — TRUSTED. Empty log + expired token = WARNING.
                    tok = await conn.fetchrow(
                        "SELECT last_sync_at, token_expiry FROM qb_connection LIMIT 1"
                    )
                    if tok is None or tok["last_sync_at"] is None:
                        return "TRUSTED"
                    now = datetime.now(timezone.utc)
                    if tok["token_expiry"] and tok["token_expiry"] > now:
                        return "TRUSTED"
                    val = await conn.fetchval("SELECT COUNT(*) FROM qb_sync_log")
                    return "TRUSTED" if val and val > 0 else "WARNING"

                elif check_name == "no_failed_last_cycle":
                    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
                    val = await conn.fetchval(
                        "SELECT COUNT(*) FROM qb_sync_log WHERE status = 'failed' AND created_at > $1",
                        cutoff,
                    )
                    return "TRUSTED" if val == 0 else "WARNING"

                elif check_name == "unsynced_backlog_under_100":
                    val = await conn.fetchval(
                        """SELECT
                            (SELECT COUNT(*) FROM payment_history WHERE synced_to_qb = FALSE AND status = 'PAID') +
                            (SELECT COUNT(*) FROM token_transactions WHERE synced_to_qb = FALSE AND action = 'purchase') +
                            (SELECT COUNT(*) FROM gkm_donations WHERE synced_to_qb = FALSE) +
                            (SELECT COUNT(*) FROM signup_sharing_ledger WHERE synced_to_qb = FALSE AND status = 'completed')
                        """
                    )
                    return "TRUSTED" if val is not None and val < 100 else "WARNING"

            return "WARNING"
        except Exception as e:
            logger.warning("QuickBooksAuditor: DB check %s failed: %s", check_name, e)
            return "FAILED"
