"""
SOVEREIGN SWARM — Fibre Trail Emission
Patent Claim 26.1a: Collisionless Fibre Trail Emission Protocol.

Trail emissions are the Fibre's heartbeat — they tell the swarm
'I am here, I am alive, this is how I am doing.'
"""

from __future__ import annotations

import asyncio
from typing import Callable, Optional

from app.models.quakete import FibreTrailEmission, QuaketeMode

from .constants import TRAIL_FLAG_MASK


# =============================================================================
# TRAIL FLAG ENCODER (Patent Claim 26.1a)
# =============================================================================


def encode_trail_flag(fragment_flags: int) -> int:
    """Set TRAIL_FLAG_MASK bit on fragment FLAGS byte."""
    return fragment_flags | TRAIL_FLAG_MASK


# =============================================================================
# TRAIL EMITTER
# =============================================================================


class TrailEmitter:
    """
    Emits FibreTrailEmission heartbeats at regular intervals.
    Supports both one-shot emit() and periodic background emission.
    """

    def __init__(
        self,
        fibre_id: str,
        fibre_type: str,
        swarm_secret: bytes,
    ) -> None:
        self.fibre_id = fibre_id
        self.fibre_type = fibre_type
        self.swarm_secret = swarm_secret
        self._trail_sequence = 0
        self._periodic_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    @property
    def trail_sequence(self) -> int:
        """Auto-incrementing counter for trail ordering."""
        return self._trail_sequence

    def emit(
        self,
        ble_density: float,
        throughput: float,
        queue_depth: int,
        time_since_delivery: int,
        quakete_mode: QuaketeMode,
        surplus: float,
        deficit: float,
        resonance: float,
        ring_id: Optional[str] = None,
        ring_position: Optional[int] = None,
        ring_partners: Optional[list] = None,
    ) -> FibreTrailEmission:
        """
        Create a FibreTrailEmission with all telemetry.
        Computes communication_health from throughput and BLE density.
        """
        self._trail_sequence += 1

        communication_health = min(
            1.0,
            throughput / max(ble_density * 0.01, 0.001),
        )

        return FibreTrailEmission(
            fibre_id=self.fibre_id,
            fibre_type=self.fibre_type,
            trail_sequence=self._trail_sequence,
            ambient_ble_density=ble_density,
            fragment_throughput=throughput,
            observation_queue_depth=queue_depth,
            time_since_last_delivery=time_since_delivery,
            communication_health=communication_health,
            quakete_mode=quakete_mode,
            surplus_capacity=surplus,
            deficit_capacity=deficit,
            resonance_frequency=resonance,
            ring_id=ring_id,
            ring_position=ring_position,
            ring_partners=ring_partners or [],
        )

    def encode_trail_flag(self, fragment_flags: int) -> int:
        """Set TRAIL_FLAG_MASK bit on fragment FLAGS byte."""
        return encode_trail_flag(fragment_flags)

    async def start_periodic_emission(
        self,
        interval: int = 60,
        callback: Optional[Callable] = None,
    ) -> None:
        """
        Background task that emits trails every interval seconds.
        callback(trail) is invoked after each emission when provided.
        Uses default telemetry; callback may optionally return dict of emit() kwargs.
        """
        self._stop_event.clear()

        default_telemetry = {
            "ble_density": 0.0,
            "throughput": 0.0,
            "queue_depth": 0,
            "time_since_delivery": 0,
            "quakete_mode": QuaketeMode.NOMINAL,
            "surplus": 0.0,
            "deficit": 0.0,
            "resonance": 0.0,
            "ring_id": None,
            "ring_position": None,
            "ring_partners": None,
        }

        async def _tick() -> None:
            while not self._stop_event.is_set():
                try:
                    await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    break
                if self._stop_event.is_set():
                    break

                try:
                    kwargs = default_telemetry.copy()
                    trail = self.emit(**kwargs)
                    if callback:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(trail)
                        else:
                            callback(trail)
                except Exception:
                    pass

        self._periodic_task = asyncio.create_task(_tick())

    async def stop(self) -> None:
        """Cancel periodic emission task."""
        self._stop_event.set()
        if self._periodic_task and not self._periodic_task.done():
            self._periodic_task.cancel()
            try:
                await self._periodic_task
            except asyncio.CancelledError:
                pass
        self._periodic_task = None
