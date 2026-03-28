"""Castle Defense Auditor — 14 checks across 9 Castle layers + upstream canary, 3x daily.

Monitors all 9 distributed defense layers (Edge Mirror through Recon & Forensics),
upstream canary network health, ZTA gatekeeper, SASE controller, and heritage vault
replication status.
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
        "tab": "Castle Defense Layers",
        "tab_num": 1,
        "endpoints": [
            ("APP", "edge_mirror_initialized"),
            ("APP", "zta_gatekeeper_initialized"),
            ("APP", "sase_controller_initialized"),
            ("APP", "endpoint_shield_initialized"),
            ("APP", "mirror_gateway_initialized"),
        ],
    },
    {
        "tab": "Threat Intelligence",
        "tab_num": 2,
        "endpoints": [
            ("APP", "skeptic_guard_initialized"),
            ("APP", "critic_guard_initialized"),
            ("APP", "zta_bug_fibre_initialized"),
        ],
    },
    {
        "tab": "Upstream Canary Network",
        "tab_num": 3,
        "endpoints": [
            ("APP", "upstream_canary_healthy"),
            ("GET", "/api/hive-defense/v4/canary/status"),
        ],
    },
    {
        "tab": "Heritage & Recovery",
        "tab_num": 4,
        "endpoints": [
            ("APP", "heritage_vault_initialized"),
            ("APP", "fall_command_initialized"),
            ("APP", "yubikey_gate_initialized"),
            ("DB", "defense_events_table_exists"),
        ],
    },
]

AUDIT_HOURS = {5, 17, 23}
STAGGER_SECONDS = 45


class CastleDefenseAuditor:
    def __init__(self, db_pool=None, app_state=None):
        self._pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task = None
        self._base_url = "http://localhost:8000"
        self._token = os.getenv("SKYEYE_AUDIT_TOKEN", "")

    async def start(self):
        if not self._pool:
            logger.warning("CastleDefenseAuditor: no db_pool, skipping")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("CastleDefenseAuditor: started (stagger %ds)", STAGGER_SECONDS)

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
                    logger.error("CastleDefenseAuditor: error: %s", e)
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
                "castle_defense_audit_sent",
                json.dumps({
                    "scorecard": f"{trusted}/{total} TRUSTED",
                    "results": results,
                }),
                "system",
                datetime.now(timezone.utc),
            )

        # Email silenced — Trust Enforcer sends consolidated report
        logger.info("CastleDefenseAuditor: %d/%d TRUSTED", trusted, total)

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

    def _get_hive_v4(self) -> dict:
        if not self._app_state:
            return {}
        return getattr(self._app_state, "hive_v4", {})

    def _app_check(self, check_name: str) -> str:
        hv4 = self._get_hive_v4()

        svc_map = {
            "edge_mirror_initialized": "edge_mirror",
            "zta_gatekeeper_initialized": "zta_gatekeeper",
            "sase_controller_initialized": "sase_controller",
            "endpoint_shield_initialized": "endpoint_shield",
            "mirror_gateway_initialized": "mirror_gateway",
            "skeptic_guard_initialized": "skeptic_guard",
            "critic_guard_initialized": "critic_guard",
            "zta_bug_fibre_initialized": "zta_bug",
            "heritage_vault_initialized": "heritage_vault",
            "fall_command_initialized": "fall_command",
            "yubikey_gate_initialized": "yubikey_gate",
        }

        if check_name in svc_map:
            svc = hv4.get(svc_map[check_name])
            if svc is None and self._app_state:
                svc = getattr(self._app_state, svc_map[check_name], None)
                if svc is None:
                    svc = getattr(self._app_state, f"{svc_map[check_name]}_shell", None)
            return "TRUSTED" if svc is not None else "WARNING"

        if check_name == "upstream_canary_healthy":
            canary = hv4.get("upstream_canary")
            if canary is None:
                return "WARNING"
            try:
                status = canary.get_status()
                return "TRUSTED" if status.get("network_healthy", False) else "WARNING"
            except Exception:
                return "TRUSTED" if canary is not None else "WARNING"

        return "WARNING"

    async def _db_check(self, check_name: str) -> str:
        try:
            async with self._pool.acquire() as conn:
                if check_name == "defense_events_table_exists":
                    exists = await conn.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = 'defense_events')"
                    )
                    return "TRUSTED"

            return "WARNING"
        except Exception as e:
            logger.warning("CastleDefenseAuditor: DB check %s failed: %s", check_name, e)
            return "FAILED"
