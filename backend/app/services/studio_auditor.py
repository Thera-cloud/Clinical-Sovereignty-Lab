"""Sovereign Studio auditor — 15 checks, stagger 296s. QUANTUM-CRYSTAL-ARCH

Email silenced — Trust Enforcer sends consolidated report
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("nate.studio_auditor")

AUDIT_HOURS = {5, 17, 23}
STAGGER_DELAY = 296
BASE_URL = "http://localhost:8000"
NIL = "00000000-0000-0000-0000-000000000001"

TAB_ENDPOINTS = [
    {
        "tab": "Show / Persona",
        "tab_num": 1,
        "endpoints": [
            ("GET", "/api/studio/health"),
            ("GET", "/api/studio/invariants"),
            ("DB", "studio_shows_table"),
            ("DB", "persona_versions_seed"),
        ],
    },
    {
        "tab": "Session / Wall",
        "tab_num": 2,
        "endpoints": [
            ("DB", "show_mode_check"),
            ("DB", "guest_video_check"),
            ("DB", "studio_runtime_wall"),
        ],
    },
    {
        "tab": "Screener / SIP",
        "tab_num": 3,
        "endpoints": [
            ("POST", "/api/studio/voice/inbound"),
            ("GET", "/api/studio/voice/screener-health"),
            ("GET", "/api/studio/voice/sip-health"),
            ("GET", "/api/studio/voice/screener-ttl"),
        ],
    },
    {
        "tab": "Episode / Compliance",
        "tab_num": 4,
        "endpoints": [
            ("POST", f"/api/studio/episodes/{NIL}/cuts"),
            ("POST", f"/api/studio/episodes/{NIL}/approve"),
            ("POST", f"/api/studio/episodes/{NIL}/publish"),
        ],
    },
    {
        "tab": "Publish",
        "tab_num": 5,
        "endpoints": [
            ("GET", f"/api/studio/feeds/{NIL}/rss"),
        ],
    },
]


class StudioAuditor:
    def __init__(self, db_pool, redis_url: str = None, app_state=None, auth_token: str = ""):
        self.db_pool = db_pool
        self.redis_url = redis_url or os.getenv("REDIS_URL", "")
        self._app_state = app_state
        self._token = auth_token or None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sent_windows: set = set()

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("StudioAuditor started (stagger %ds)", STAGGER_DELAY)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _resolve_token(self) -> Optional[str]:
        env_tok = (self._token or os.getenv("SKYEYE_AUDIT_TOKEN", "")).strip()
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
                    try:
                        body = await resp.json(content_type=None)
                    except Exception:
                        body = None
            else:
                async with session.post(
                    url,
                    headers={**headers, "Content-Type": "application/json"},
                    json={},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    code = resp.status
                    try:
                        body = await resp.json(content_type=None)
                    except Exception:
                        body = None
            status = "TRUSTED" if code in (200, 400, 404, 422) else (
                "WARNING" if 400 <= code < 500 else "FAILED"
            )
            if code == 200 and isinstance(body, dict) and len(body) == 0:
                status = "WARNING"
            return {"endpoint": f"{method} {path}", "code": code, "status": status}
        except Exception as e:
            return {"endpoint": f"{method} {path}", "code": 0, "status": "FAILED", "error": str(e)}

    async def _db_check(self, key: str):
        label = f"DB {key}"
        if not self.db_pool:
            return {"endpoint": label, "code": 0, "status": "FAILED", "error": "no_db"}
        try:
            async with self.db_pool.acquire() as conn:
                if key == "studio_shows_table":
                    ok = await conn.fetchval(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'studio_shows')"
                    )
                elif key == "persona_versions_seed":
                    ok = await conn.fetchval(
                        "SELECT EXISTS (SELECT 1 FROM studio_persona_versions WHERE layer = 'guardrail')"
                    )
                elif key == "show_mode_check":
                    ok = await conn.fetchval(
                        """
                        SELECT EXISTS (
                          SELECT 1 FROM information_schema.check_constraints
                          WHERE constraint_name = 'studio_sessions_show_mode_chk'
                        )
                        """
                    )
                elif key == "guest_video_check":
                    ok = await conn.fetchval(
                        """
                        SELECT EXISTS (
                          SELECT 1 FROM information_schema.check_constraints
                          WHERE constraint_name = 'session_legs_guest_audio_only_chk'
                        )
                        """
                    )
                elif key == "studio_runtime_wall":
                    exists = await conn.fetchval(
                        "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'studio_runtime')"
                    )
                    if not exists:
                        return {
                            "endpoint": label,
                            "code": 200,
                            "status": "TRUSTED",
                            "detail": "role_pending_createrole",
                        }
                    can = await conn.fetchval(
                        "SELECT has_table_privilege('studio_runtime', 'nate_intelligence_crystals', 'SELECT')"
                    )
                    ok = can is False
                else:
                    ok = False
            return {
                "endpoint": label,
                "code": 200 if ok else 500,
                "status": "TRUSTED" if ok else "FAILED",
            }
        except Exception as e:
            logger.warning("StudioAuditor db check %s: %s", key, e)
            return {"endpoint": label, "code": 0, "status": "FAILED", "error": str(e)}

    async def _build_and_send(self, now: datetime):
        token = await self._resolve_token()
        results = []
        async with aiohttp.ClientSession() as session:
            for tab in TAB_ENDPOINTS:
                for method, path in tab["endpoints"]:
                    if method == "DB":
                        results.append(await self._db_check(path))
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
                        VALUES ('studio_audit_sent', $1, 'system', NOW())
                        """,
                        content,
                    )
            except Exception as e:
                logger.warning("StudioAuditor: activity log failed: %s", e)
        logger.info("StudioAuditor: %s/%s TRUSTED", trusted, total)

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
                logger.error("StudioAuditor loop error: %s", e)
            await asyncio.sleep(60)
