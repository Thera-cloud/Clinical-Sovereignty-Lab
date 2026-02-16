"""
SOVEREIGN SWARM — Quakete Protocol Constants
Patent Claim 26: Collisionless Fibre Trail Emission Protocol.
"""

# =============================================================================
# TRAIL EMISSION
# =============================================================================

TRAIL_EMISSION_INTERVAL_SECONDS = 60
TRAIL_FLAG_MASK = 0b10000000

# =============================================================================
# HEALTH THRESHOLDS (QuaketeMode classification)
# =============================================================================

COMMUNICATION_HEALTH_THRESHOLD = 0.3  # below this = REQUESTING
SURPLUS_THRESHOLD = 0.7              # above this = SURPLUS
SILENT_TIMEOUT_SECONDS = 300         # 5 minutes no trail = SILENT
CRITICAL_HEALTH_THRESHOLD = 0.15

# =============================================================================
# RING FORMATION & SOLIDARITY
# =============================================================================

RING_MIN_COUPLING = 0.5              # minimum pairwise coupling for ring formation
RING_SURPLUS_DONATION_RATE = 0.10    # 10% surplus donated per cycle
RING_CIRCULATION_INTERVAL_SECONDS = 30

# =============================================================================
# LORENTZ CAPS (Fragment acceleration limits)
# =============================================================================

LORENTZ_CAP_DETECTION = 3.0
LORENTZ_CAP_EMBEDDING = 2.0
LORENTZ_CAP_ASSEMBLY = 2.0
LORENTZ_CAP_FORWARDING = 3.0

# =============================================================================
# PARTICLE BEAM DECAY
# =============================================================================

PARTICLE_BEAM_HALF_LIFE_SECONDS = 300   # 5 minutes
PARTICLE_BEAM_MAX_HALF_LIVES = 5

# =============================================================================
# RAMP-UP (Emergency protocol)
# =============================================================================

RAMP_UP_TRAIL_INTERVAL_SECONDS = 10
RAMP_UP_MAX_QUEUE_SIZE = 50

# =============================================================================
# RESONANCE (Nevedal → Quakete bridge)
# =============================================================================

RESONANCE_SIGMA = 0.5   # coupling Gaussian width
