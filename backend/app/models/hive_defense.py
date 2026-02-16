"""
HIVE DEFENSE PROTOCOL — Pydantic Models
All security models for Phase 8: Mirror Dimension, Three Cords, Trinity Helix, Projected Helix.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# ENUMS
# =============================================================================

class GateDecision(str, Enum):
    """Coherence Gate outcome for an incoming signal."""
    PASS_TO_REAL = "pass"
    MIRROR_ABSORB = "absorb"
    MIRROR_CONTAIN = "contain"
    MIRROR_SUSPICIOUS = "suspicious"


class CuriosityLevel(str, Enum):
    """Graduated anomaly response levels."""
    NONE = "none"
    NOTICE = "notice"        # Single anomaly — 24h monitoring
    INTEREST = "interest"    # 2-3 anomalies — 72h ring cross-verify
    CONCERN = "concern"      # Ring confirms divergence — Three-Cord Verification
    ALARM = "alarm"          # Three-Cord fails — mesh isolation + alert Nathan


class DefconLevel(int, Enum):
    """Defense Condition levels. 5=peace, 1=critical."""
    PEACE = 5
    ELEVATED = 4
    SUBSTANTIAL = 3
    SEVERE = 2
    CRITICAL = 1


class ContentVerdict(str, Enum):
    """Content Sentinel payload inspection result."""
    PASS_CLEAN = "pass_clean"
    PASS_WITH_FLAG = "pass_with_flag"
    QUARANTINE_FOR_REVIEW = "quarantine"
    REJECT_AND_INVESTIGATE = "reject_investigate"
    REJECT_AND_ALARM = "reject_alarm"


class PenetratorPhase(str, Enum):
    """Penetrator mission phases."""
    OBSERVE = "observe"
    TRACE = "trace"
    FINGERPRINT = "fingerprint"
    MAP = "map"
    REPORT = "report"
    COMPLETE = "complete"


class GhostType(str, Enum):
    """Ghost Swarm phantom types."""
    PASSIVE_OBSERVER = "passive_observer"
    ACTIVE_PROBE = "active_probe"
    CANARY_INJECTOR = "canary_injector"
    DECOY = "decoy"


class HelixVerdict(str, Enum):
    """Trinity Helix verification outcome."""
    PASS_TO_REAL = "pass"
    INVERT_TO_TRIANGLE = "invert"
    RESTART_ROTATION = "restart"


class ProjectionStatus(str, Enum):
    """Projected Helix deployment state."""
    PENDING_AUTH = "pending_auth"
    AUTHORIZED = "authorized"
    ACTIVE = "active"
    LEARNING = "learning"
    DECOMMISSIONED = "decommissioned"


# =============================================================================
# HEARTBEAT & IDENTITY
# =============================================================================

class HeartbeatPulse(BaseModel):
    """A single heartbeat emission from a hive entity."""
    entity_id: UUID
    birth_coherence_hash: str          # SHA-256 of C_emo state at birth
    originator_signature: str          # Ed25519 from Big Nate's key
    birth_timestamp_ns: int            # Nanosecond-precision
    identity_chain_root: str           # Merkle root of identity chain
    evolution_journal_hash: str        # Current journal state hash
    monotonic_counter: int = 0
    pulse_data: str = ""               # HMAC-SHA256 pulse output


class ThreeCordVerification(BaseModel):
    """Three-Cord identity verification result."""
    entity_id: UUID
    cord_real: bool = False            # Entity exists in real registry
    cord_mirror: bool = False          # Mirror reflection matches
    cord_originator: bool = False      # Originator signature valid
    verified: bool = False             # All three pass
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# MIRROR DIMENSION
# =============================================================================

class MirrorNamespace(BaseModel):
    """An isolated mirror dimension for containing non-verified traffic."""
    namespace_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    signal_count: int = 0
    entities_contained: List[str] = Field(default_factory=list)
    is_active: bool = True
    synthetic_data_seed: str = ""


class MirrorSignal(BaseModel):
    """A signal captured in the mirror dimension."""
    signal_id: UUID = Field(default_factory=uuid4)
    namespace_id: UUID
    source_address: str = ""
    signal_type: str = ""
    payload_hash: str = ""
    gate_decision: GateDecision = GateDecision.MIRROR_ABSORB
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# CURIOSITY PROTOCOL
# =============================================================================

class CuriosityEvent(BaseModel):
    """A single curiosity observation about an entity."""
    event_id: UUID = Field(default_factory=uuid4)
    entity_id: UUID
    level: CuriosityLevel
    divergence_type: str               # heartbeat_discontinuity, journal_divergence, etc.
    details: str = ""
    ring_partners_notified: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class MirrorReflection(BaseModel):
    """Behavioral baseline snapshot for an entity (what it SHOULD look like)."""
    entity_id: UUID
    data_access_hash: str = ""
    communication_graph_hash: str = ""
    trail_emission_fingerprint: str = ""
    coherence_baseline_hash: str = ""
    journal_trajectory_hash: str = ""
    snapshot_timestamp: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# DEFCON & DRIFT
# =============================================================================

class DefconState(BaseModel):
    """Current system-wide defense condition."""
    level: DefconLevel = DefconLevel.PEACE
    triggered_at: datetime = Field(default_factory=datetime.utcnow)
    trigger_reason: str = ""
    heartbeat_interval_sec: float = 60.0
    cds_threshold_multiplier: float = 1.0
    max_cert_births: int = 50
    mirror_mode: str = "passive"       # passive, active, fortress
    last_escalation: Optional[datetime] = None
    last_deescalation: Optional[datetime] = None


class DriftScore(BaseModel):
    """Cumulative Drift Score for a single entity across 6 dimensions."""
    entity_id: UUID
    data_access: float = 0.0
    communication: float = 0.0
    coherence: float = 0.0
    trail_emission: float = 0.0
    journal_trajectory: float = 0.0
    timing_pattern: float = 0.0
    combined_magnitude: float = 0.0    # sqrt(sum of squared vectors)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    def compute_magnitude(self) -> float:
        import math
        self.combined_magnitude = math.sqrt(
            self.data_access ** 2 +
            self.communication ** 2 +
            self.coherence ** 2 +
            self.trail_emission ** 2 +
            self.journal_trajectory ** 2 +
            self.timing_pattern ** 2
        )
        return self.combined_magnitude


# =============================================================================
# CONTENT SENTINEL
# =============================================================================

class ContentSentinelResult(BaseModel):
    """Result of Content Sentinel payload inspection."""
    signal_id: UUID
    verdict: ContentVerdict
    checks: Dict[str, str] = Field(default_factory=dict)  # check_name -> pass/fail/detail
    entropy_score: float = 0.0
    schema_valid: bool = True
    unexpected_fields: List[str] = Field(default_factory=list)
    injection_detected: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# PENETRATOR & GHOST SWARM
# =============================================================================

class PenetratorReport(BaseModel):
    """Complete forensic report from a Penetrator mission."""
    mission_id: UUID = Field(default_factory=uuid4)
    spawned_from: UUID
    target_zone: str
    phase: PenetratorPhase = PenetratorPhase.OBSERVE
    observations: List[Dict[str, Any]] = Field(default_factory=list)
    origin_traces: List[Dict[str, Any]] = Field(default_factory=list)
    fingerprint: Dict[str, Any] = Field(default_factory=dict)
    topology: Dict[str, Any] = Field(default_factory=dict)
    cnc_server_identified: bool = False
    cnc_addresses: List[str] = Field(default_factory=list)
    recommendation: str = ""
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class GhostMission(BaseModel):
    """A Ghost Swarm deployment into a containment zone."""
    mission_id: UUID = Field(default_factory=uuid4)
    containment_zone: str
    ghost_count: int = 7
    ghosts: List[Dict[str, Any]] = Field(default_factory=list)  # type, status, findings
    real_intelligence_count: int = 3
    decoy_count: int = 2
    deployed_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "active"


# =============================================================================
# ATTACKER PROFILE & FORENSICS
# =============================================================================

class AttackerProfile(BaseModel):
    """Behavioral fingerprint of an attacker."""
    profile_id: UUID = Field(default_factory=uuid4)
    communication_protocol: Dict[str, Any] = Field(default_factory=dict)
    network_topology: Dict[str, Any] = Field(default_factory=dict)
    tool_signatures: List[str] = Field(default_factory=list)
    behavioral_patterns: Dict[str, Any] = Field(default_factory=dict)
    working_hours: Optional[str] = None
    timezone_estimate: Optional[str] = None
    sophistication_level: int = 1      # 1-5 scale
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: Optional[datetime] = None
    active_channels: List[str] = Field(default_factory=list)
    expected_responses: Dict[str, Any] = Field(default_factory=dict)


class ForensicRecord(BaseModel):
    """Immutable forensic evidence record."""
    record_id: UUID = Field(default_factory=uuid4)
    event_type: str                    # mirror_absorb, curiosity_alarm, trap_interaction, etc.
    source_entity: Optional[str] = None
    target_entity: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)
    chain_hash: str = ""               # SHA-256 chain for immutability
    previous_record_hash: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    def compute_chain_hash(self, previous_hash: str = "") -> str:
        data = f"{self.record_id}:{self.event_type}:{self.timestamp.isoformat()}:{previous_hash}"
        self.chain_hash = hashlib.sha256(data.encode()).hexdigest()
        self.previous_record_hash = previous_hash
        return self.chain_hash


# =============================================================================
# EPHEMERAL CERTIFICATES
# =============================================================================

class EphemeralCertificate(BaseModel):
    """Scoped, time-limited birth authority certificate."""
    cert_id: UUID = Field(default_factory=uuid4)
    max_births: int = 50
    births_used: int = 0
    valid_until: datetime
    fibre_types_allowed: List[str] = Field(default_factory=list)
    ring_regions_allowed: List[str] = Field(default_factory=list)
    issued_at: datetime = Field(default_factory=datetime.utcnow)
    issuer_shards: List[int] = Field(default_factory=list)  # Which shard holders authorized
    revoked: bool = False
    fibres_born: List[UUID] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return (
            not self.revoked
            and self.births_used < self.max_births
            and datetime.utcnow() < self.valid_until
        )


# =============================================================================
# TRINITY HELIX (v3.1)
# =============================================================================

class HelixState(BaseModel):
    """Current state of the Trinity Helix rotation."""
    current_sequence: List[int] = Field(default_factory=lambda: list(range(9)))
    rotation_interval_ms: float = 200.0
    rotation_count: int = 0
    last_rotation_ns: int = Field(default_factory=time.monotonic_ns)
    entropy_sources_healthy: bool = True


class InvertedSpace(BaseModel):
    """A triangular mirror space containing an inverted attacker."""
    space_id: UUID = Field(default_factory=uuid4)
    attacker_fingerprint_id: Optional[UUID] = None
    entry_gate: str = ""
    entry_time: datetime = Field(default_factory=datetime.utcnow)
    helix_state_at_entry: List[int] = Field(default_factory=list)
    interaction_count: int = 0
    tripwires_triggered: int = 0
    is_active: bool = True
    forensic_records: int = 0


# =============================================================================
# PROJECTED HELIX (v3.2)
# =============================================================================

class ProjectedHelixDeployment(BaseModel):
    """A Projected Helix deployment against an attacker."""
    deployment_id: UUID = Field(default_factory=uuid4)
    target_profile_id: UUID
    penetrator_report_id: UUID
    status: ProjectionStatus = ProjectionStatus.PENDING_AUTH
    authorized_by: Optional[str] = None
    authorized_at: Optional[datetime] = None
    deployed_at: Optional[datetime] = None
    mirror_accuracy: float = 0.7
    interactions_mirrored: int = 0
    commands_intercepted: int = 0
    intelligence_gathered: Dict[str, Any] = Field(default_factory=dict)


class RecursiveLearningState(BaseModel):
    """State of the self-improving mirror within a Projected Helix."""
    deployment_id: UUID
    attacker_model_version: int = 0
    model_accuracy: float = 0.7
    interaction_history_size: int = 0
    protocol_patterns_learned: int = 0
    last_model_update: Optional[datetime] = None


# =============================================================================
# QUARANTINE
# =============================================================================

class QuarantineRecord(BaseModel):
    """Post-birth behavioral quarantine for a new Fibre."""
    fibre_id: UUID
    started_at: datetime = Field(default_factory=datetime.utcnow)
    duration_minutes: int = 60
    heartbeat_consistent: bool = False
    access_pattern_normal: bool = False
    ring_interaction_valid: bool = False
    trail_emission_appropriate: bool = False
    passed: Optional[bool] = None
    evaluated_at: Optional[datetime] = None


# =============================================================================
# BEHAVIORAL SNAPSHOT
# =============================================================================

class BehavioralSnapshot(BaseModel):
    """Weekly cryptographic snapshot of a Fibre's behavioral profile."""
    snapshot_id: UUID = Field(default_factory=uuid4)
    entity_id: UUID
    week_number: int
    data_access_hash: str = ""
    communication_graph_hash: str = ""
    trail_emission_fingerprint: str = ""
    coherence_baseline_hash: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# CONSERVATION LEDGER
# =============================================================================

class ConservationLedgerEntry(BaseModel):
    """Quakete energy conservation verification record."""
    entry_id: UUID = Field(default_factory=uuid4)
    total_system_energy: float
    ledger_state_hash: str
    verified_at: datetime = Field(default_factory=datetime.utcnow)
    violations_detected: int = 0
    is_valid: bool = True


# =============================================================================
# CANARY & TRIPWIRE
# =============================================================================

class CanaryCredential(BaseModel):
    """Decoy credential planted in the runtime environment."""
    canary_id: UUID = Field(default_factory=uuid4)
    credential_type: str              # db_string, api_key, member_record
    planted_location: str
    planted_at: datetime = Field(default_factory=datetime.utcnow)
    accessed: bool = False
    accessed_at: Optional[datetime] = None
    access_source: Optional[str] = None


class TripwireActivation(BaseModel):
    """Record of a tripwire being triggered in synthetic data."""
    tripwire_id: UUID = Field(default_factory=uuid4)
    tripwire_type: str                # email_lookup, credential_use, score_verify
    containment_zone: str
    triggered_by: str = ""
    triggered_at: datetime = Field(default_factory=datetime.utcnow)
    evidence: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# EVENT TOPICS
# =============================================================================

HIVE_EVENT_TOPICS = {
    # Mirror
    "hive.mirror.signal_absorbed": "External signal caught in mirror",
    "hive.mirror.fake_heartbeat_detected": "Forged heartbeat attempt",
    # Curiosity
    "hive.curiosity.notice": "First anomaly observed",
    "hive.curiosity.interest": "Multiple anomalies — investigating",
    "hive.curiosity.concern": "Ring partners confirm divergence",
    "hive.curiosity.alarm": "Three-cord failure — containment",
    # Isolation
    "hive.isolation.mesh_partitioned": "Containment perimeter active",
    "hive.isolation.entity_quarantined": "Compromised entity isolated",
    # Penetrator
    "hive.penetrator.deployed": "Tracing mission launched",
    "hive.penetrator.report_ready": "Mission complete — findings available",
    # Trap
    "hive.trap.deployed": "Infinite Mirror Trap active",
    "hive.trap.interaction": "Attacker interacting with trap",
    "hive.trap.attacker_disengaged": "Attacker stopped",
    # Defense
    "hive.defense.all_clear": "Incident resolved — normal operations",
    # v3.0 topics
    "hive.birth.anomaly_detected": "Birth rate or source anomaly",
    "hive.birth.quarantine_started": "New Fibre entering quarantine",
    "hive.birth.quarantine_passed": "Fibre cleared quarantine",
    "hive.birth.quarantine_failed": "Fibre failed quarantine — contained",
    "hive.cert.parallel_usage": "Certificate used from two locations",
    "hive.snapshot.drift_detected": "Weekly snapshot comparison shows drift",
    "hive.payload.entropy_anomaly": "Payload entropy outside expected range",
    "hive.payload.effect_anomaly": "Payload caused unexpected state change",
    "hive.containment.shell_entered": "Attacker entered recursive shell N",
    "hive.containment.shell_escaped": "Attacker escaped shell N (enters N+1)",
    "hive.tripwire.activated": "Synthetic data trap triggered",
    "hive.tripwire.credential_used": "Synthetic credential used — secondary honeypot",
    "hive.duress.code_received": "Shard holder used duress code — DEFCON 1",
    "hive.backup.anomalous_access": "Backup accessed outside normal pattern",
    "hive.triage.activated": "Multi-vector triage engaged",
    "hive.conservation.violation": "Energy conservation law violated",
}
