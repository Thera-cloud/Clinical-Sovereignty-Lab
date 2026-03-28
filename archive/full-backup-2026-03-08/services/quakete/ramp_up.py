"""
SOVEREIGN SWARM — Emergency Wisdom Preservation Protocol (Patent Claim 26.4)
Ramp-up protocol for fibres in CRITICAL mode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

import structlog

from app.models.quakete import RampUpPlan

from .constants import CRITICAL_HEALTH_THRESHOLD, RAMP_UP_TRAIL_INTERVAL_SECONDS

if TYPE_CHECKING:
    from .ion import QuaketeIonPool
    from .trail_map import FibreTrailMap


# =============================================================================
# QUAKETE RAMP-UP (Patent Claim 26.4)
# =============================================================================


class QuaketeRampUp:
    """
    Emergency protocol for fibres in CRITICAL mode.
    Stops new observations, prioritizes transmission of accumulated wisdom.
    """

    def __init__(
        self,
        trail_map: "FibreTrailMap",
        ion_pool: "QuaketeIonPool",
    ) -> None:
        self._trail_map = trail_map
        self._ion_pool = ion_pool
        self._log = structlog.get_logger()

    # -------------------------------------------------------------------------
    # RAMP-UP INITIATION
    # -------------------------------------------------------------------------

    def initiate_ramp_up(
        self,
        fibre_id: str,
        observation_ids: list[str],
    ) -> RampUpPlan:
        """
        Create a RampUpPlan with sorted observation priority queue.
        Sets distress_beacon_interval to RAMP_UP_TRAIL_INTERVAL_SECONDS.
        """
        prioritized = self.prioritize_observations(observation_ids)
        plan = RampUpPlan(
            fibre_id=fibre_id,
            observation_priority_queue=prioritized,
            distress_beacon_interval=RAMP_UP_TRAIL_INTERVAL_SECONDS,
        )
        self._log.info(
            "ramp_up_initiated",
            fibre_id=fibre_id,
            queue_size=len(prioritized),
        )
        return plan

    def prioritize_observations(
        self,
        observation_ids: list[str],
        therapeutic_values: Optional[dict[str, float]] = None,
    ) -> list[str]:
        """
        Sort by therapeutic_value_score descending if provided.
        Else keep original order.
        """
        if therapeutic_values is None or not therapeutic_values:
            return list(observation_ids)

        def score(obs_id: str) -> float:
            return therapeutic_values.get(obs_id, 0.0)

        return sorted(observation_ids, key=score, reverse=True)

    def should_ramp_up(self, fibre_id: str) -> bool:
        """
        True if trail_map health <= CRITICAL_HEALTH_THRESHOLD
        and mode is CRITICAL.
        """
        from app.models.quakete import QuaketeMode

        health = self._trail_map.get_fibre_health(fibre_id)
        trail = self._trail_map.get_fibre_trail(fibre_id)

        if health is None or trail is None:
            return False

        return (
            health <= CRITICAL_HEALTH_THRESHOLD
            and trail.quakete_mode == QuaketeMode.CRITICAL
        )

    # -------------------------------------------------------------------------
    # EXECUTE RAMP-UP
    # -------------------------------------------------------------------------

    async def execute_ramp_up(
        self,
        plan: RampUpPlan,
        emit_callback: Optional[Callable] = None,
    ) -> dict:
        """
        Stop accepting new observations, process queue in priority order.
        Emit distress beacons at RAMP_UP_TRAIL_INTERVAL_SECONDS.
        Returns {observations_transmitted, distress_beacons_sent}.
        """
        import asyncio

        stop_new_observations = True  # Flag set
        observations_transmitted = 0
        distress_beacons_sent = 0

        queue = list(plan.observation_priority_queue)
        interval = plan.distress_beacon_interval

        beacon_interval_count = max(1, interval)  # Beacon every N observations
        for i, obs_id in enumerate(queue):
            observations_transmitted += 1
            if emit_callback is not None:
                try:
                    if asyncio.iscoroutinefunction(emit_callback):
                        await emit_callback(obs_id, i, len(queue))
                    else:
                        emit_callback(obs_id, i, len(queue))
                except Exception as e:
                    self._log.warning(
                        "ramp_up_emit_failed",
                        obs_id=obs_id,
                        error=str(e),
                    )

            # Emit distress beacon at RAMP_UP_TRAIL_INTERVAL_SECONDS (every N observations)
            if (i + 1) % beacon_interval_count == 0 or i == len(queue) - 1:
                distress_beacons_sent += 1
                if emit_callback is not None:
                    try:
                        beacon_payload = {
                            "type": "distress_beacon",
                            "fibre_id": plan.fibre_id,
                            "observation_index": i,
                            "total": len(queue),
                        }
                        if asyncio.iscoroutinefunction(emit_callback):
                            await emit_callback(beacon_payload, i, len(queue))
                        else:
                            emit_callback(beacon_payload, i, len(queue))
                    except Exception as e:
                        self._log.warning(
                            "ramp_up_beacon_failed",
                            error=str(e),
                        )

        self._log.info(
            "ramp_up_complete",
            fibre_id=plan.fibre_id,
            observations_transmitted=observations_transmitted,
            distress_beacons_sent=distress_beacons_sent,
        )
        return {
            "observations_transmitted": observations_transmitted,
            "distress_beacons_sent": distress_beacons_sent,
            "stop_new_observations": stop_new_observations,
        }

    # -------------------------------------------------------------------------
    # ACTIVATE (Bridge for Silent Fibre Detector — S1)
    # -------------------------------------------------------------------------

    async def activate(self, activation) -> dict:
        """
        High-level activation entry point used by SilentFibreDetector.
        Accepts a RampUpActivation model and orchestrates ramp-up for
        each partner fibre that needs emergency transmission.
        """
        results = []
        partner_fibres = getattr(activation, "partner_fibres", []) or []
        trigger = getattr(activation, "trigger", "unknown")

        for fibre_id in partner_fibres:
            if self.should_ramp_up(fibre_id):
                plan = self.initiate_ramp_up(fibre_id, observation_ids=[])
                result = await self.execute_ramp_up(plan)
                results.append(result)

        self._log.info(
            "ramp_up_activated",
            trigger=trigger,
            target=getattr(activation, "target_member_id", None),
            partners_checked=len(partner_fibres),
            ramp_ups_executed=len(results),
        )
        return {
            "trigger": trigger,
            "ramp_ups_executed": len(results),
            "results": results,
        }
