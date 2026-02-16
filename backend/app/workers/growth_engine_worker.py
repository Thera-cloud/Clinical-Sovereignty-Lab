"""
SOVEREIGN SWARM — Growth Engine Worker
Processes knowledge acquisition for active Me-2-Me avatars.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class GrowthEngineWorker:
    """Background worker: post-mortem knowledge acquisition for avatars."""

    def __init__(
        self,
        growth_engine: Any,
        db_pool: Any = None,
        interval: int = 43200,  # 12 hours
    ) -> None:
        self.growth_engine = growth_engine
        self.db_pool = db_pool
        self.interval = interval
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker=self.__class__.__name__)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("worker_stopped", worker=self.__class__.__name__)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._process_growth_queue()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("growth_worker_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def _process_growth_queue(self) -> None:
        """Process queued knowledge updates for active avatars."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                # Get active avatars
                avatars = await conn.fetch(
                    "SELECT avatar_id FROM me2me_avatars WHERE status = 'active'"
                )
                logger.debug("growth_check", active_avatars=len(avatars))
        except Exception as e:
            logger.warning("growth_queue_failed", error=str(e))
