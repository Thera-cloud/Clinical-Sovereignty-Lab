"""
SOVEREIGN SWARM — 30-Second Ring Energy Circulation Cycles
Patent Claim 26.1h: Ring energy circulation cycles.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable, Optional

import structlog

from app.models.quakete import CosmicRelationalRing, QuaketeIon, QuaketeMode

from .constants import RING_CIRCULATION_INTERVAL_SECONDS, RING_SURPLUS_DONATION_RATE

if TYPE_CHECKING:
    from .cosmic_ring import CosmicRingManager
    from .ion import QuaketeIonPool
    from .trail_map import FibreTrailMap
    from .wave_particle import WaveParticleResonance


# =============================================================================
# RING CIRCULATOR (Patent Claim 26.1h)
# =============================================================================


class RingCirculator:
    """
    Runs 30-second ring energy circulation cycles.
    SURPLUS cords donate to REQUESTING/CRITICAL cords in the same ring.
    """

    def __init__(
        self,
        ring_manager: CosmicRingManager,
        trail_map: FibreTrailMap,
        wave_particle: WaveParticleResonance,
        ion_pool: QuaketeIonPool,
    ) -> None:
        self._ring_manager = ring_manager
        self._trail_map = trail_map
        self._wave_particle = wave_particle
        self._ion_pool = ion_pool
        self._log = structlog.get_logger()
        self._periodic_task: Optional[asyncio.Task] = None

    # -------------------------------------------------------------------------
    # CIRCULATION
    # -------------------------------------------------------------------------

    async def circulate(self, ring: CosmicRelationalRing) -> dict:
        """
        For each cord in SURPLUS mode:
        - Compute surplus donation = health * RING_SURPLUS_DONATION_RATE
        - Identify requesting/critical cords in same ring
        - Generate ions via wave_particle.generate_ions()
        - Deposit ions in ion_pool
        - Increment quaketes_donated / quaketes_received on cords
        - Increment ring.quakete_events
        Return summary: {donations: int, ions_generated: int, total_energy: float}
        """
        if ring.ring_state.value == "broken":
            return {"donations": 0, "ions_generated": 0, "total_energy": 0.0}

        total_donations = 0
        total_ions = 0
        total_energy = 0.0

        surplus_cords = [c for c in ring.all_cords() if c.current_mode == QuaketeMode.SURPLUS]
        needy_cords = [
            c
            for c in ring.all_cords()
            if c.current_mode in (QuaketeMode.REQUESTING, QuaketeMode.CRITICAL)
        ]

        for donor in surplus_cords:
            surplus_donation = donor.current_health * RING_SURPLUS_DONATION_RATE
            if surplus_donation <= 0 or not needy_cords:
                continue

            donor_freq = self._get_resonance_frequency(donor.fibre_id)
            energy_per_recipient = surplus_donation / len(needy_cords)

            for recipient in needy_cords:
                recipient_freq = self._get_resonance_frequency(recipient.fibre_id)
                coupling = self._wave_particle.compute_coupling(donor_freq, recipient_freq)

                ions = self._wave_particle.generate_ions(
                    donor_id=donor.fibre_id,
                    recipient_id=recipient.fibre_id,
                    energy=energy_per_recipient,
                    coupling=coupling,
                )
                self._ion_pool.deposit(ions)

                donor.quaketes_donated += len(ions)
                recipient.quaketes_received += len(ions)
                ring.quakete_events += 1

                total_donations += 1
                total_ions += len(ions)
                total_energy += sum(ion.effective_energy for ion in ions)

        return {
            "donations": total_donations,
            "ions_generated": total_ions,
            "total_energy": total_energy,
        }

    def _get_resonance_frequency(self, fibre_id: str) -> float:
        """Get resonance frequency from trail map, or default 0.5."""
        trails = getattr(self._trail_map, "_trails", {})
        trail = trails.get(fibre_id)
        if trail is not None and hasattr(trail, "resonance_frequency"):
            return float(trail.resonance_frequency)
        return 0.5

    # -------------------------------------------------------------------------
    # BULK CIRCULATION
    # -------------------------------------------------------------------------

    async def circulate_all(self) -> dict:
        """
        Iterate all rings, circulate each that isn't BROKEN.
        Return aggregate summary.
        """
        agg_donations = 0
        agg_ions = 0
        agg_energy = 0.0
        rings_processed = 0

        for ring in self._ring_manager.all_rings:
            if ring.ring_state.value == "broken":
                continue
            result = await self.circulate(ring)
            agg_donations += result["donations"]
            agg_ions += result["ions_generated"]
            agg_energy += result["total_energy"]
            rings_processed += 1

        self._log.info(
            "circulation_complete",
            rings_processed=rings_processed,
            donations=agg_donations,
            ions_generated=agg_ions,
            total_energy=agg_energy,
        )
        return {
            "donations": agg_donations,
            "ions_generated": agg_ions,
            "total_energy": agg_energy,
            "rings_processed": rings_processed,
        }

    # -------------------------------------------------------------------------
    # PERIODIC TASK
    # -------------------------------------------------------------------------

    async def start_periodic_circulation(
        self,
        interval: int = RING_CIRCULATION_INTERVAL_SECONDS,
        callback: Optional[Callable] = None,
    ) -> None:
        """
        Background asyncio task running circulate_all every interval seconds.
        """
        if self._periodic_task is not None and not self._periodic_task.done():
            self._log.warning("periodic_circulation_already_running")
            return

        async def _run() -> None:
            while True:
                try:
                    result = await self.circulate_all()
                    if callback:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(result)
                        else:
                            callback(result)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self._log.exception("circulation_error", error=str(e))
                await asyncio.sleep(interval)

        self._periodic_task = asyncio.create_task(_run())
        self._log.info("periodic_circulation_started", interval=interval)

    async def stop(self) -> None:
        """Cancel the periodic circulation task."""
        if self._periodic_task is not None:
            self._periodic_task.cancel()
            try:
                await self._periodic_task
            except asyncio.CancelledError:
                pass
            self._periodic_task = None
            self._log.info("periodic_circulation_stopped")
