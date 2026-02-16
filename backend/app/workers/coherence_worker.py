"""
SOVEREIGN SWARM — Coherence Calculation Worker
Periodic 5-layer coherence measurement and threshold monitoring.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

# Score thresholds below which we log warnings (0.0-1.0)
SCORE_WARNING_THRESHOLD = 0.3


class CoherenceWorker:
    """
    Background worker for coherence calculations:
    measure all 5 layers, store results, check thresholds, generate gap alerts.
    """

    def __init__(
        self,
        coherence_engine: Any,
        db_pool: Any,
        interval: int = 600,
    ) -> None:
        self.coherence_engine = coherence_engine
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
                await self._tick()
            except Exception as e:
                logger.error(
                    "worker_error",
                    worker=self.__class__.__name__,
                    error=str(e),
                )
            await asyncio.sleep(self.interval)

    async def _tick(self) -> None:
        # 1. Calculate coherence across all 5 layers
        layer_scores: dict[str, float] = {}
        try:
            # measure_global cascades through layers; generate_pulse_snapshot does the full run
            snapshot = await self.coherence_engine.generate_pulse_snapshot()
            layer_scores = snapshot.layer_scores or {}
            layer_scores["global"] = snapshot.global_coherence_index
        except Exception as e:
            logger.warning("coherence_snapshot_failed", error=str(e))

        # 2. Store via briefing (persists to Strategic Memory Layer 4)
        try:
            await self.coherence_engine.generate_briefing(persist=True)
        except Exception as e:
            logger.warning("coherence_briefing_store_failed", error=str(e))

        # 3. Check for threshold violations (score too low)
        for layer_name, score in layer_scores.items():
            if score < SCORE_WARNING_THRESHOLD:
                logger.warning(
                    "coherence_threshold_violation",
                    layer=layer_name,
                    score=score,
                    threshold=SCORE_WARNING_THRESHOLD,
                )

        # 4. Gap analysis — check for inside/outside coherence gap
        try:
            gap = await self.coherence_engine.compute_gap_analysis()
            if gap and abs(gap.gap_magnitude) > 0.2:
                logger.info(
                    "coherence_gap_detected",
                    internal=gap.internal_score,
                    external=gap.external_score,
                    gap_magnitude=gap.gap_magnitude,
                )
        except Exception as e:
            logger.debug("gap_analysis_skipped", error=str(e))

        logger.debug(
            "coherence_tick_complete",
            layers=len(layer_scores),
        )
