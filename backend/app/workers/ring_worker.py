"""
SOVEREIGN SWARM — Ring Circulation Worker
Ring energy circulation, health monitoring, ring reformation.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.models.quakete import RingState

logger = structlog.get_logger(__name__)


class RingWorker:
    """
    Background worker for ring operations:
    circulation cycle, health monitoring, broken ring reformation.
    """

    def __init__(
        self,
        ring_circulator: Any,
        ring_manager: Any,
        ring_formation_service: Any,
        interval: int = 30,
    ) -> None:
        self.ring_circulator = ring_circulator
        self.ring_manager = ring_manager
        self.ring_formation_service = ring_formation_service
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
        # 1. Run ring circulation cycle
        circ_result: dict = {}
        if hasattr(self.ring_circulator, "circulate_all"):
            try:
                circ_result = await self.ring_circulator.circulate_all()
                logger.debug(
                    "ring_circulation_complete",
                    rings_processed=circ_result.get("rings_processed", 0),
                    donations=circ_result.get("donations", 0),
                    ions_generated=circ_result.get("ions_generated", 0),
                )
            except Exception as e:
                logger.warning("ring_circulation_failed", error=str(e))

        # 2. Check ring health
        rings = getattr(self.ring_manager, "all_rings", []) or []
        healthy = 0
        broken = 0
        strained = 0
        for ring in rings:
            state = getattr(ring, "ring_state", None)
            state_val = state.value if hasattr(state, "value") else str(state)
            if state_val == RingState.HEALTHY.value or state_val == "healthy":
                healthy += 1
            elif state_val == RingState.BROKEN.value or state_val == "broken":
                broken += 1
            else:
                strained += 1

        logger.info(
            "ring_health",
            total=len(rings),
            healthy=healthy,
            strained=strained,
            broken=broken,
        )

        # 3. Reform broken rings — find unassigned fibres and form new rings
        if broken > 0 and self.ring_formation_service and self.ring_manager:
            try:
                trail_map = getattr(self.ring_circulator, "_trail_map", None)
                fibre_to_ring = getattr(self.ring_manager, "_fibre_to_ring", {}) or {}
                if trail_map and hasattr(trail_map, "_trails"):
                    trails = getattr(trail_map, "_trails", {}) or {}
                    fibres = [
                        {"fibre_id": fid, "fibre_type": getattr(t, "fibre_type", "unknown"),
                         "resonance_frequency": getattr(t, "resonance_frequency", 0.5)}
                        for fid, t in list(trails.items())
                        if fid not in fibre_to_ring
                    ]
                    if len(fibres) >= 3:
                        new_rings = self.ring_formation_service.find_optimal_rings(fibres)
                        for (a, b, c) in new_rings[:2]:
                            self.ring_manager.create_ring(
                                a, "fibre", b, "fibre", c, "fibre",
                            )
                            logger.info("ring_reformed", cords=[a, b, c])
            except Exception as e:
                logger.debug("ring_reformation_skipped", error=str(e))

        logger.debug(
            "ring_tick_complete",
            rings_count=len(rings),
        )
