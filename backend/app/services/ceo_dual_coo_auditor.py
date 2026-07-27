"""CEO Dual-COO Auditor — 10 checks on Nathan inbox / patent library / clinical APIs.

# QUANTUM-CRYSTAL-ARCH — ceo_dual_coo_check_count
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import aiohttp

logger = logging.getLogger(__name__)

TAB_ENDPOINTS = [
    {
        "tab": "CEO Inbox & Health",
        "tab_num": 1,
        "endpoints": [
            ("GET", "/api/ceo/health"),
            ("GET", "/api/ceo/inbox"),
            ("GET", "/api/ceo/loop-status"),
        ],
    },
    {
        "tab": "Patent & Clinical Gates",
        "tab_num": 2,
        "endpoints": [
            ("GET", "/api/ceo/patent-tags/pending"),
            ("GET", "/api/ceo/clinical-shadows"),
            ("GET", "/api/ceo/insight-briefs"),
        ],
    },
    {
        "tab": "Patent Idea Library",
        "tab_num": 3,
        "endpoints": [
            ("GET", "/api/ceo/patent-library"),
            ("GET", "/api/ceo/patent-library/weights"),
            ("GET", "/api/ceo/patent-reflections"),
            ("POST", "/api/ceo/patent-reflections/0/decide"),
        ],
    },
]

AUDIT_HOURS = {5, 17, 23}
STAGGER_SECONDS = 288


class CeoDualCooAuditor:
    def __init__(self, db_pool=None, app_state=None):
        self._pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task = None
        self._base_url = "http://localhost:8000"
        self._token = os.getenv("SKYEYE_AUDIT_TOKEN", "")

    async def start(self):
        if not self._pool:
            logger.warning("CeoDualCooAuditor: no db_pool, skipping")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("CeoDualCooAuditor: started (stagger %ds)", STAGGER_SECONDS)

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
                    logger.error("CeoDualCooAuditor: error: %s", e)
                await asyncio.sleep(3600)
            else:
                await asyncio.sleep(60)

    async def _build_and_send(self):
        results = []
        for tab in TAB_ENDPOINTS:
            for method, endpoint in tab["endpoints"]:
                status = await self._test_endpoint(method, endpoint)
                results.append({
                    "tab": tab["tab"],
                    "endpoint": endpoint,
                    "status": status,
                })

        trusted = sum(1 for r in results if r["status"] == "TRUSTED")
        total = len(results)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO skyeye_activity (type, content, platform, created_at)
                   VALUES ($1, $2, $3, $4)""",
                "ceo_dual_coo_audit_sent",
                json.dumps({
                    "scorecard": f"{trusted}/{total} TRUSTED",
                    "results": results,
                }),
                "system",
                datetime.now(timezone.utc),
            )

        # Email silenced — Trust Enforcer sends consolidated report
        logger.info("CeoDualCooAuditor: %d/%d TRUSTED", trusted, total)

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
                            try:
                                body = await resp.json()
                            except Exception:
                                body = {}
                            if isinstance(body, dict) and len(body) == 0:
                                return "WARNING"
                        return "TRUSTED"
                    if 400 <= code < 500:
                        return "WARNING"
                    return "FAILED"
        except Exception:
            return "FAILED"
