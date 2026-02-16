"""
SOVEREIGN SWARM — BLE Assembly Worker
Cloud-side fragment buffer maintenance and completed observation forwarding.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class BLEAssemblyWorker:
    """
    Background worker for ZEFCP fragment buffer:
    purge expired assemblies, forward completed observations, log metrics.
    """

    def __init__(
        self,
        fragment_buffer: Any,
        zefcp_bridge: Any,
        interval: int = 5,
    ) -> None:
        self.fragment_buffer = fragment_buffer
        self.zefcp_bridge = zefcp_bridge
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
                await self._tick()
            except Exception as e:
                logger.error(
                    "worker_error",
                    worker=self.__class__.__name__,
                    error=str(e),
                )
            await asyncio.sleep(self.interval)

    async def _tick(self) -> None:
        # 1. Purge expired assemblies
        expired_count = 0
        if hasattr(self.fragment_buffer, "purge_expired"):
            try:
                expired_count = await self.fragment_buffer.purge_expired()
            except Exception as e:
                logger.warning("purge_expired_failed", error=str(e))

        # 2. Forward any completed observations (buffer returns from ingest;
        #    cloud assembly coordinator forwards on reconstruction.
        #    No drain queue — forwarding happens in ingest path.)
        forwarded = 0
        if hasattr(self.fragment_buffer, "pending") and self.zefcp_bridge:
            # Buffer doesn't store completed obs; they're returned from ingest.
            # Log that forwarding is handled by assembly coordinator.
            pass

        # 3. Log assembly metrics
        pending_count = 0
        if hasattr(self.fragment_buffer, "pending_count"):
            pending_count = self.fragment_buffer.pending_count
        elif hasattr(self.fragment_buffer, "pending"):
            pending_count = len(self.fragment_buffer.pending)

        logger.info(
            "ble_assembly_metrics",
            pending_count=pending_count,
            expired_count=expired_count,
            forwarded=forwarded,
        )
