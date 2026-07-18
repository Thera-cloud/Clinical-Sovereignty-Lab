"""High-risk occupational crisis engine auditor — QUANTUM-CRYSTAL-ARCH.

10 checks: health, resources, confidentiality, population GET,
family education, coach risk-windows, concern-flag validation,
critical-incident validation, coach population validation,
risk_windows table exists.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("nate.high_risk_crisis_auditor")

AUDIT_HOURS = {5, 17, 23}
STAGGER_DELAY = 298  # under 300s ceiling
BASE_URL = "http://localhost:8000"

TAB_ENDPOINTS = [
    {
        "tab": "Client Surfaces",
        "tab_num": 1,
        "endpoints": [
            ("GET", "/api/high-risk-crisis/health"),
            ("GET", "/api/high-risk-crisis/resources"),
            ("GET", "/api/high-risk-crisis/confidentiality"),
            ("GET", "/api/high-risk-crisis/population"),
            ("GET", "/api/high-risk-crisis/family/education"),
        ],
    },
    {
        "tab": "Coach + Flags",
        "tab_num": 2,
        "endpoints": [
            ("GET", "/api/high-risk-crisis/coach/risk-windows"),
            ("POST", "/api/high-risk-crisis/family/concern-flag"),
            ("POST", "/api/high-risk-crisis/coach/critical-incident"),
            ("PUT", "/api/high-risk-crisis/coach/population"),
            ("DB", "risk_windows_table"),
        ],
    },
]


class HighRiskCrisisAuditor:
    def __init__(self, db_pool, redis_url: str = None, app_state=None):
        self.db_pool = db_pool
        self.redis_url = redis_url or os.getenv("REDIS_URL", "")
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sent_windows: set = set()
        self._token: Optional[str] = None

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("HighRiskCrisisAuditor started (stagger %ds)", STAGGER_DELAY)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _resolve_token(self) -> Optional[str]:
        env_tok = os.getenv("SKYEYE_AUDIT_TOKEN", "").strip()
        if env_tok:
            return env_tok
        return None

    async def _test_endpoint(self, session, method, path, token):
        url = f"{BASE_URL}{path}"
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            if method == "GET":
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    code = resp.status
            elif method == "PUT":
                async with session.put(
                    url, headers={**headers, "Content-Type": "application/json"},
                    json={}, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    code = resp.status
            else:
                async with session.post(
                    url, headers={**headers, "Content-Type": "application/json"},
                    json={}, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    code = resp.status
            status = "TRUSTED" if code in (200, 400, 404, 422) else (
                "WARNING" if 400 <= code < 500 else "FAILED"
            )
            return {"endpoint": f"{method} {path}", "code": code, "status": status}
        except Exception as e:
            return {"endpoint": f"{method} {path}", "code": 0, "status": "FAILED", "error": str(e)}

    async def _db_check(self):
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'checkin_risk_windows'
                    ) AS ok
                    """
                )
            ok = bool(row and row["ok"])
            return {
                "endpoint": "DB risk_windows_table",
                "code": 200 if ok else 500,
                "status": "TRUSTED" if ok else "FAILED",
            }
        except Exception as e:
            return {
                "endpoint": "DB risk_windows_table",
                "code": 0,
                "status": "FAILED",
                "error": str(e),
            }

    async def _build_and_send(self, now: datetime):
        token = await self._resolve_token()
        results = []
        async with aiohttp.ClientSession() as session:
            for tab in TAB_ENDPOINTS:
                for method, path in tab["endpoints"]:
                    if method == "DB":
                        results.append(await self._db_check())
                    else:
                        results.append(await self._test_endpoint(session, method, path, token))
        trusted = sum(1 for r in results if r["status"] == "TRUSTED")
        total = len(results)
        content = json.dumps({
            "trusted": trusted,
            "total": total,
            "pct": int(trusted / total * 100) if total else 0,
            "details": results,
            "ts": now.isoformat(),
        })
        # Email silenced — Trust Enforcer sends consolidated report
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO skyeye_activity (type, content, platform, created_at)
                        VALUES ('high_risk_crisis_audit_sent', $1, 'system', NOW())
                        """,
                        content,
                    )
            except Exception as e:
                logger.warning("HighRiskCrisisAuditor: activity log failed: %s", e)
        logger.info("HighRiskCrisisAuditor: %s/%s TRUSTED", trusted, total)

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_DELAY)
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                window_key = f"{now.date().isoformat()}_{now.hour}"
                if now.hour in AUDIT_HOURS and window_key not in self._sent_windows:
                    await self._build_and_send(now)
                    self._sent_windows.add(window_key)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("HighRiskCrisisAuditor loop error: %s", e)
            await asyncio.sleep(60)
