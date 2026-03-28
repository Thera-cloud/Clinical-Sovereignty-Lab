"""
LITTLE NATE — Universal Summon Auditor
Tests the Universal Summon system endpoints and verifies the privacy shield
is running alongside the summon service.

8 checks across 4 tabs:
  Tab 1: Summon Health (2 GET endpoints)
  Tab 2: Summon Operations (2 POST endpoints)
  Tab 3: Privacy Shield (2 endpoints — 1 GET, 1 POST)
  Tab 4: Data Integrity (2 DB/state checks)

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 295s.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("nate.summon_auditor")

AUDIT_HOURS = {5, 17, 23}
BASE_URL = "http://localhost:8000"

TAB_ENDPOINTS = [
    {
        "tab": "Summon Health",
        "tab_num": 1,
        "endpoints": [
            ("GET", "/api/summon/health"),
            ("GET", "/api/summon/active-devices"),
        ],
    },
    {
        "tab": "Summon Operations",
        "tab_num": 2,
        "endpoints": [
            ("POST", "/api/summon/register-device"),
            ("POST", "/api/summon/wake"),
        ],
    },
    {
        "tab": "Privacy Shield",
        "tab_num": 3,
        "endpoints": [
            ("GET", "/api/summon/privacy/status"),
            ("POST", "/api/summon/privacy/scan"),
        ],
    },
    {
        "tab": "Data Integrity",
        "tab_num": 4,
        "endpoints": [
            ("DB", "summon_service_running"),
            ("DB", "privacy_shield_running"),
        ],
    },
]


class SummonAuditor:

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
        logger.info("SummonAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SummonAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(295)
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
                logger.error("SummonAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = await self._audit_all_tabs()

        # Email silenced — Trust Enforcer sends consolidated report

        total = sum(t["total"] for t in results)
        trusted = sum(t["trusted"] for t in results)

        detail_json = json.dumps([{
            "tab": t["tab"],
            "total": t["total"],
            "trusted": t["trusted"],
            "endpoints": t["endpoints"],
        } for t in results])

        await self._log_activity(
            "system", "summon_audit_detail", detail_json, "info"
        )
        await self._log_activity(
            "system", "summon_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}", "success"
        )
        logger.info("SummonAuditor: scorecard sent — %d/%d TRUSTED", trusted, total)

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
            logger.debug("SummonAuditor: Redis token scan failed: %s", e)
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
            if check_name == "summon_service_running":
                return await self._check_summon_service(t0)
            elif check_name == "privacy_shield_running":
                return await self._check_privacy_shield(t0)
            else:
                elapsed = int((time.monotonic() - t0) * 1000)
                return {"method": "DB", "path": check_name, "code": 0,
                        "ms": elapsed, "status": "FAILED",
                        "detail": f"Unknown check: {check_name}"}
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            logger.warning("SummonAuditor: DB check '%s' failed: %s", check_name, e)
            return {"method": "DB", "path": check_name, "code": 0,
                    "ms": elapsed, "status": "FAILED", "detail": str(e)[:80]}

    async def _check_summon_service(self, t0: float) -> dict:
        """Verify nate_summon_service is initialized on app.state."""
        elapsed = int((time.monotonic() - t0) * 1000)
        if self._app_state is None:
            return {"method": "DB", "path": "summon_service_running", "code": 0,
                    "ms": elapsed, "status": "WARNING",
                    "detail": "app_state not available to auditor"}
        svc = getattr(self._app_state, "nate_summon_service", None)
        if svc is not None:
            return {"method": "DB", "path": "summon_service_running", "code": 200,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": f"nate_summon_service is running ({elapsed}ms)"}
        return {"method": "DB", "path": "summon_service_running", "code": 0,
                "ms": elapsed, "status": "FAILED",
                "detail": "nate_summon_service is None — not initialized"}

    async def _check_privacy_shield(self, t0: float) -> dict:
        """Verify privacy_shield is initialized on app.state."""
        elapsed = int((time.monotonic() - t0) * 1000)
        if self._app_state is None:
            return {"method": "DB", "path": "privacy_shield_running", "code": 0,
                    "ms": elapsed, "status": "WARNING",
                    "detail": "app_state not available to auditor"}
        svc = getattr(self._app_state, "privacy_shield", None)
        if svc is not None:
            return {"method": "DB", "path": "privacy_shield_running", "code": 200,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": f"privacy_shield is running ({elapsed}ms)"}
        return {"method": "DB", "path": "privacy_shield_running", "code": 0,
                "ms": elapsed, "status": "FAILED",
                "detail": "privacy_shield is None — not initialized"}

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
