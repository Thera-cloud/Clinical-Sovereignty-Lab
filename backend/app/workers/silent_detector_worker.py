"""
SOVEREIGN SWARM — Silent Detector Worker
15-minute sweep across all active members via the Silent Fibre Detector.
Generates alerts for members who have gone silent.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class SilentDetectorWorker:
    """Background worker: 15-minute sweeps for silent members."""

    def __init__(
        self,
        silent_detector: Any,
        interval: int = 900,  # 15 minutes
    ) -> None:
        self.silent_detector = silent_detector
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
                alerts = await self.silent_detector.sweep()
                if alerts:
                    logger.info(
                        "silent_sweep_complete",
                        alerts_generated=len(alerts),
                        critical=sum(1 for a in alerts if a.alert_level.value == "critical"),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("silent_detector_error", error=str(e))
            await asyncio.sleep(self.interval)
