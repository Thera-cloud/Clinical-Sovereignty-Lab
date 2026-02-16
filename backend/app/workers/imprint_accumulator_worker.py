"""
SOVEREIGN SWARM — Imprint Accumulator Worker
Periodically flushes buffered imprints and processes new session data.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class ImprintAccumulatorWorker:
    """Background worker: imprint buffer flush and processing."""

    def __init__(self, accumulator: Any, interval: int = 60) -> None:
        self.accumulator = accumulator
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
        # Final flush
        if self.accumulator:
            await self.accumulator.flush_all()
        logger.info("worker_stopped", worker=self.__class__.__name__)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                flushed = await self.accumulator.flush_all()
                if flushed > 0:
                    logger.info("imprints_flushed", count=flushed)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("imprint_worker_error", error=str(e))
            await asyncio.sleep(self.interval)
