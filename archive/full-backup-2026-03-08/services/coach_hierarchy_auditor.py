"""
LITTLE NATE — Coach Hierarchy & Coaching Mesh Auditor

Tests 16 endpoints/checks covering coach hierarchy management,
supervised hours, and BLE coaching mesh functionality.

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 290s.

10 hierarchy checks + 6 mesh checks = 16 total.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("nate.coach_hierarchy_auditor")

AUDIT_HOURS = {5, 17, 23}
BASE_URL = "http://localhost:8000"
FAKE_COACH = "audit_coach_hw"

TAB_ENDPOINTS = [
    {
        "tab": "Hierarchy Management",
        "tab_num": 1,
        "endpoints": [
            ("POST", "/api/coach/hierarchy/invite", {"assistant_username": "nonexistent_test_user"}),
            ("POST", "/api/coach/hierarchy/accept", {"master_coach_id": "test_master"}),
            ("GET", f"/api/coach/hierarchy/assistants/{FAKE_COACH}"),
            ("POST", "/api/coach/hierarchy/revoke", {"assistant_id": "test_assistant"}),
        ],
    },
    {
        "tab": "Supervised Hours",
        "tab_num": 2,
        "endpoints": [
            ("POST", "/api/coach/hierarchy/hours/log", {
                "assistant_id": "test_assistant", "duration_minutes": 0, "activity_type": "test",
            }),
            ("GET", f"/api/coach/hierarchy/hours/{FAKE_COACH}"),
            ("GET", f"/api/coach/hierarchy/hours/export/{FAKE_COACH}"),
            ("POST", "/api/coach/hierarchy/hours/attest", {"hours_id": 0}),
        ],
    },
    {
        "tab": "Coaching Metrics",
        "tab_num": 3,
        "endpoints": [
            ("GET", "/api/coach/hierarchy/metrics"),
            ("GET", "/api/coach/hierarchy/wisdom"),
        ],
    },
    {
        "tab": "Mesh Tables",
        "tab_num": 4,
        "endpoints": [
            ("DB_CHECK", "coaching_mesh_sessions"),
            ("DB_CHECK", "coaching_mesh_participants"),
            ("DB_CHECK", "coaching_mesh_messages"),
        ],
    },
    {
        "tab": "Mesh Endpoints",
        "tab_num": 5,
        "endpoints": [
            ("POST", "/api/coach/mesh/create", {
                "title": "Audit Test", "session_type": "group_discussion",
            }),
            ("GET", f"/api/coach/mesh/sessions/{FAKE_COACH}"),
            ("GET", "/api/coach/mesh/methods/therapist"),
        ],
    },
    {
        "tab": "Coach Nate Progress",
        "tab_num": 6,
        "endpoints": [
            ("GET", "/api/coach/nate-progress"),
            ("GET", f"/api/coach/nate-progress/{FAKE_COACH}"),
        ],
    },
    {
        "tab": "Assistant Oversight",
        "tab_num": 7,
        "endpoints": [
            ("GET", "/api/coach/hierarchy/assistant-metrics?days=30"),
            ("GET", f"/api/coach/hierarchy/assistant-clients/{FAKE_COACH}"),
        ],
    },
]

TRUSTED_CODES = {200, 400, 404, 422}


class CoachHierarchyAuditor:

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
        logger.info("CoachHierarchyAuditor started (3x daily, stagger 290s)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CoachHierarchyAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(290)
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
                logger.error("CoachHierarchyAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        token = self._resolve_token()
        results = []

        for tab in TAB_ENDPOINTS:
            tab_trusted = 0
            tab_total = 0
            for ep in tab["endpoints"]:
                tab_total += 1
                if ep[0] == "DB_CHECK":
                    ok = await self._check_table(ep[1])
                    if ok:
                        tab_trusted += 1
                else:
                    method = ep[0]
                    path = ep[1]
                    body = ep[2] if len(ep) > 2 else None
                    code = await self._check_endpoint(method, path, token, body)
                    if code in TRUSTED_CODES:
                        tab_trusted += 1
            results.append({
                "tab": tab["tab"],
                "tab_num": tab["tab_num"],
                "trusted": tab_trusted,
                "total": tab_total,
            })

        total = sum(r["total"] for r in results)
        trusted = sum(r["trusted"] for r in results)

        # Email silenced — Trust Enforcer sends consolidated report

        await self._log_activity(
            "system", "coach_hierarchy_audit_sent",
            f"Scorecard: {trusted}/{total} TRUSTED at {now.isoformat()}", "success",
        )
        logger.info("CoachHierarchyAuditor: %d/%d TRUSTED", trusted, total)

    def _resolve_token(self) -> str:
        if self._auth_token:
            return self._auth_token
        return os.environ.get("SKYEYE_AUDIT_TOKEN", "")

    async def _check_endpoint(self, method: str, path: str, token: str,
                               body: dict = None) -> int:
        url = f"{BASE_URL}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with aiohttp.ClientSession() as session:
                if method == "GET":
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        return resp.status
                elif method == "POST":
                    async with session.post(url, headers=headers, json=body or {},
                                            timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        return resp.status
        except Exception as e:
            logger.warning("Endpoint check failed %s %s: %s", method, path, e)
            return 500

    async def _check_table(self, table_name: str) -> bool:
        if not self.db_pool:
            return False
        try:
            async with self.db_pool.acquire() as conn:
                await conn.fetchval(f"SELECT COUNT(*) FROM {table_name}")
            return True
        except Exception as e:
            logger.warning("Table check failed %s: %s", table_name, e)
            return False

    async def _log_activity(self, platform: str, activity_type: str,
                             content: str, severity: str = "info"):
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                       VALUES ($1, $2, $3, $4, NOW())""",
                    platform, activity_type, content, severity,
                )
        except Exception as e:
            logger.warning("Activity log failed: %s", e)
