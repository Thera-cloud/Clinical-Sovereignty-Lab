"""
SOVEREIGN SWARM — Particle Beam Generator (Patent Claim 26.6f)
Concentrated burst for fragment acceleration with exponential decay.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import structlog

from app.models.quakete import ParticleBeam, QuaketeBoost

from .constants import PARTICLE_BEAM_HALF_LIFE_SECONDS

if TYPE_CHECKING:
    from .lorentz import LorentzForceAccelerator


# =============================================================================
# PARTICLE BEAM GENERATOR (Patent Claim 26.6f)
# =============================================================================


class ParticleBeamGenerator:
    """
    Creates and tracks particle beams for fragment acceleration.
    Beams decay exponentially; expired beams are purged after 5 half-lives.
    """

    def __init__(self, lorentz: "LorentzForceAccelerator") -> None:
        self._lorentz = lorentz
        self._active_beams: dict[str, ParticleBeam] = {}
        self._log = structlog.get_logger()

    # -------------------------------------------------------------------------
    # BEAM LIFECYCLE
    # -------------------------------------------------------------------------

    def create_beam(
        self,
        target_fibre_id: str,
        energy: float,
        endpoints: Optional[list[str]] = None,
    ) -> ParticleBeam:
        """
        Create a new particle beam targeting a fibre.
        Stores in _active_beams and returns the beam.
        """
        beam = ParticleBeam(
            target_fibre_id=target_fibre_id,
            initial_energy=energy,
            current_energy=energy,
            decay_half_life=PARTICLE_BEAM_HALF_LIFE_SECONDS,
            affected_endpoints=endpoints or [],
        )
        self._active_beams[target_fibre_id] = beam
        self._log.debug(
            "particle_beam_created",
            target_fibre_id=target_fibre_id,
            energy=energy,
        )
        return beam

    def get_beam(self, target_fibre_id: str) -> Optional[ParticleBeam]:
        """Return the active beam for target fibre, or None."""
        return self._active_beams.get(target_fibre_id)

    def update_beam_energy(self, target_fibre_id: str) -> Optional[float]:
        """
        Recompute current_energy using beam.energy_at(now).
        If expired (after 5 half-lives), remove beam.
        Returns remaining energy or None if expired.
        """
        beam = self._active_beams.get(target_fibre_id)
        if beam is None:
            return None

        now = datetime.utcnow()
        if now >= beam.expires_at:
            del self._active_beams[target_fibre_id]
            return None

        remaining = beam.energy_at(now)
        beam.current_energy = remaining
        return remaining

    def get_boost(self, target_fibre_id: str) -> Optional[QuaketeBoost]:
        """
        If beam exists: compute acceleration from current energy,
        return QuaketeBoost. Else return None.
        """
        beam = self._active_beams.get(target_fibre_id)
        if beam is None:
            return None

        energy = self.update_beam_energy(target_fibre_id)
        if energy is None:
            return None

        acc = self._lorentz.compute_acceleration(energy)
        return QuaketeBoost(
            fibre_id=target_fibre_id,
            detection_sensitivity=acc.detection_sensitivity_boost,
            embedding_priority=acc.embedding_priority_boost,
            assembly_priority=acc.reassembly_priority_boost,
            forwarding_priority=acc.cloud_forwarding_priority,
            half_life_seconds=PARTICLE_BEAM_HALF_LIFE_SECONDS,
        )

    def purge_expired(self) -> int:
        """Remove all beams past their expires_at. Return count purged."""
        now = datetime.utcnow()
        expired: list[str] = []
        for fibre_id, beam in self._active_beams.items():
            if now >= beam.expires_at:
                expired.append(fibre_id)

        for fibre_id in expired:
            del self._active_beams[fibre_id]

        if expired:
            self._log.debug("particle_beams_purged", count=len(expired), fibre_ids=expired)
        return len(expired)

    @property
    def active_beam_count(self) -> int:
        """Number of active beams."""
        return len(self._active_beams)
