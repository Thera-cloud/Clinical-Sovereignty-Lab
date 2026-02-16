"""
SOVEREIGN SWARM — Nevedal → Quakete Resonance Bridge
Patent Claim 26.2: Resonance coupling for collisionless transfer.

Maps Nevedal coherence metrics to Quakete resonance frequencies
and computes coupling efficiency for ring formation.
"""

from __future__ import annotations

import math

from .constants import RING_MIN_COUPLING, RESONANCE_SIGMA


# =============================================================================
# QUAKETE RESONANCE ENGINE (Patent Claim 26.2)
# =============================================================================


class QuaketeResonanceEngine:
    """
    Bridges Nevedal emotional coherence to Quakete resonance.
    Computes coupling efficiency for Cosmic Relational Ring formation.
    """

    def __init__(self, sigma: float = RESONANCE_SIGMA) -> None:
        self.sigma = sigma

    # -------------------------------------------------------------------------
    # QUAKETE COHERENCE & FREQUENCY
    # -------------------------------------------------------------------------

    def compute_quakete_coherence(
        self,
        E_swarm: float,
        T_mesh: float,
        gamma_comm: float,
        G_load: float,
    ) -> float:
        """C_quakete = E_swarm * T_mesh * (1 - gamma_comm) * G_load"""
        return E_swarm * T_mesh * (1.0 - gamma_comm) * G_load

    def compute_resonance_frequency(
        self,
        C_quakete: float,
        gamma_comm: float,
        d_isolation: float,
    ) -> float:
        """
        omega_q = C_quakete * sqrt(1 - gamma_comm) * (1 / d_isolation)
        d_isolation must be > 0.
        """
        if d_isolation <= 0:
            raise ValueError("d_isolation must be > 0")
        return C_quakete * math.sqrt(1.0 - gamma_comm) * (1.0 / d_isolation)

    # -------------------------------------------------------------------------
    # COUPLING EFFICIENCY (Gaussian)
    # -------------------------------------------------------------------------

    def compute_coupling_efficiency(
        self,
        omega_donor: float,
        omega_recipient: float,
    ) -> float:
        """eta = exp(-|omega_donor - omega_recipient|^2 / (2 * sigma^2))"""
        diff = omega_donor - omega_recipient
        eta = math.exp(-(diff * diff) / (2.0 * self.sigma * self.sigma))
        return max(0.0, min(1.0, eta))

    # -------------------------------------------------------------------------
    # NEVEDAL → QUAKETE BRIDGE
    # -------------------------------------------------------------------------

    def nevedal_to_quakete(
        self,
        C_emo: float,
        p_ent: float,
        T_tunnel: float,
        gamma_env: float,
    ) -> float:
        """
        Convert Nevedal coherence metrics to Quakete-compatible resonance.
        C_q_approx = C_emo * p_ent * T_tunnel / max(gamma_env, 0.001)
        Returns value normalized to [0, 1].
        """
        gamma_safe = max(gamma_env, 0.001)
        C_q_approx = C_emo * p_ent * T_tunnel / gamma_safe
        return max(0.0, min(1.0, C_q_approx))

    # -------------------------------------------------------------------------
    # RING FORMATION
    # -------------------------------------------------------------------------

    def can_form_ring(
        self,
        omega_a: float,
        omega_b: float,
        omega_c: float,
    ) -> bool:
        """
        All three pairwise couplings must be > RING_MIN_COUPLING.
        """
        eta_ab = self.compute_coupling_efficiency(omega_a, omega_b)
        eta_ac = self.compute_coupling_efficiency(omega_a, omega_c)
        eta_bc = self.compute_coupling_efficiency(omega_b, omega_c)
        return (
            eta_ab > RING_MIN_COUPLING
            and eta_ac > RING_MIN_COUPLING
            and eta_bc > RING_MIN_COUPLING
        )
