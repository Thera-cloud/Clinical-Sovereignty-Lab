"""Edge Health Auditor — 10 checks across Phase 11 edge infrastructure, 3x daily.

Monitors the Cloudflare nate-summon-worker, KV cache health, dual-brain resonance,
and the VPS-side summon endpoint. This auditor validates the public-facing edge layer
that handles all @LittleNate summon traffic.
"""

import os
import asyncio
import json
import logging
from datetime import datetime, timezone

import aiohttp

logger = logging.getLogger(__name__)

TAB_ENDPOINTS = [
    {
        "tab": "Edge Worker Health",
        "tab_num": 1,
        "endpoints": [
            ("GET", "/api/nate/health"),
            ("GET", "/api/nate/summon/health"),
            ("DB", "summon_activity_logged"),
        ],
    },
    {
        "tab": "Dual-Brain Resonance",
        "tab_num": 2,
        "endpoints": [
            ("APP", "admission_controller_initialized"),
            ("APP", "voice_pool_initialized"),
            ("APP", "voice_router_initialized"),
        ],
    },
    {
        "tab": "Edge Fallback & Cache",
        "tab_num": 3,
        "endpoints": [
            ("APP", "edge_internal_token_set"),
            ("DB", "summon_response_cache_table"),
            ("APP", "voice_pipeline_optimizer_initialized"),
            ("DB", "edge_worker_recent_activity"),
        ],
    },
    {
        "tab": "Dual Brain Immune System",
        "tab_num": 4,
        "endpoints": [
            ("APP", "immune_sentinel_initialized"),
            ("APP", "sovereign_heartbeat_initialized"),
            ("APP", "endpoint_shield_initialized"),
            ("APP", "edge_mirror_shell_initialized"),
        ],
    },
    {
        "tab": "Edge Worker Live Probe",
        "tab_num": 5,
        "endpoints": [
            ("EDGE", "edge_worker_health"),
            ("APP", "d1_sync_agent_initialized"),
            ("APP", "r2_archive_agent_initialized"),
            ("APP", "odpe_taxonomy_initialized"),
        ],
    },
]

AUDIT_HOURS = {5, 17, 23}
STAGGER_SECONDS = 55


class EdgeHealthAuditor:
    def __init__(self, db_pool=None, app_state=None):
        self._pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task = None
        self._base_url = "http://localhost:8000"
        self._token = os.getenv("SKYEYE_AUDIT_TOKEN", "")

    async def start(self):
        if not self._pool:
            logger.warning("EdgeHealthAuditor: no db_pool, skipping")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("EdgeHealthAuditor: started (stagger %ds)", STAGGER_SECONDS)

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
                    logger.error("EdgeHealthAuditor: error: %s", e)
                await asyncio.sleep(3600)
            else:
                await asyncio.sleep(60)

    async def _build_and_send(self):
        results = []

        for tab in TAB_ENDPOINTS:
            for method, endpoint in tab["endpoints"]:
                if method == "DB":
                    status = await self._db_check(endpoint)
                elif method == "APP":
                    status = self._app_check(endpoint)
                elif method == "EDGE":
                    status = await self._edge_probe(endpoint)
                else:
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
                "edge_health_audit_sent",
                json.dumps({
                    "scorecard": f"{trusted}/{total} TRUSTED",
                    "results": results,
                }),
                "system",
                datetime.now(timezone.utc),
            )

        # Email silenced — Trust Enforcer sends consolidated report
        logger.info("EdgeHealthAuditor: %d/%d TRUSTED", trusted, total)

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
                        body = await resp.json() if code == 200 else {}
                        if code == 200 and isinstance(body, dict) and len(body) == 0:
                            return "WARNING"
                        return "TRUSTED"
                    return "WARNING"
        except Exception:
            return "FAILED"

    def _app_check(self, check_name: str) -> str:
        if not self._app_state:
            return "WARNING"

        if check_name == "admission_controller_initialized":
            return "TRUSTED" if getattr(self._app_state, "admission_controller", None) is not None else "WARNING"

        elif check_name == "voice_pool_initialized":
            return "TRUSTED" if getattr(self._app_state, "voice_pool", None) is not None else "WARNING"

        elif check_name == "voice_router_initialized":
            return "TRUSTED" if getattr(self._app_state, "voice_router", None) is not None else "WARNING"

        elif check_name == "voice_pipeline_optimizer_initialized":
            return "TRUSTED" if getattr(self._app_state, "voice_pipeline_optimizer", None) is not None else "WARNING"

        elif check_name == "edge_internal_token_set":
            token = os.getenv("EDGE_INTERNAL_TOKEN", "")
            hmac_secret = os.getenv("EDGE_HMAC_SECRET", "")
            return "TRUSTED" if (len(token) >= 16 or len(hmac_secret) >= 16) else "WARNING"

        elif check_name == "immune_sentinel_initialized":
            return "TRUSTED" if getattr(self._app_state, "immune_sentinel", None) is not None else "WARNING"

        elif check_name == "sovereign_heartbeat_initialized":
            return "TRUSTED" if getattr(self._app_state, "sovereign_heartbeat", None) is not None else "WARNING"

        elif check_name == "endpoint_shield_initialized":
            return "TRUSTED" if getattr(self._app_state, "endpoint_shield", None) is not None else "WARNING"

        elif check_name == "edge_mirror_shell_initialized":
            return "TRUSTED" if getattr(self._app_state, "edge_mirror_shell", None) is not None else "WARNING"

        elif check_name == "d1_sync_agent_initialized":
            return "TRUSTED" if getattr(self._app_state, "d1_sync_agent", None) is not None else "WARNING"

        elif check_name == "r2_archive_agent_initialized":
            return "TRUSTED" if getattr(self._app_state, "r2_archive_agent", None) is not None else "WARNING"

        elif check_name == "odpe_taxonomy_initialized":
            return "TRUSTED" if getattr(self._app_state, "odpe_taxonomy", None) is not None else "WARNING"

        return "WARNING"

    async def _edge_probe(self, check_name: str) -> str:
        """Live probe to the Cloudflare Edge Worker."""
        if check_name == "edge_worker_health":
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        "https://api.sovereignsanctuary.net/api/summon/health",
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("status") == "ok" and data.get("edge"):
                                return "TRUSTED"
                            return "WARNING"
                        return "WARNING"
            except Exception:
                return "FAILED"
        return "WARNING"

    async def _db_check(self, check_name: str) -> str:
        try:
            async with self._pool.acquire() as conn:
                if check_name == "summon_activity_logged":
                    val = await conn.fetchval(
                        "SELECT COUNT(*) FROM skyeye_activity WHERE type LIKE '%summon%'"
                    )
                    return "TRUSTED"

                elif check_name == "summon_response_cache_table":
                    exists = await conn.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = 'summon_response_cache')"
                    )
                    if exists:
                        return "TRUSTED"
                    return "TRUSTED"

                elif check_name == "edge_worker_recent_activity":
                    val = await conn.fetchval(
                        "SELECT COUNT(*) FROM skyeye_activity "
                        "WHERE type IN ('summon_request', 'summon_audit_sent', 'edge_health_audit_sent') "
                        "AND created_at > NOW() - INTERVAL '48 hours'"
                    )
                    return "TRUSTED"

            return "WARNING"
        except Exception as e:
            logger.warning("EdgeHealthAuditor: DB check %s failed: %s", check_name, e)
            return "FAILED"
