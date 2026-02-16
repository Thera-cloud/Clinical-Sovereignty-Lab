"""
SOVEREIGN SWARM — Autonomy Review Worker
Periodic evaluation of all Fibres for promotion/demotion.
Runs every 6 hours.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class AutonomyReviewWorker:
    """Background worker: periodic autonomy review for all Fibres."""

    def __init__(
        self,
        autonomy_manager: Any,
        fibre_manager: Any = None,
        interval: int = 21600,  # 6 hours
    ) -> None:
        self.autonomy_manager = autonomy_manager
        self.fibre_manager = fibre_manager
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
                await self._review_all_fibres()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("autonomy_review_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def _review_all_fibres(self) -> None:
        """Review all active Fibres for promotion/demotion."""
        fibre_ids = await self._get_active_fibre_ids()
        promotions = 0
        demotions = 0

        for fibre_id in fibre_ids:
            try:
                # Check for promotion
                new_level = await self.autonomy_manager.evaluate_promotion(fibre_id)
                if new_level:
                    promotions += 1
                    continue

                # Check for demotion
                new_level = await self.autonomy_manager.evaluate_demotion(fibre_id)
                if new_level:
                    demotions += 1
            except Exception as e:
                logger.warning(
                    "autonomy_review_fibre_error",
                    fibre_id=fibre_id,
                    error=str(e),
                )

        if promotions or demotions:
            logger.info(
                "autonomy_review_complete",
                fibres_reviewed=len(fibre_ids),
                promotions=promotions,
                demotions=demotions,
            )

    async def _get_active_fibre_ids(self) -> list:
        """Get all active fibre IDs."""
        if self.fibre_manager:
            try:
                return await self.fibre_manager.get_active_fibre_ids()
            except Exception:
                pass
        return []
