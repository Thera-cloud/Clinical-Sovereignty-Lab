"""
Tests for QuaketeResonanceEngine.
"""

import pytest

from app.services.quakete.resonance import QuaketeResonanceEngine
from app.services.quakete.constants import RING_MIN_COUPLING


def test_quakete_coherence_formula(resonance_engine):
    """Known inputs produce expected C_quakete."""
    # C_quakete = E_swarm * T_mesh * (1 - gamma_comm) * G_load
    result = resonance_engine.compute_quakete_coherence(
        E_swarm=2.0,
        T_mesh=0.5,
        gamma_comm=0.2,
        G_load=1.0,
    )
    expected = 2.0 * 0.5 * (1.0 - 0.2) * 1.0  # 0.8
    assert result == 0.8


def test_resonance_frequency(resonance_engine):
    """Known C_quakete, gamma_comm, d_isolation produce expected omega_q."""
    # omega_q = C_quakete * sqrt(1 - gamma_comm) * (1 / d_isolation)
    result = resonance_engine.compute_resonance_frequency(
        C_quakete=1.0,
        gamma_comm=0.0,
        d_isolation=2.0,
    )
    expected = 1.0 * (1.0 ** 0.5) * (1.0 / 2.0)  # 0.5
    assert result == 0.5

    with pytest.raises(ValueError, match="d_isolation must be > 0"):
        resonance_engine.compute_resonance_frequency(1.0, 0.0, 0.0)


def test_coupling_efficiency_identical_frequencies(resonance_engine):
    """Same frequency → eta ≈ 1.0."""
    eta = resonance_engine.compute_coupling_efficiency(0.5, 0.5)
    assert eta == 1.0


def test_coupling_efficiency_distant_frequencies(resonance_engine):
    """Very different frequencies → eta ≈ 0.0."""
    eta = resonance_engine.compute_coupling_efficiency(0.0, 10.0)
    assert eta < 0.01
    assert eta >= 0.0


def test_can_form_ring(resonance_engine):
    """Three close frequencies → True; one distant → False."""
    # Close frequencies (all within sigma=0.5)
    assert resonance_engine.can_form_ring(0.5, 0.51, 0.49) is True

    # One distant frequency
    assert resonance_engine.can_form_ring(0.5, 0.51, 5.0) is False
