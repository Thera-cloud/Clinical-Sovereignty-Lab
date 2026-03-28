"""
SOVEREIGN SWARM — Standing Wave Resonance Coupling (Patent Claim 26.1)
"""

from __future__ import annotations

import math

from app.models.quakete import QuaketeIon


# =============================================================================
# WAVE-PARTICLE RESONANCE
# =============================================================================


class WaveParticleResonance:
    """
    Couples donors and recipients through standing wave resonance patterns
    in the Wisdom Mesh. Energy flows without collision — the donor's surplus
    capacity is converted to ions that propagate through the mesh's resonant
    channels.
    """

    def __init__(self, sigma: float = 0.5) -> None:
        self.sigma = sigma

    # -------------------------------------------------------------------------
    # COUPLING & ION GENERATION
    # -------------------------------------------------------------------------

    def compute_coupling(self, donor_freq: float, recipient_freq: float) -> float:
        """
        eta = exp(-|donor_freq - recipient_freq|^2 / (2 * sigma^2))
        """
        diff = donor_freq - recipient_freq
        eta = math.exp(-(diff * diff) / (2.0 * self.sigma * self.sigma))
        return eta

    def generate_ions(
        self,
        donor_id: str,
        recipient_id: str,
        energy: float,
        coupling: float,
    ) -> list[QuaketeIon]:
        """
        Create N ions where N = ceil(energy / 0.1), each with energy/N
        energy and given coupling.
        """
        n = max(1, math.ceil(energy / 0.1))
        energy_per_ion = energy / n
        return [
            QuaketeIon(
                donor_fibre_id=donor_id,
                recipient_fibre_id=recipient_id,
                energy=energy_per_ion,
                resonance_coupling=coupling,
            )
            for _ in range(n)
        ]

    def total_effective_energy(self, ions: list[QuaketeIon]) -> float:
        """Sum of ion.effective_energy for all ions."""
        return sum(ion.effective_energy for ion in ions)
