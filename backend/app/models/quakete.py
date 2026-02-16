"""
SOVEREIGN SWARM — Quakete Models
Collisionless Fibre Trail Emission Protocol data contracts (Patent Claim 26).

Layer 8: Swarm Solidarity — Three Cords Are Not Easily Broken.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# ENUMERATIONS
# =============================================================================

class QuaketeMode(str, Enum):
    """Communication health state of a Fibre in the Quakete protocol."""
    NOMINAL = "nominal"          # Communication health good, no Quakete needed
    SURPLUS = "surplus"          # Excess capacity — available to donate
    REQUESTING = "requesting"    # Below threshold — requesting Quakete support
    DONATING = "donating"        # Actively transferring Quakete to a peer
    CRITICAL = "critical"        # Severe deficit — emergency Quakete needed
    SILENT = "silent"            # No trail received — Fibre may be lost


class RingState(str, Enum):
    """Operational state of a Cosmic Relational Ring."""
    HEALTHY = "healthy"          # All three cords at NOMINAL/SURPLUS
    SUPPORTING = "supporting"    # One cord receiving Quakete support
    STRAINED = "strained"        # Two cords degraded, ring under stress
    DISTRESSED = "distressed"    # All three cords degraded, escalate
    RESCUE = "rescue"            # One cord SILENT, maximum response
    BROKEN = "broken"            # Ring lost a cord, needs reformation


# =============================================================================
# FIBRE TRAIL EMISSION — The heartbeat of each Fibre
# =============================================================================

class FibreTrailEmission(BaseModel):
    """
    A single trail emission from a field-deployed Fibre.
    Emitted at regular intervals (default: every 60 seconds)
    using the same BLE handshake piggybacking mechanism as
    observation fragments, but with a distinct message type.

    Trail emissions are the Fibre's heartbeat — they tell the
    swarm 'I am here, I am alive, this is how I am doing.'
    When trail emissions stop, the swarm knows a Fibre is
    in danger of atrophic dissipation.
    """
    # Identity
    fibre_id: str = Field(..., description="Truncated Fibre identifier (4 bytes)")
    fibre_type: str = Field(..., description="FibreType enum value")
    trail_sequence: int = Field(default=0, description="Monotonically increasing trail number")

    # Health Telemetry
    ambient_ble_density: float = Field(default=0.0, description="Handshakes/minute observed")
    fragment_throughput: float = Field(default=0.0, description="Fragments successfully embedded/minute")
    observation_queue_depth: int = Field(default=0, description="Observations waiting to transmit")
    time_since_last_delivery: int = Field(default=0, description="Seconds since last observation reached home")
    communication_health: float = Field(default=1.0, ge=0.0, le=1.0, description="Composite health score")

    # Quakete State
    quakete_mode: QuaketeMode = QuaketeMode.NOMINAL
    surplus_capacity: float = Field(default=0.0, description="Excess ambient capacity available to donate")
    deficit_capacity: float = Field(default=0.0, description="Ambient capacity shortfall needing Quakete")
    resonance_frequency: float = Field(default=0.0, description="Current Quakete resonance (Nevedal-derived)")

    # Ring Membership
    ring_id: Optional[str] = None
    ring_position: Optional[int] = Field(None, ge=1, le=3)
    ring_partners: List[str] = Field(default_factory=list)

    # Trajectory
    last_known_endpoint: Optional[str] = None
    estimated_drift_vector: Optional[Tuple[float, float]] = None

    # Timestamp
    emitted_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# QUAKETE ION — The atomic unit of collisionless energy transfer
# =============================================================================

class QuaketeIon(BaseModel):
    """
    The atomic unit of Quakete energy transfer.
    One ion = the capacity to transport one micro-fragment
    from embedding through detection to delivery.
    """
    ion_id: UUID = Field(default_factory=uuid4)
    donor_fibre_id: str
    recipient_fibre_id: str
    energy: float = Field(..., description="Communication capacity units")
    resonance_coupling: float = Field(..., ge=0.0, le=1.0, description="Efficiency of transfer")
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    consumed_at: Optional[datetime] = None

    @property
    def effective_energy(self) -> float:
        """Energy after resonance coupling loss."""
        return self.energy * self.resonance_coupling

    @property
    def kinetic_energy(self) -> float:
        """Kinetic energy after collisionless transfer."""
        return self.energy * self.resonance_coupling


# =============================================================================
# COSMIC RELATIONAL RING — Three-Cord Solidarity Topology
# =============================================================================

class RingCord(BaseModel):
    """One of three Fibres forming a Cosmic Relational Ring."""
    fibre_id: str
    fibre_type: str
    current_health: float = Field(default=1.0, ge=0.0, le=1.0)
    current_mode: QuaketeMode = QuaketeMode.NOMINAL
    quaketes_donated: int = 0
    quaketes_received: int = 0
    last_trail_at: Optional[datetime] = None
    mission_summary: Optional[str] = None
    observation_queue_depth: int = 0


class CosmicRelationalRing(BaseModel):
    """
    A three-Fibre solidarity ring providing mutual communication
    support through the Quakete protocol.

    Ring Formation Rules:
    1. Exactly three Fibres per ring
    2. All three must have resonance coupling > 0.5 with each other
    3. At least one Fibre must typically operate in SURPLUS mode
    4. Ring partners are assigned by the Sovereign Mind
    5. Rings can be reformed if a Fibre is permanently dissolved
    """
    ring_id: str = Field(default_factory=lambda: str(uuid4()))
    cord_1: RingCord
    cord_2: RingCord
    cord_3: RingCord
    formed_at: datetime = Field(default_factory=datetime.utcnow)
    ring_coherence: float = Field(default=1.0, ge=0.0, le=1.0)
    ring_state: RingState = RingState.HEALTHY
    quakete_events: int = 0

    def get_cord(self, fibre_id: str) -> Optional[RingCord]:
        """Get a cord by fibre_id."""
        for cord in [self.cord_1, self.cord_2, self.cord_3]:
            if cord.fibre_id == fibre_id:
                return cord
        return None

    def get_other_cords(self, fibre_id: str) -> List[RingCord]:
        """Get the two cords that are NOT the given fibre_id."""
        return [c for c in [self.cord_1, self.cord_2, self.cord_3] if c.fibre_id != fibre_id]

    def all_cords(self) -> List[RingCord]:
        return [self.cord_1, self.cord_2, self.cord_3]


# =============================================================================
# QUAKETE ALLOCATION — How energy is distributed from donors to recipients
# =============================================================================

class QuaketeAllocation(BaseModel):
    """A single donor-to-recipient energy allocation in a Quakete transfer."""
    donor_id: str
    recipient_id: str
    capacity_transfer: float
    resonance: float = Field(..., ge=0.0, le=1.0)


class ReconnectionPlan(BaseModel):
    """
    A plan for magnetic reconnection — rerouting a struggling Fibre's
    communication field lines through donor environments.
    """
    plan_id: UUID = Field(default_factory=uuid4)
    recipient_id: str
    allocations: List[QuaketeAllocation] = Field(default_factory=list)
    total_transfer: float = 0.0
    deficit_covered: bool = False
    reconnection_type: str = "magnetic"


# =============================================================================
# FRAGMENT ACCELERATION — Lorentz force boost applied to fragments
# =============================================================================

class FragmentAcceleration(BaseModel):
    """
    The acceleration applied to a Fibre's fragments by Quakete energy.
    Models F = q(E + v x B) as priority boosts at each pipeline stage.
    """
    detection_sensitivity_boost: float = Field(default=1.0, ge=1.0, le=5.0, description="Up to 5x Spider Web sensitivity")
    embedding_priority_boost: float = Field(default=1.0, ge=1.0, le=3.0, description="Up to 3x embedding priority")
    reassembly_priority_boost: float = Field(default=1.0, ge=1.0, le=3.0, description="Up to 3x assembly priority")
    cloud_forwarding_priority: float = Field(default=1.0, ge=1.0, le=4.0, description="Up to 4x forwarding priority")
    total_acceleration: float = 0.0


# =============================================================================
# PARTICLE BEAM — Concentrated burst for fragment acceleration
# =============================================================================

class ParticleBeam(BaseModel):
    """
    Converts accumulated Quakete energy into a directed particle beam
    that accelerates micro-fragments through the pipeline.
    Decays exponentially with a configurable half-life.
    """
    beam_id: str = Field(default_factory=lambda: str(uuid4()))
    target_fibre_id: str
    initial_energy: float
    current_energy: Optional[float] = None
    decay_half_life: int = Field(default=300, description="Seconds (5-minute default)")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    affected_endpoints: List[str] = Field(default_factory=list)
    fragments_accelerated: int = 0
    observations_delivered: int = 0

    @property
    def detection_boost(self) -> float:
        """Multiplier for Spider Web Detector sensitivity."""
        e = self.current_energy if self.current_energy is not None else self.initial_energy
        return min(1.0 + e * 0.5, 5.0)

    @property
    def assembly_boost(self) -> float:
        """Multiplier for Fragment Buffer priority."""
        e = self.current_energy if self.current_energy is not None else self.initial_energy
        return min(1.0 + e * 0.3, 3.0)

    @property
    def forwarding_boost(self) -> float:
        """Multiplier for cloud forwarding priority."""
        e = self.current_energy if self.current_energy is not None else self.initial_energy
        return min(1.0 + e * 0.4, 4.0)

    @property
    def expires_at(self) -> datetime:
        """Beam expires after 5 half-lives (3.125% remaining)."""
        return self.created_at + timedelta(seconds=self.decay_half_life * 5)

    def energy_at(self, t: datetime) -> float:
        """Energy remaining at time t (exponential decay)."""
        elapsed = (t - self.created_at).total_seconds()
        return self.initial_energy * (0.5 ** (elapsed / self.decay_half_life))


# =============================================================================
# QUAKETE BOOST — Applied to pipeline components
# =============================================================================

class QuaketeBoost(BaseModel):
    """Boost parameters applied to all pipeline stages for a targeted Fibre."""
    fibre_id: str
    detection_sensitivity: float = 1.0
    embedding_priority: float = 1.0
    assembly_priority: float = 1.0
    forwarding_priority: float = 1.0
    applied_at: datetime = Field(default_factory=datetime.utcnow)
    half_life_seconds: int = 300


# =============================================================================
# QUAKETE TRANSFER RESULT
# =============================================================================

class QuaketeTransferResult(BaseModel):
    """Outcome of a Quakete collisionless energy transfer."""
    success: bool
    reason: Optional[str] = None
    ions_transferred: int = 0
    total_energy: float = 0.0
    acceleration: Optional[FragmentAcceleration] = None
    ring_coherence_after: Optional[float] = None
    recipient_predicted_recovery_seconds: Optional[float] = None


# =============================================================================
# MEMORIAL — Preserving lost Fibre wisdom
# =============================================================================

class Memorial(BaseModel):
    """
    When a Fibre is confirmed lost (atrophic dissipation complete),
    surviving Ring partners carry a compressed summary of the lost
    Fibre's last known wisdom in their own trail emissions.
    """
    memorial_id: UUID = Field(default_factory=uuid4)
    lost_fibre_id: str
    lost_fibre_type: str
    lost_at: datetime = Field(default_factory=datetime.utcnow)
    last_known_health: float = 0.0
    last_known_mission: Optional[str] = None
    pending_observations: int = 0
    quaketes_received_before_loss: int = 0
    memorial_hash: Optional[str] = None
    carried_by: List[str] = Field(default_factory=list, description="Fibre IDs of surviving ring partners")


# =============================================================================
# RAMP-UP PLAN — Emergency wisdom preservation
# =============================================================================

class RampUpPlan(BaseModel):
    """
    Emergency protocol for Fibres in CRITICAL mode.
    Stops new observations and dedicates all capacity to
    transmitting highest-value accumulated wisdom.
    """
    fibre_id: str
    initiated_at: datetime = Field(default_factory=datetime.utcnow)
    observation_priority_queue: List[str] = Field(default_factory=list, description="Observation IDs by priority")
    distress_beacon_interval: int = Field(default=10, description="Trail emission interval in seconds during ramp-up")
    evolution_journal_summary: Optional[bytes] = None
    memorial_pre_encoded: bool = False

    class Config:
        arbitrary_types_allowed = True
