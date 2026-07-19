"""Little Nate Dispatch auditor — 12 checks (stagger 298s).

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("nate.newsletter_auditor")

AUDIT_HOURS = {5, 17, 23}
BASE_URL = "http://localhost:8000"

TAB_ENDPOINTS = [
    {
        "tab": "Public Surface",
        "tab_num": 1,
        "endpoints": [
            ("GET", "/api/newsletter/health"),
            ("GET", "/api/newsletter/library"),
            ("GET", "/api/newsletter/rss"),
            ("GET", "/api/newsletter/library/__missing__/page"),
            ("GET", "/api/newsletter/share"),
            ("POST", "/api/newsletter/subscribe"),
            ("GET", "/api/newsletter/confirm"),
        ],
    },
    {
        "tab": "Admin + Integrity",
        "tab_num": 2,
        "endpoints": [
            ("GET", "/api/newsletter/admin/issues"),
            ("GET", "/api/newsletter/admin/subscribers/stats"),
            ("POST", "/api/newsletter/admin/issues/00000000-0000-0000-0000-000000000000/approve"),
            ("DB", "newsletter_tables_exist"),
            ("DB", "newsletter_baseline_row"),
        ],
    },
]


class NewsletterAuditor:
    def __init__(self, db_pool, notification_system=None, auth_token: str = "", app_state=None):
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
        logger.info("NewsletterAuditor started (stagger 298s)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        await asyncio.sleep(298)
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                window_key = f"{now.date().isoformat()}_{now.hour}"
                if now.hour in AUDIT_HOURS and window_key not in self._sent_windows:
                    await self._build_and_send(now)
                    self._sent_windows.add(window_key)
                    self._sent_windows = {
                        k for k in self._sent_windows if k.startswith(now.date().isoformat())
                    }
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("NewsletterAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = await self._audit_all_tabs()
        # Email silenced — Trust Enforcer sends consolidated report
        total = sum(t["total"] for t in results)
        trusted = sum(t["trusted"] for t in results)
        detail_json = json.dumps(
            [{"tab": t["tab"], "total": t["total"], "trusted": t["trusted"], "endpoints": t["endpoints"]} for t in results]
        )
        await self._log_activity("system", "newsletter_audit_detail", detail_json, "info")
        await self._log_activity(
            "system",
            "newsletter_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}",
            "success",
        )
        logger.info("NewsletterAuditor: %d/%d TRUSTED", trusted, total)

    def _resolve_token(self) -> str:
        if self._auth_token:
            return self._auth_token
        env_token = os.environ.get("SKYEYE_AUDIT_TOKEN", "")
        if env_token:
            return env_token
        return ""

    async def _audit_all_tabs(self) -> list:
        results = []
        token = self._resolve_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for tab_def in TAB_ENDPOINTS:
                tab_result = {
                    "tab": tab_def["tab"],
                    "tab_num": tab_def["tab_num"],
                    "total": 0,
                    "trusted": 0,
                    "warning": 0,
                    "failed": 0,
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
            else:
                async with session.get(url, headers=headers) as resp:
                    code = resp.status
                    try:
                        body = await resp.json()
                    except Exception:
                        body = None
            elapsed = int((time.monotonic() - t0) * 1000)
            if code in (200, 400, 404, 422):
                if code == 200 and isinstance(body, dict) and body == {}:
                    return {
                        "method": method,
                        "path": path,
                        "code": code,
                        "ms": elapsed,
                        "status": "WARNING",
                        "detail": "empty payload",
                    }
                return {
                    "method": method,
                    "path": path,
                    "code": code,
                    "ms": elapsed,
                    "status": "TRUSTED",
                    "detail": f"{code} in {elapsed}ms",
                }
            if 400 <= code < 500:
                return {
                    "method": method,
                    "path": path,
                    "code": code,
                    "ms": elapsed,
                    "status": "WARNING",
                    "detail": f"HTTP {code}",
                }
            return {
                "method": method,
                "path": path,
                "code": code,
                "ms": elapsed,
                "status": "FAILED",
                "detail": f"HTTP {code}",
            }
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "method": method,
                "path": path,
                "code": 0,
                "ms": elapsed,
                "status": "FAILED",
                "detail": str(exc)[:80],
            }

    async def _run_db_check(self, check_name: str) -> dict:
        t0 = time.monotonic()
        try:
            async with self.db_pool.acquire() as conn:
                if check_name == "newsletter_tables_exist":
                    rows = await conn.fetch(
                        """
                        SELECT table_name FROM information_schema.tables
                        WHERE table_schema = 'public'
                          AND table_name = ANY($1::text[])
                        """,
                        [
                            "newsletter_subscribers",
                            "newsletter_issues",
                            "newsletter_sends",
                            "newsletter_send_events",
                            "newsletter_feedback",
                            "newsletter_warm_leads",
                        ],
                    )
                    ok = len(rows) >= 6
                elif check_name == "newsletter_baseline_row":
                    val = await conn.fetchval(
                        """
                        SELECT parameter_value->>'expected'
                        FROM trust_baseline
                        WHERE parameter_key = 'newsletter_check_count'
                        """
                    )
                    ok = val == "10"
                else:
                    ok = False
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "method": "DB",
                "path": check_name,
                "code": 200 if ok else 0,
                "ms": elapsed,
                "status": "TRUSTED" if ok else "FAILED",
                "detail": "ok" if ok else "missing",
            }
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "method": "DB",
                "path": check_name,
                "code": 0,
                "ms": elapsed,
                "status": "FAILED",
                "detail": str(e)[:80],
            }

    async def _log_activity(self, platform: str, activity_type: str, content: str, level: str):
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    """,
                    platform,
                    activity_type,
                    content[:4000],
                    level,
                )
        except Exception as e:
            logger.warning("NewsletterAuditor log failed: %s", e)
