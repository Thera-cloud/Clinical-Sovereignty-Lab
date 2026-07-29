"""Background outreach health + optional reply drain (ENABLE_OUTREACH_ENGINE).

Pushing campaigns is driven by marketing_content publish/scheduler — this worker
tracks Instantly health / circuit state for digest + service checks.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from app.services.growth import outreach_engine_enabled
from app.services.growth.instantly_client import InstantlyClient

logger = logging.getLogger("nate.growth.outreach_worker")


class OutreachWorker:
    def __init__(self, db_pool, *, interval_s: int = 600):
        self.db_pool = db_pool
        self.interval_s = interval_s
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.last_health: Dict[str, Any] = {"status": "init"}

    async def start(self) -> None:
        if not outreach_engine_enabled():
            logger.info("OutreachWorker not started (ENABLE_OUTREACH_ENGINE=false)")
            return
        client = InstantlyClient()
        if not client.configured:
            self.last_health = {
                "status": "degraded",
                "ok": False,
                "error": "INSTANTLY_API_KEY missing",
            }
            logger.warning("OutreachWorker degraded — Instantly not configured")
            # Still mark running so service check is truthy; health reports degraded.
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("OutreachWorker started (interval=%ss)", self.interval_s)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except Exception as e:
                logger.warning("OutreachWorker tick failed: %s", e)
            await asyncio.sleep(self.interval_s)

    async def tick(self) -> Dict[str, Any]:
        if not outreach_engine_enabled():
            return {"skipped": True}
        client = InstantlyClient()
        health = await client.health()
        self.last_health = health
        return {"health": health}
