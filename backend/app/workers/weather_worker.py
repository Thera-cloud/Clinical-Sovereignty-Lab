"""
SOVEREIGN SWARM — Weather Worker
Real-time emotional weather map updates for active Family Sanctuary sessions.
Updates every 5 seconds.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class WeatherWorker:
    """Background worker: real-time weather map updates for active sessions."""

    def __init__(
        self,
        emotional_weather: Any,
        session_interface: Any = None,
        interval: int = 5,
    ) -> None:
        self.emotional_weather = emotional_weather
        self.session_interface = session_interface
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
                await self._update_all_sessions()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("weather_worker_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def _update_all_sessions(self) -> None:
        """Update weather maps for all active sessions."""
        sessions = self.emotional_weather.get_active_sessions()
        for sanctuary_id in sessions:
            try:
                weather = self.emotional_weather.get_weather_map(sanctuary_id)
                if not weather:
                    continue

                # Generate intervention recommendation
                intervention = await self.emotional_weather.generate_intervention(
                    sanctuary_id
                )

                # Notify coach via session interface if significant
                if intervention and self.session_interface and intervention.intervention_type != "observe":
                    if intervention.intervention_type in ("de_escalate", "deepen"):
                        await self.session_interface.notify_weather_change(
                            session_id=sanctuary_id,
                            change_type="escalation" if intervention.intervention_type == "de_escalate" else "bridge_opportunity",
                            details=intervention.clinical_reasoning or "",
                        )

            except Exception as e:
                logger.warning(
                    "weather_update_error",
                    sanctuary_id=sanctuary_id,
                    error=str(e),
                )
