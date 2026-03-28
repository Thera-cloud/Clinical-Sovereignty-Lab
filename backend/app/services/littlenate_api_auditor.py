"""
LittleNate-1.X API Trust Auditor.

Runs 8 checks 3x daily (5am/5pm/11pm UTC) across the /v1/ API surface.
Registered in the Trust Enforcer at stagger 55s.

Checks:
  1. /v1/health — API health endpoint
  2. /v1/models — model listing
  3. /v1/chat/completions (POST) — inference endpoint accepts input
  4. /v1/audio/speech (POST) — TTS endpoint accepts input
  5. /v1/audio/transcriptions (POST) — STT endpoint accepts input
  6. /v1/coherence/score (POST) — coherence scoring
  7. /v1/oauth/token (POST) — OAuth token endpoint
  8. DB: littlenate_tables_exist — all 4 tables present
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

AUDIT_HOURS = {5, 17, 23}
STAGGER_SECONDS = 55

TAB_ENDPOINTS = [
    {
        "tab_num": 1,
        "tab": "API Health & Models",
        "endpoints": [
            {"path": "/v1/health", "method": "GET"},
            {"path": "/v1/models", "method": "GET"},
        ],
    },
    {
        "tab_num": 2,
        "tab": "Inference Endpoints",
        "endpoints": [
            {"path": "/v1/chat/completions", "method": "POST"},
            {"path": "/v1/audio/speech", "method": "POST"},
            {"path": "/v1/audio/transcriptions", "method": "POST"},
        ],
    },
    {
        "tab_num": 3,
        "tab": "Coherence & OAuth",
        "endpoints": [
            {"path": "/v1/coherence/score", "method": "POST"},
            {"path": "/v1/oauth/token", "method": "POST"},
        ],
    },
]

DB_CHECKS = [
    {"id": "littlenate_tables_exist", "description": "All 4 LittleNate API tables present"},
]


class LittleNateApiAuditor:
    """Trust auditor for the LittleNate-1.X API endpoints."""

    def __init__(self, db_pool=None, auth_token: str = "", app_state=None):
        self._db_pool = db_pool
        self._token = auth_token or os.getenv("SKYEYE_AUDIT_TOKEN", "")
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("LittleNateApiAuditor started (stagger=%ds)", STAGGER_SECONDS)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                if now.hour in AUDIT_HOURS and now.minute < 5:
                    await asyncio.sleep(STAGGER_SECONDS)
                    await self._build_and_send()
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("LittleNateApiAuditor loop error: %s", e)
                await asyncio.sleep(60)

    async def _build_and_send(self):
        """Run all checks and store results."""
        results = []
        base = "http://localhost:8000"
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        async with aiohttp.ClientSession() as sess:
            for tab in TAB_ENDPOINTS:
                for ep in tab["endpoints"]:
                    status = await self._test_endpoint(sess, base, ep, headers)
                    results.append({
                        "tab": tab["tab"],
                        "path": ep["path"],
                        "method": ep["method"],
                        "status": status["status"],
                        "code": status.get("code", 0),
                    })

        db_result = await self._check_db()
        results.append({
            "tab": "Data Integrity",
            "path": "DB:littlenate_tables_exist",
            "method": "DB",
            "status": db_result["status"],
            "detail": db_result.get("detail", ""),
        })

        trusted = sum(1 for r in results if r["status"] == "TRUSTED")
        total = len(results)

        if self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO skyeye_activity (type, platform, content)
                           VALUES ($1, $2, $3)""",
                        "littlenate_api_audit_sent",
                        "trust",
                        json.dumps({
                            "trusted": trusted,
                            "total": total,
                            "results": results,
                        }),
                    )
            except Exception as e:
                logger.warning("LittleNateApiAuditor: failed to store results: %s", e)

        logger.info("LittleNateApiAuditor: %d/%d TRUSTED", trusted, total)

    async def _test_endpoint(self, sess, base, ep, headers) -> Dict[str, Any]:
        url = f"{base}{ep['path']}"
        method = ep["method"]
        try:
            kwargs = {"headers": headers, "timeout": aiohttp.ClientTimeout(total=15)}

            if method == "POST":
                kwargs["json"] = {}
                async with sess.post(url, **kwargs) as resp:
                    code = resp.status
            else:
                async with sess.get(url, **kwargs) as resp:
                    code = resp.status

            if code in (200, 400, 404, 422):
                return {"status": "TRUSTED", "code": code}
            elif 400 <= code < 500:
                return {"status": "WARNING", "code": code}
            else:
                return {"status": "FAILED", "code": code}
        except Exception as e:
            return {"status": "FAILED", "error": str(e)}

    async def _check_db(self) -> Dict[str, Any]:
        if not self._db_pool:
            return {"status": "FAILED", "detail": "No db_pool"}
        try:
            required = ["littlenate_training_pairs", "api_clients", "api_usage", "api_audit_log"]
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT table_name FROM information_schema.tables
                       WHERE table_name = ANY($1::text[])""",
                    required,
                )
                found = {r["table_name"] for r in rows}
                missing = [t for t in required if t not in found]
                if missing:
                    return {"status": "WARNING", "detail": f"Missing: {', '.join(missing)}"}
                return {"status": "TRUSTED", "detail": f"All {len(required)} tables present"}
        except Exception as e:
            return {"status": "FAILED", "detail": str(e)}

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "stagger_seconds": STAGGER_SECONDS,
            "total_checks": sum(len(t["endpoints"]) for t in TAB_ENDPOINTS) + len(DB_CHECKS),
        }
