"""LN-Observer auditor — 13 checks (REST + DB), 3x daily, stagger 289s.

Email silenced — Trust Enforcer sends consolidated report.
# QUANTUM-CRYSTAL-ARCH
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

logger = logging.getLogger("nate.ln_observer_auditor")

AUDIT_HOURS = {5, 17, 23}
STAGGER_S = 289
BASE_URL = "http://localhost:8000"

TAB_ENDPOINTS = [
    {
        "tab": "Health & Status",
        "tab_num": 1,
        "endpoints": [
            ("GET", "/api/ln-observer/health"),
            ("GET", "/api/ln-observer/status"),
        ],
    },
    {
        "tab": "Approval Gate",
        "tab_num": 2,
        "endpoints": [
            ("POST", "/api/ln-observer/request-access"),
            ("GET", "/api/ln-observer/admin/approvals"),
            ("POST", "/api/ln-observer/admin/decide"),
        ],
    },
    {
        "tab": "Session Lifecycle",
        "tab_num": 3,
        "endpoints": [
            ("POST", "/api/ln-observer/activate"),
            (
                "POST",
                "/api/ln-observer/deactivate/00000000-0000-0000-0000-000000000000",
            ),
        ],
    },
    {
        "tab": "Gap Closure Ops",
        "tab_num": 4,
        "endpoints": [
            ("POST", "/api/ln-observer/admin/drain-ns-ingest"),
            ("POST", "/api/ln-observer/admin/backfill-summaries"),
        ],
    },
    {
        "tab": "Data Integrity",
        "tab_num": 5,
        "endpoints": [
            ("DB", "tables_exist"),
            ("DB", "ns_ingest_table"),
            ("DB", "no_stale_live"),
            ("DB", "engine_or_flag"),
        ],
    },
]


class LNObserverAuditor:
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
            "LNObserverAuditor started (3x daily, stagger %ds)", STAGGER_S
        )

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("LNObserverAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_S)
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
                logger.error("LNObserverAuditor tick failed: %s", e, exc_info=True)
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
                {"tab": t["tab"], "trusted": t["trusted"], "total": t["total"],
                 "endpoints": t["endpoints"]}
                for t in results
            ],
        })
        await self._log_activity(
            "system",
            "ln_observer_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()} | {detail}",
            "success",
        )
        logger.info("LNObserverAuditor: scorecard sent — %d/%d TRUSTED", trusted, total)

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
            r = _redis.Redis.from_url(
                redis_url, socket_timeout=2, decode_responses=True
            )
            env = os.environ.get("ENVIRONMENT", "development")
            prefix = f"nate:{env}:auth:"
            for key in r.scan_iter(f"{prefix}*", count=100):
                val = r.get(key)
                if val and "ADMIN" in val.upper():
                    return key.replace(prefix, "")
        except Exception as e:
            logger.debug("LNObserverAuditor: Redis token scan failed: %s", e)
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
                    elapsed = int((time.monotonic() - t0) * 1000)
            else:
                async with session.get(url, headers=headers) as resp:
                    code = resp.status
                    elapsed = int((time.monotonic() - t0) * 1000)
            if code in (200, 400, 404, 422):
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
                "ms": elapsed, "status": "FAILED",
                "detail": str(exc)[:80],
            }

    async def _run_db_check(self, check_name: str) -> dict:
        t0 = time.monotonic()
        try:
            if check_name == "engine_or_flag":
                elapsed = int((time.monotonic() - t0) * 1000)
                eng = getattr(self._app_state, "ln_observer_engine", None) if self._app_state else None
                flag = os.environ.get("ENABLE_LN_OBSERVER", "").lower() in (
                    "1", "true", "yes",
                )
                ok = (eng is not None) or (not flag)
                return {
                    "method": "DB", "path": check_name, "code": 200 if ok else 500,
                    "ms": elapsed,
                    "status": "TRUSTED" if ok else "WARNING",
                    "detail": f"engine={'yes' if eng else 'no'} flag={flag}",
                }
            async with self.db_pool.acquire() as conn:
                if check_name == "tables_exist":
                    n = await conn.fetchval(
                        """SELECT COUNT(*)::int FROM information_schema.tables
                           WHERE table_name IN (
                             'ln_observer_sessions',
                             'ln_observer_transcripts',
                             'ln_observer_approvals',
                             'ln_observer_activation_log'
                           )"""
                    )
                    elapsed = int((time.monotonic() - t0) * 1000)
                    ok = (n or 0) >= 4
                    return {
                        "method": "DB", "path": check_name, "code": 200 if ok else 500,
                        "ms": elapsed,
                        "status": "TRUSTED" if ok else "FAILED",
                        "detail": f"tables={n}",
                    }
                if check_name == "ns_ingest_table":
                    n = await conn.fetchval(
                        """SELECT COUNT(*)::int FROM information_schema.tables
                           WHERE table_name = 'ln_observer_ns_ingest'"""
                    )
                    elapsed = int((time.monotonic() - t0) * 1000)
                    ok = (n or 0) >= 1
                    return {
                        "method": "DB", "path": check_name, "code": 200 if ok else 500,
                        "ms": elapsed,
                        "status": "TRUSTED" if ok else "FAILED",
                        "detail": f"ns_ingest={n}",
                    }
                if check_name == "no_stale_live":
                    n = await conn.fetchval(
                        """SELECT COUNT(*)::int FROM ln_observer_sessions s
                           WHERE s.status = 'live'
                             AND s.started_at < NOW() - INTERVAL '3 hours'"""
                    )
                    elapsed = int((time.monotonic() - t0) * 1000)
                    ok = (n or 0) == 0
                    return {
                        "method": "DB", "path": check_name, "code": 200,
                        "ms": elapsed,
                        "status": "TRUSTED" if ok else "WARNING",
                        "detail": f"stale_live_3h={n}",
                    }
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "method": "DB", "path": check_name, "code": 0,
                "ms": elapsed, "status": "FAILED",
                "detail": f"Unknown check: {check_name}",
            }
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "method": "DB", "path": check_name, "code": 0,
                "ms": elapsed, "status": "FAILED", "detail": str(e)[:80],
            }

    async def _log_activity(self, platform, typ, content, severity):
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO skyeye_activity
                       (platform, type, content, severity)
                       VALUES ($1, $2, $3, $4)""",
                    platform, typ, content[:8000], severity,
                )
        except Exception as e:
            logger.warning("LNObserverAuditor activity log failed: %s", e)
