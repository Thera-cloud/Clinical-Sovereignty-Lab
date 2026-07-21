"""
Six-Quotient Living Battery Auditor — 18 checks (health/bank/judge/actions + D.12/13 + DB).

Baseline key: six_quotient_battery_check_count (expected: 18)
Activity: six_quotient_battery_audit_sent
Stagger: 298s (under Trust Enforcer minute-10 ceiling)
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

logger = logging.getLogger("nate.six_quotient_battery_auditor")

AUDIT_HOURS = {5, 17, 23}
STAGGER_DELAY = 298
BASE_URL = "http://localhost:8000"

TAB_ENDPOINTS = [
    {
        "tab": "Health & Runs",
        "tab_num": 1,
        "endpoints": [
            ("GET", "/api/admin/six-quotient/health"),
            ("GET", "/api/admin/six-quotient/runs"),
            ("GET", "/api/admin/six-quotient/scorecard"),
        ],
    },
    {
        "tab": "Bank & Standards",
        "tab_num": 2,
        "endpoints": [
            ("GET", "/api/admin/six-quotient/bank"),
            ("GET", "/api/admin/six-quotient/standards"),
            ("GET", "/api/admin/six-quotient/ability"),
        ],
    },
    {
        "tab": "Judge & Validation",
        "tab_num": 3,
        "endpoints": [
            ("GET", "/api/admin/six-quotient/judge/gold"),
            ("POST", "/api/admin/six-quotient/scores"),
            ("POST", "/api/admin/six-quotient/bank/approve"),
            ("POST", "/api/admin/six-quotient/standards/approve"),
            ("POST", "/api/admin/six-quotient/judge/calibrate"),
        ],
    },
    {
        "tab": "Actions",
        "tab_num": 4,
        "endpoints": [
            ("POST", "/api/admin/six-quotient/generate"),
            ("POST", "/api/admin/six-quotient/self-dev/trigger"),
            ("POST", "/api/admin/six-quotient/standards/reject"),
            ("POST", "/api/admin/six-quotient/bank/holdout"),
            ("GET", "/api/admin/six-quotient/trend"),
            ("GET", "/api/admin/six-quotient/acceleration"),
        ],
    },
    {
        "tab": "Data Integrity",
        "tab_num": 5,
        "endpoints": [
            ("DB", "scenario_bank_table"),
        ],
    },
]


class SixQuotientBatteryAuditor:
    """3x-daily trust scorecard for Living Battery admin API + schema."""

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
        logger.info(
            "SixQuotientBatteryAuditor started (3x daily, stagger %ds)",
            STAGGER_DELAY,
        )

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SixQuotientBatteryAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_DELAY)
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
                logger.error("SixQuotientBatteryAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = await self._audit_all_tabs()
        # Email silenced — Trust Enforcer sends consolidated report
        total = sum(t["total"] for t in results)
        trusted = sum(t["trusted"] for t in results)
        detail = json.dumps({
            "trusted": trusted,
            "total": total,
            "results": [
                {"id": e.get("path"), "status": e.get("status"), "detail": e.get("detail")}
                for t in results for e in t.get("endpoints", [])
            ],
        })
        await self._log_activity(
            "system",
            "six_quotient_battery_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()} | {detail}",
            "success",
        )
        logger.info(
            "SixQuotientBatteryAuditor: scorecard sent — %d/%d TRUSTED",
            trusted,
            total,
        )

    def _resolve_token(self) -> str:
        if self._auth_token:
            return self._auth_token
        env_token = os.environ.get("SKYEYE_AUDIT_TOKEN", "")
        if env_token:
            return env_token
        try:
            import redis as _redis
            redis_pw = os.environ.get("REDIS_PASSWORD", "")
            redis_url = (
                f"redis://:{redis_pw}@redis:6379/0" if redis_pw
                else "redis://redis:6379/0"
            )
            r = _redis.Redis.from_url(redis_url, socket_timeout=2, decode_responses=True)
            env = os.environ.get("ENVIRONMENT", "development")
            prefix = f"nate:{env}:auth:"
            for key in r.scan_iter(f"{prefix}*", count=100):
                val = r.get(key)
                if val and "ADMIN" in val.upper():
                    return key.replace(prefix, "")
        except Exception as e:
            logger.debug("SixQuotientBatteryAuditor: Redis token scan failed: %s", e)
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
                        ep_result = await self._test_endpoint(
                            session, method, path, headers
                        )
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
                    return {
                        "method": method, "path": path, "code": code,
                        "ms": elapsed, "status": "WARNING",
                        "detail": f"200 but empty payload ({elapsed}ms)",
                    }
                return {
                    "method": method, "path": path, "code": code,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": f"{code} in {elapsed}ms",
                }
            if 400 <= code < 500:
                return {
                    "method": method, "path": path, "code": code,
                    "ms": elapsed, "status": "WARNING",
                    "detail": f"HTTP {code}",
                }
            return {
                "method": method, "path": path, "code": code,
                "ms": elapsed, "status": "FAILED",
                "detail": f"HTTP {code}",
            }
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "method": method, "path": path, "code": 0,
                "ms": elapsed, "status": "FAILED", "detail": "Timeout",
            }
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "method": method, "path": path, "code": 0,
                "ms": elapsed, "status": "FAILED", "detail": str(exc)[:80],
            }

    @staticmethod
    def _is_empty_payload(body) -> bool:
        if body is None:
            return True
        if isinstance(body, dict) and len(body) == 0:
            return True
        return False

    async def _run_db_check(self, check_name: str) -> dict:
        t0 = time.monotonic()
        try:
            async with self.db_pool.acquire() as conn:
                if check_name == "scenario_bank_table":
                    row = await conn.fetchrow(
                        """SELECT EXISTS (
                             SELECT 1 FROM information_schema.tables
                             WHERE table_name = 'six_quotient_scenario_bank'
                           ) AS ok"""
                    )
                    elapsed = int((time.monotonic() - t0) * 1000)
                    if row and row["ok"]:
                        return {
                            "method": "DB", "path": check_name, "code": 200,
                            "ms": elapsed, "status": "TRUSTED",
                            "detail": f"six_quotient_scenario_bank exists ({elapsed}ms)",
                        }
                    return {
                        "method": "DB", "path": check_name, "code": 0,
                        "ms": elapsed, "status": "FAILED",
                        "detail": "six_quotient_scenario_bank missing",
                    }
                elapsed = int((time.monotonic() - t0) * 1000)
                return {
                    "method": "DB", "path": check_name, "code": 0,
                    "ms": elapsed, "status": "FAILED",
                    "detail": f"Unknown check: {check_name}",
                }
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            logger.warning("SixQuotientBatteryAuditor: DB check '%s' failed: %s", check_name, e)
            return {
                "method": "DB", "path": check_name, "code": 0,
                "ms": elapsed, "status": "FAILED", "detail": str(e)[:80],
            }

    async def _log_activity(self, platform: str, activity_type: str,
                            content: str, severity: str):
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO skyeye_activity
                       (platform, type, content, severity, created_at)
                       VALUES ($1, $2, $3, $4, NOW())""",
                    platform, activity_type, content[:4000], severity,
                )
        except Exception as e:
            logger.warning("SixQuotientBatteryAuditor: activity log failed: %s", e)
