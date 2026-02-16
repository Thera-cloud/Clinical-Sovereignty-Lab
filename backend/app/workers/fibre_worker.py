"""
SOVEREIGN SWARM — Fibre Lifecycle Worker
Periodic fibre alignment, promotion/demotion, quarantine detection.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
from uuid import UUID

import structlog

from app.models.fibre import AutonomyLevel

logger = structlog.get_logger(__name__)


class FibreLifecycleWorker:
    """
    Background worker for fibre lifecycle operations:
    alignment checks, autonomy evaluations, quarantine candidate detection.
    """

    def __init__(
        self,
        fibre_manager: Any,
        immunity: Any,
        interval: int = 300,
    ) -> None:
        self.fibre_manager = fibre_manager
        self.immunity = immunity
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
        # 1. Check alignment across all fibres
        reports = await self.fibre_manager.check_alignment(fibre_id=None)
        for i, report in enumerate(reports):
            logger.info(
                "fibre_alignment_check",
                overall_passing=report.get("overall_passing"),
                dimensions=report.get("dimensions", {}),
            )

        # 2. Run promotion/demotion evaluations for each fibre
        inventory = await self.fibre_manager.inventory()
        for item in inventory:
            fibre_id_str = item.get("fibre_id")
            if not fibre_id_str:
                continue
            try:
                fibre_id = UUID(fibre_id_str)
            except (ValueError, TypeError):
                continue
            # Only attempt upgrade for observation/restricted
            autonomy = item.get("autonomy", "")
            if autonomy in (AutonomyLevel.OBSERVATION.value, AutonomyLevel.RESTRICTED.value):
                try:
                    result = await self.fibre_manager.upgrade_autonomy(fibre_id)
                    if result.get("result") == "upgraded":
                        logger.info(
                            "fibre_autonomy_upgraded",
                            fibre_id=fibre_id_str,
                            from_level=result.get("from"),
                            to_level=result.get("to"),
                        )
                except Exception as e:
                    logger.debug(
                        "autonomy_eval_skipped",
                        fibre_id=fibre_id_str,
                        error=str(e),
                    )

        # 3. Detect quarantine candidates via immunity service
        if self.immunity:
            try:
                # Check for fibres with anomaly indicators
                anomalies = getattr(self.immunity, "get_anomaly_candidates", None)
                if callable(anomalies):
                    candidates = await anomalies() if asyncio.iscoroutinefunction(anomalies) else anomalies()
                    for c in (candidates or []):
                        logger.info(
                            "quarantine_candidate_detected",
                            fibre_id=str(c) if hasattr(c, "__str__") else c,
                        )
            except Exception as e:
                logger.debug("quarantine_check_skipped", error=str(e))

        logger.debug(
            "fibre_lifecycle_tick_complete",
            fibres_checked=len(reports),
            inventory_count=len(inventory),
        )
