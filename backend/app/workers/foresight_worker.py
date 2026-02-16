"""
SOVEREIGN SWARM — Foresight Prediction Worker
4-stream synthesis, ForesightAlert generation, Strategic Memory Layer 5 storage.
"""

from __future__ import annotations

import asyncio
from typing import Any, List

import structlog

logger = structlog.get_logger(__name__)


class ForesightWorker:
    """
    Background worker for foresight predictions:
    4-stream synthesis, alert generation, storage in strategic memory Layer 5.
    """

    def __init__(
        self,
        foresight_engine: Any,
        pattern_engine: Any,
        strategic_memory: Any,
        interval: int = 21600,
    ) -> None:
        self.foresight_engine = foresight_engine
        self.pattern_engine = pattern_engine
        self.strategic_memory = strategic_memory
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
        # 1. Run 4-stream foresight synthesis
        synthesis: dict = {}
        try:
            synthesis = await self.foresight_engine.synthesize_streams()
        except Exception as e:
            logger.warning("foresight_synthesis_failed", error=str(e))

        # 2. Generate ForesightAlerts
        alerts: List[dict] = []
        try:
            alerts = await self.foresight_engine.generate_alerts()
        except Exception as e:
            logger.warning("foresight_alerts_failed", error=str(e))

        # 3. Store alerts in strategic memory Layer 5
        stored = 0
        if self.strategic_memory and hasattr(
            self.strategic_memory, "create_foresight_alert"
        ):
            for alert in alerts:
                try:
                    await self.strategic_memory.create_foresight_alert(alert)
                    stored += 1
                except Exception as e:
                    logger.warning(
                        "foresight_alert_store_failed",
                        signal=alert.get("signal_description", "")[:80],
                        error=str(e),
                    )

        logger.info(
            "foresight_tick_complete",
            streams_synthesized=len(synthesis.get("streams", {})),
            alerts_generated=len(alerts),
            alerts_stored=stored,
        )
