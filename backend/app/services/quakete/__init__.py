"""
SOVEREIGN SWARM — Quakete Collisionless Fibre Protocol
Layer 8: Swarm Solidarity — Three Cords Are Not Easily Broken.
Patent Claim 26: Quakete Collisionless Solidarity Protocol.

When a Fibre's communication falters, its Ring partners donate energy
through collisionless wave-particle transfer. Cosmic Relational Rings
of three Fibres form the topology. If one weakens, two lift.

Resonance bridge: Nevedal coherence → Quakete frequency → coupling efficiency
"""

from .constants import (
    COMMUNICATION_HEALTH_THRESHOLD,
    CRITICAL_HEALTH_THRESHOLD,
    RESONANCE_SIGMA,
    RING_MIN_COUPLING,
    SILENT_TIMEOUT_SECONDS,
    SURPLUS_THRESHOLD,
    TRAIL_EMISSION_INTERVAL_SECONDS,
    TRAIL_FLAG_MASK,
)
from .ion import QuaketeIonPool
from .lorentz import LorentzForceAccelerator
from .memorial import MemorialService
from .metrics import QuaketeMetrics
from .particle_beam import ParticleBeamGenerator
from .ramp_up import QuaketeRampUp
from .reconnection import MagneticReconnectionEngine
from .resonance import QuaketeResonanceEngine
from .trail_emission import TrailEmitter, encode_trail_flag
from .trail_map import FibreTrailMap
from .transfer_service import QuaketeTransferService
from .wave_particle import WaveParticleResonance

__all__ = [
    "LorentzForceAccelerator",
    "MagneticReconnectionEngine",
    "MemorialService",
    "ParticleBeamGenerator",
    "QuaketeIonPool",
    "QuaketeMetrics",
    "QuaketeRampUp",
    "QuaketeResonanceEngine",
    "QuaketeTransferService",
    "TrailEmitter",
    "FibreTrailMap",
    "WaveParticleResonance",
    "encode_trail_flag",
    "TRAIL_EMISSION_INTERVAL_SECONDS",
    "TRAIL_FLAG_MASK",
    "COMMUNICATION_HEALTH_THRESHOLD",
    "SURPLUS_THRESHOLD",
    "SILENT_TIMEOUT_SECONDS",
    "CRITICAL_HEALTH_THRESHOLD",
    "RING_MIN_COUPLING",
    "RESONANCE_SIGMA",
]
