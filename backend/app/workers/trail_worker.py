"""
SOVEREIGN SWARM — Trail Map Worker
Trail aggregation, silent fibre detection, memorial encoding, Quakete transfers.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class TrailWorker:
    """
    Background worker for trail map operations:
    detect silent fibres, trigger memorials for confirmed losses,
    initiate Quakete transfers for struggling fibres.
    """

    def __init__(
        self,
        trail_map: Any,
        ring_manager: Any,
        memorial_service: Any,
        transfer_service: Any,
        interval: int = 60,
    ) -> None:
        self.trail_map = trail_map
        self.ring_manager = ring_manager
        self.memorial_service = memorial_service
        self.transfer_service = transfer_service
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
        # 1. Detect silent fibres (trail_map aggregates internally via update calls)
        silent: list[str] = []
        if hasattr(self.trail_map, "detect_silent_fibres"):
            try:
                silent = self.trail_map.detect_silent_fibres()
            except Exception as e:
                logger.warning("silent_detection_failed", error=str(e))

        # 2. Trigger memorial encoding for confirmed losses (silent beyond threshold)
        for fibre_id in silent:
            if self.memorial_service and not self.memorial_service.get_memorial(fibre_id):
                try:
                    trail = self.trail_map.get_fibre_trail(fibre_id)
                    if trail:
                        memorial = self.memorial_service.create_memorial(
                            lost_fibre_id=fibre_id,
                            lost_fibre_type=getattr(trail, "fibre_type", "unknown"),
                            last_health=getattr(trail, "communication_health", 0.0),
                            last_mission=getattr(trail, "current_mission", None),
                        )
                        logger.info(
                            "memorial_created",
                            fibre_id=fibre_id,
                            memorial_hash=(memorial.memorial_hash[:16] if memorial.memorial_hash else "n/a"),
                        )
                except Exception as e:
                    logger.warning(
                        "memorial_creation_failed",
                        fibre_id=fibre_id,
                        error=str(e),
                    )

        # 3. Initiate Quakete transfers for struggling fibres (REQUESTING/CRITICAL)
        health = self.trail_map.get_swarm_health() if hasattr(
            self.trail_map, "get_swarm_health"
        ) else {}
        requesting = health.get("requesting", 0)
        critical = health.get("critical", 0)

        transfer_count = 0
        if self.transfer_service and hasattr(
            self.transfer_service, "execute_transfer"
        ):
            # Get fibres needing support from trail map
            trails = getattr(self.trail_map, "_trails", {}) or {}
            for fid, trail in list(trails.items()):
                if fid in silent:
                    continue
                mode = getattr(trail, "quakete_mode", None)
                mode_str = mode.value if hasattr(mode, "value") else str(mode)
                health_val = getattr(trail, "communication_health", 1.0)
                if mode_str in ("requesting", "critical") or health_val < 0.3:
                    try:
                        result = await self.transfer_service.execute_transfer(fid)
                        success = result.success if hasattr(result, "success") else result.get("success", False)
                        if success:
                            transfer_count += 1
                    except Exception as e:
                        logger.debug(
                            "transfer_skipped",
                            fibre_id=fid,
                            error=str(e),
                        )
                    if transfer_count >= 3:
                        break  # limit per tick

        logger.debug(
            "trail_tick_complete",
            silent_count=len(silent),
            transfers_initiated=transfer_count,
            requesting=requesting,
            critical=critical,
        )
