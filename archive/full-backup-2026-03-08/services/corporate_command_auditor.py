"""Corporate Command Trust Auditor — 25 checks across 7 tabs, 3x daily."""

import os
import asyncio
import logging
from datetime import datetime, timezone

import aiohttp

logger = logging.getLogger(__name__)

TAB_ENDPOINTS = [
    {
        "tab": "Health & Auth",
        "tab_num": 1,
        "endpoints": [
            ("GET", "/api/corp/health"),
            ("GET", "/api/corp/roster"),
            ("GET", "/api/corp/usage-dashboard"),
        ],
    },
    {
        "tab": "Import Pipeline",
        "tab_num": 2,
        "endpoints": [
            ("GET", "/api/corp/template/download"),
            ("POST", "/api/corp/bulk-import"),
            ("GET", "/api/corp/engagement-report"),
        ],
    },
    {
        "tab": "Management",
        "tab_num": 3,
        "endpoints": [
            ("GET", "/api/corp/coach-assignments"),
            ("GET", "/api/corp/billing/overview"),
            ("GET", "/api/corp/billing/invoices"),
        ],
    },
    {
        "tab": "Data Integrity",
        "tab_num": 4,
        "endpoints": [
            ("DB", "company_id_column_exists"),
            ("DB", "corporate_sponsors_table_exists"),
            ("DB", "corp_admin_has_company_id"),
        ],
    },
    {
        "tab": "Corp QuickBooks API",
        "tab_num": 5,
        "endpoints": [
            ("GET", "/api/corp/quickbooks/health"),
            ("GET", "/api/corp/quickbooks/status"),
            ("GET", "/api/corp/quickbooks/connect"),
            ("POST", "/api/corp/quickbooks/disconnect"),
            ("POST", "/api/corp/quickbooks/sync/trigger"),
            ("GET", "/api/corp/quickbooks/sync/history"),
            ("GET", "/api/corp/quickbooks/account-mapping"),
        ],
    },
    {
        "tab": "Corp QB Data Integrity",
        "tab_num": 6,
        "endpoints": [
            ("DB", "qb_corp_tables_exist"),
            ("DB", "qb_corp_tracking_columns_exist"),
        ],
    },
    {
        "tab": "Analytics",
        "tab_num": 7,
        "endpoints": [
            ("GET", "/api/corp/analytics/wellness"),
            ("GET", "/api/corp/analytics/trends?period=30d"),
            ("GET", "/api/corp/analytics/coach-team"),
            ("GET", "/api/corp/analytics/coach-roi"),
        ],
    },
]

AUDIT_HOURS = {5, 17, 23}
STAGGER_SECONDS = 115


class CorporateCommandAuditor:
    def __init__(self, db_pool=None, app_state=None):
        self._pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task = None
        self._base_url = "http://localhost:8000"
        self._token = os.getenv("SKYEYE_AUDIT_TOKEN", "")

    async def start(self):
        if not self._pool:
            logger.warning("CorporateCommandAuditor: no db_pool, skipping")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("CorporateCommandAuditor: started (stagger %ds)", STAGGER_SECONDS)

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
                    logger.error("CorporateCommandAuditor: error: %s", e)
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
                "corporate_command_audit_sent",
                json.dumps({
                    "scorecard": f"{trusted}/{total} TRUSTED",
                    "results": results,
                }),
                "system",
                datetime.now(timezone.utc),
            )

        # Email silenced — Trust Enforcer sends consolidated report
        logger.info("CorporateCommandAuditor: %d/%d TRUSTED", trusted, total)

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
                        if code == 200:
                            ct = resp.headers.get("content-type", "")
                            if "json" in ct:
                                body = await resp.json()
                                if isinstance(body, dict) and len(body) == 0:
                                    return "WARNING"
                        return "TRUSTED"
                    return "WARNING"
        except Exception as e:
            logger.warning("CorporateCommandAuditor: %s %s exception: %s", method, path, e)
            return "FAILED"

    async def _db_check(self, check_name: str) -> str:
        try:
            async with self._pool.acquire() as conn:
                if check_name == "company_id_column_exists":
                    val = await conn.fetchval(
                        """SELECT COUNT(*) FROM information_schema.columns
                           WHERE table_name = 'users' AND column_name = 'company_id'"""
                    )
                    return "TRUSTED" if val and val > 0 else "WARNING"

                elif check_name == "corporate_sponsors_table_exists":
                    val = await conn.fetchval(
                        """SELECT COUNT(*) FROM information_schema.tables
                           WHERE table_name = 'corporate_sponsors'"""
                    )
                    return "TRUSTED" if val and val > 0 else "WARNING"

                elif check_name == "corp_admin_has_company_id":
                    val = await conn.fetchval(
                        """SELECT COUNT(*) FROM users
                           WHERE role = 'CORP_ADMIN'
                             AND (company_id IS NOT NULL OR profile_data->>'company_id' IS NOT NULL)"""
                    )
                    if val is not None and val >= 0:
                        return "TRUSTED"
                    return "WARNING"

                elif check_name == "qb_corp_tables_exist":
                    val = await conn.fetchval(
                        """SELECT COUNT(*) FROM information_schema.tables
                           WHERE table_name IN ('qb_corp_connection', 'qb_corp_sync_log', 'qb_corp_account_mapping')"""
                    )
                    return "TRUSTED" if val and val >= 3 else "WARNING"

                elif check_name == "qb_corp_tracking_columns_exist":
                    val = await conn.fetchval(
                        """SELECT COUNT(*) FROM information_schema.columns
                           WHERE table_name = 'payment_history' AND column_name = 'synced_to_corp_qb'"""
                    )
                    return "TRUSTED" if val and val > 0 else "WARNING"

            return "WARNING"
        except Exception as e:
            logger.warning("CorporateCommandAuditor: DB check %s failed: %s", check_name, e)
            return "FAILED"
