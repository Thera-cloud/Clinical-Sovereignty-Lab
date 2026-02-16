"""
SOVEREIGN SWARM — Quakete Transfer Lifecycle (Patent Claim 26.1)
Full six-phase Quakete transfer: deficit detection → donor identification →
reconnection plan → wave-particle transfer → Lorentz acceleration → particle beam.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import structlog

from app.models.quakete import (
    FragmentAcceleration,
    ParticleBeam,
    QuaketeMode,
    QuaketeTransferResult,
)

if TYPE_CHECKING:
    from .cosmic_ring import CosmicRingManager
    from .ion import QuaketeIonPool
    from .lorentz import LorentzForceAccelerator
    from .particle_beam import ParticleBeamGenerator
    from .reconnection import MagneticReconnectionEngine
    from .resonance import QuaketeResonanceEngine
    from .trail_map import FibreTrailMap
    from .wave_particle import WaveParticleResonance


# =============================================================================
# QUAKETE TRANSFER SERVICE (Patent Claim 26.1)
# =============================================================================


class QuaketeTransferService:
    """
    Orchestrates the full Quakete transfer lifecycle across six phases.
    Detects deficit, identifies donors, computes reconnection plan,
    generates ions, applies Lorentz acceleration, and creates particle beam.
    """

    def __init__(
        self,
        ring_manager: "CosmicRingManager",
        trail_map: "FibreTrailMap",
        resonance_engine: "QuaketeResonanceEngine",
        reconnection_engine: "MagneticReconnectionEngine",
        wave_particle: "WaveParticleResonance",
        lorentz: "LorentzForceAccelerator",
        ion_pool: "QuaketeIonPool",
        particle_beam_generator: Optional["ParticleBeamGenerator"] = None,
    ) -> None:
        self._ring_manager = ring_manager
        self._trail_map = trail_map
        self._resonance_engine = resonance_engine
        self._reconnection_engine = reconnection_engine
        self._wave_particle = wave_particle
        self._lorentz = lorentz
        self._ion_pool = ion_pool
        self._particle_beam_generator = particle_beam_generator
        self._log = structlog.get_logger()

    # -------------------------------------------------------------------------
    # PHASE 1–6: FULL TRANSFER LIFECYCLE
    # -------------------------------------------------------------------------

    async def execute_transfer(self, recipient_id: str) -> QuaketeTransferResult:
        """
        Execute full six-phase Quakete transfer for a recipient fibre.
        Phase 1: Detect deficit from trail_map
        Phase 2: Identify donors from ring partners
        Phase 3: Reconnection plan via reconnection_engine
        Phase 4: Wave-particle transfer (ions → ion_pool)
        Phase 5: Lorentz acceleration from total energy
        Phase 6: Particle beam creation
        """
        # Phase 1: Detect deficit
        trail = self._trail_map.get_fibre_trail(recipient_id)
        if trail is None:
            self._log.warning("transfer_recipient_unknown", recipient_id=recipient_id)
            return QuaketeTransferResult(
                success=False,
                reason="recipient fibre not in trail map",
            )

        deficit = trail.deficit_capacity
        health = trail.communication_health
        recipient_freq = trail.resonance_frequency or 0.5

        if deficit <= 0 and health > 0.15:
            return QuaketeTransferResult(
                success=False,
                reason="no deficit to cover",
            )

        # Phase 2: Identify donors
        ring = self._ring_manager.get_fibre_ring(recipient_id)
        if ring is None:
            self._log.warning("transfer_no_ring", recipient_id=recipient_id)
            return QuaketeTransferResult(
                success=False,
                reason="recipient not in a cosmic ring",
            )

        other_cords = ring.get_other_cords(recipient_id)
        donors: list[dict] = []
        for cord in other_cords:
            donor_trail = self._trail_map.get_fibre_trail(cord.fibre_id)
            surplus = donor_trail.surplus_capacity if donor_trail else 0.0
            donor_freq = donor_trail.resonance_frequency if donor_trail else 0.5
            if surplus > 0:
                donors.append({
                    "fibre_id": cord.fibre_id,
                    "surplus": surplus,
                    "resonance_frequency": donor_freq,
                })

        if not donors:
            self._log.warning("transfer_no_donors", recipient_id=recipient_id)
            return QuaketeTransferResult(
                success=False,
                reason="no ring partners with surplus",
            )

        # Phase 3: Reconnection plan
        plan = self._reconnection_engine.compute_reconnection_plan(
            recipient_id=recipient_id,
            recipient_deficit=max(deficit, 0.1),
            donors=donors,
            recipient_resonance_frequency=recipient_freq,
        )

        if not plan.allocations:
            return QuaketeTransferResult(
                success=False,
                reason="reconnection plan produced no allocations",
            )

        # Phase 4: Wave-particle transfer
        all_ions: list = []
        for alloc in plan.allocations:
            ions = self._wave_particle.generate_ions(
                donor_id=alloc.donor_id,
                recipient_id=recipient_id,
                energy=alloc.capacity_transfer,
                coupling=alloc.resonance,
            )
            for ion in ions:
                self._ion_pool.deposit(ion)
                all_ions.append(ion)

        total_energy = self._wave_particle.total_effective_energy(all_ions)

        # Phase 5: Lorentz acceleration
        acceleration = self._lorentz.compute_acceleration(total_energy)

        # Phase 6: Particle beam
        beam: Optional[ParticleBeam] = None
        endpoints: list[str] = []
        if trail.last_known_endpoint:
            endpoints.append(trail.last_known_endpoint)

        if self._particle_beam_generator is not None:
            beam = self._particle_beam_generator.create_beam(
                target_fibre_id=recipient_id,
                energy=total_energy,
                endpoints=endpoints if endpoints else None,
            )

        # Recovery estimate
        recovery_seconds = self._reconnection_engine.estimate_recovery_time(
            plan, deficit
        )
        ring_coherence = ring.ring_coherence if ring else None

        result = QuaketeTransferResult(
            success=True,
            ions_transferred=len(all_ions),
            total_energy=total_energy,
            acceleration=acceleration,
            ring_coherence_after=ring_coherence,
            recipient_predicted_recovery_seconds=recovery_seconds,
        )

        self._log.info(
            "transfer_complete",
            recipient_id=recipient_id,
            ions=len(all_ions),
            total_energy=total_energy,
            beam_created=beam is not None,
        )
        return result

    # -------------------------------------------------------------------------
    # CONDITIONAL & BULK TRANSFERS
    # -------------------------------------------------------------------------

    async def check_and_transfer(
        self, fibre_id: str
    ) -> Optional[QuaketeTransferResult]:
        """
        If fibre is REQUESTING or CRITICAL, execute transfer.
        Returns result or None if no transfer performed.
        """
        trail = self._trail_map.get_fibre_trail(fibre_id)
        if trail is None:
            return None

        if trail.quakete_mode not in (QuaketeMode.REQUESTING, QuaketeMode.CRITICAL):
            return None

        return await self.execute_transfer(fibre_id)

    async def process_all_needy(self) -> list[QuaketeTransferResult]:
        """
        Scan trail_map for all fibres in REQUESTING or CRITICAL mode,
        execute transfer for each.
        """
        results: list[QuaketeTransferResult] = []
        for fibre_id in list(self._trail_map._trails):
            trail = self._trail_map.get_fibre_trail(fibre_id)
            if trail is None:
                continue
            if trail.quakete_mode in (QuaketeMode.REQUESTING, QuaketeMode.CRITICAL):
                result = await self.execute_transfer(fibre_id)
                results.append(result)

        return results
