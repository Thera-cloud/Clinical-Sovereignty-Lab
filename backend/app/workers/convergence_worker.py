"""
SOVEREIGN SWARM — Convergence Scanning Worker
Cross-fibre convergence detection and escalation to Sovereign Mind.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, List
from uuid import UUID

import structlog

from app.models.mesh import ConvergenceAlert

logger = structlog.get_logger(__name__)

CONVERGENCE_FIBRE_THRESHOLD = 3


class ConvergenceWorker:
    """
    Background worker for convergence detection:
    scan mesh messages, aggregate themes, create alerts when >= 3 fibres converge,
    escalate to Sovereign Mind.
    """

    def __init__(
        self,
        wisdom_mesh: Any,
        sovereign_mind: Any,
        interval: int = 120,
    ) -> None:
        self.wisdom_mesh = wisdom_mesh
        self.sovereign_mind = sovereign_mind
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
        # 1. Scan recent mesh messages for convergence
        alerts: List[ConvergenceAlert] = []
        if hasattr(self.wisdom_mesh, "detect_convergence"):
            try:
                alerts = await self.wisdom_mesh.detect_convergence()
            except Exception as e:
                logger.warning("detect_convergence_failed", error=str(e))

        if not alerts:
            logger.debug("convergence_tick_no_alerts")
            return

        # 2. Aggregate matching themes — group by topic, count unique fibres
        theme_to_fibres: dict[str, set[UUID]] = defaultdict(set)
        for a in alerts:
            theme = a.topic or "general"
            for fid in a.converging_fibre_ids:
                theme_to_fibres[theme].add(fid)

        # 3. Create ConvergenceAlert and escalate when >= 3 fibres on same theme
        for theme, fibre_ids in theme_to_fibres.items():
            if len(fibre_ids) >= CONVERGENCE_FIBRE_THRESHOLD:
                # Find best matching alert for this theme
                best_alert = next(
                    (a for a in alerts if (a.topic or "general") == theme),
                    None,
                )
                logger.info(
                    "convergence_threshold_met",
                    theme=theme,
                    fibre_count=len(fibre_ids),
                    fibre_ids=[str(f) for f in fibre_ids],
                )
                # 4. Escalate to sovereign mind (log to strategic memory)
                if self.sovereign_mind:
                    memory = getattr(self.sovereign_mind, "strategic_memory", None)
                    if memory and hasattr(memory, "log_insight"):
                        try:
                            body = (
                                f"Convergence detected: {len(fibre_ids)} fibres on theme '{theme}'"
                            )
                            await memory.log_insight(
                                title=f"Convergence: {theme}",
                                body=body,
                                domain="convergence",
                                confidence=0.8,
                                tags=["convergence", theme],
                                metadata={
                                    "theme": theme,
                                    "fibre_count": len(fibre_ids),
                                    "fibre_ids": [str(f) for f in fibre_ids],
                                    "alert_id": str(best_alert.alert_id) if best_alert else None,
                                },
                            )
                            logger.info(
                                "convergence_escalated",
                                theme=theme,
                            )
                        except Exception as e:
                            logger.warning(
                                "convergence_escalation_failed",
                                theme=theme,
                                error=str(e),
                            )

        logger.debug(
            "convergence_tick_complete",
            alerts_found=len(alerts),
            themes_escalated=sum(
                1 for s in theme_to_fibres.values() if len(s) >= CONVERGENCE_FIBRE_THRESHOLD
            ),
        )
