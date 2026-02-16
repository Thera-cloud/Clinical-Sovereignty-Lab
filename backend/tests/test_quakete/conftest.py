"""
Pytest fixtures for Quakete protocol tests.
"""

import pytest

from app.services.quakete.resonance import QuaketeResonanceEngine
from app.services.quakete.cosmic_ring import CosmicRingManager
from app.services.quakete.trail_map import FibreTrailMap
from app.services.quakete.wave_particle import WaveParticleResonance
from app.services.quakete.lorentz import LorentzForceAccelerator
from app.services.quakete.ion import QuaketeIonPool


@pytest.fixture
def resonance_engine():
    """QuaketeResonanceEngine instance for coupling and coherence calculations."""
    return QuaketeResonanceEngine()


@pytest.fixture
def ring_manager(resonance_engine):
    """CosmicRingManager instance with resonance engine."""
    return CosmicRingManager(resonance_engine)


@pytest.fixture
def trail_map():
    """FibreTrailMap for swarm-wide trail aggregation."""
    return FibreTrailMap()


@pytest.fixture
def wave_particle():
    """WaveParticleResonance for ion generation and coupling."""
    return WaveParticleResonance()


@pytest.fixture
def lorentz():
    """LorentzForceAccelerator for fragment acceleration."""
    return LorentzForceAccelerator()


@pytest.fixture
def ion_pool():
    """QuaketeIonPool for storing QuaketeIon units."""
    return QuaketeIonPool()
