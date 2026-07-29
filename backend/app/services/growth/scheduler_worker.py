"""Background worker: publish scheduled marketing_content when due.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from app.services.growth import growth_engine_enabled
from app.services.growth.marketing_content_service import MarketingContentService

logger = logging.getLogger("nate.growth.scheduler")


class GrowthSchedulerWorker:
    def __init__(self, db_pool, *, interval_s: int = 120):
        self.db_pool = db_pool
        self.interval_s = interval_s
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.svc = MarketingContentService(db_pool)

    async def start(self) -> None:
        if not growth_engine_enabled():
            logger.info("GrowthSchedulerWorker not started (ENABLE_GROWTH_ENGINE=false)")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("GrowthSchedulerWorker started (interval=%ss)", self.interval_s)

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
                logger.warning("GrowthSchedulerWorker tick failed: %s", e)
            await asyncio.sleep(self.interval_s)

    async def tick(self) -> Dict[str, Any]:
        published = 0
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id FROM marketing_content
                WHERE status = 'scheduled'
                  AND scheduled_at IS NOT NULL
                  AND scheduled_at <= NOW()
                ORDER BY scheduled_at ASC
                LIMIT 20
                """
            )
        for r in rows:
            try:
                await self.svc.publish(int(r["id"]), actor="growth_scheduler")
                published += 1
            except Exception as e:
                logger.warning("publish %s failed: %s", r["id"], e)
        return {"published": published, "checked": len(rows)}
