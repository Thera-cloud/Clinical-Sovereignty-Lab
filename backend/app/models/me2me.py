"""
SOVEREIGN SWARM — Me-2-Me Platinum Models
Data contracts for the capstone legacy system: identity preservation,
transgenerational interaction, and organic-to-inorganic migration.

Me2Me Platinum Legacy Architecture v1.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# CONSENT LEVELS
# =============================================================================

class ConsentLevel(str, Enum):
    """Three-level consent architecture for Me-2-Me participation."""
    OBSERVE = "observe"       # Level 1: Data collection acknowledged
    PRESERVE = "preserve"     # Level 2: Active identity crystallization
    INTERACT = "interact"     # Level 3: Post-mortem avatar activation


class ConsentStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    SUSPENDED = "suspended"
    PENDING = "pending"


class ConsentRecord(BaseModel):
    """Immutable consent record for a member's Me-2-Me participation."""
    consent_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    level: ConsentLevel
    status: ConsentStatus = ConsentStatus.PENDING
    granted_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    renewal_due: Optional[datetime] = None
    witness_signature: Optional[str] = None
    legal_notice_acknowledged: bool = False
    version: int = 1
    audit_trail: List[Dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# IDENTITY CRYSTAL
# =============================================================================

class PersonalityProfile(BaseModel):
    """Big Five + therapeutic personality dimensions."""
    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5
    attachment_style: str = "unknown"
    conflict_resolution_style: str = "unknown"
    emotional_processing_speed: float = 0.5
    vulnerability_capacity: float = 0.5
    humor_style: str = "unknown"
    confidence: float = 0.0


class LanguageSignature(BaseModel):
    """Unique linguistic fingerprint of a member."""
    vocabulary_level: str = "standard"
    sentence_complexity: float = 0.5
    metaphor_usage_frequency: float = 0.0
    favorite_phrases: List[str] = Field(default_factory=list)
    emotional_vocabulary_range: float = 0.5
    communication_style: str = "balanced"
    formality_preference: float = 0.5
    humor_markers: List[str] = Field(default_factory=list)
    cultural_references: List[str] = Field(default_factory=list)


class HumorProfile(BaseModel):
    """Member's humor characteristics for avatar authenticity."""
    humor_style: str = "affiliative"
    sarcasm_frequency: float = 0.0
    self_deprecation_level: float = 0.0
    timing_preference: str = "natural"
    topic_preferences: List[str] = Field(default_factory=list)
    humor_triggers: List[str] = Field(default_factory=list)
    sample_exchanges: List[Dict[str, str]] = Field(default_factory=list)


class IdentityCrystal(BaseModel):
    """Monthly synthesis: the crystallized identity of a member."""
    crystal_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    crystal_version: int = 1
    synthesized_at: datetime = Field(default_factory=datetime.utcnow)
    personality: PersonalityProfile = Field(default_factory=PersonalityProfile)
    language: LanguageSignature = Field(default_factory=LanguageSignature)
    humor: HumorProfile = Field(default_factory=HumorProfile)
    core_values: List[str] = Field(default_factory=list)
    life_themes: List[str] = Field(default_factory=list)
    relationship_patterns: Dict[str, str] = Field(default_factory=dict)
    therapeutic_journey_summary: str = ""
    growth_narrative: str = ""
    wisdom_distilled: List[str] = Field(default_factory=list)
    coherence_signature: Dict[str, float] = Field(default_factory=dict)
    confidence_score: float = 0.0
    data_points_used: int = 0
    sessions_analyzed: int = 0


# =============================================================================
# AVATAR CORE
# =============================================================================

class AvatarStatus(str, Enum):
    INACTIVE = "inactive"     # Not yet activated
    LEARNING = "learning"     # Still accumulating data
    READY = "ready"           # Enough data, not yet activated
    ACTIVE = "active"         # Post-transition, accepting visitors
    DORMANT = "dormant"       # Temporarily paused
    ARCHIVED = "archived"     # Permanently stored


class AvatarCore(BaseModel):
    """The Me-2-Me Avatar — identity-locked response generation engine."""
    avatar_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    display_name: str = ""
    status: AvatarStatus = AvatarStatus.INACTIVE
    crystal_version_locked: int = 0
    latest_crystal_id: Optional[str] = None
    activation_date: Optional[datetime] = None
    total_visitor_sessions: int = 0
    total_interactions: int = 0
    grief_monitoring_active: bool = True
    response_accuracy_score: float = 0.0
    family_fabric_id: Optional[str] = None
    ethical_boundaries: Dict[str, Any] = Field(default_factory=dict)
    growth_layers: List[str] = Field(default_factory=list)


# =============================================================================
# GROWTH ENGINE
# =============================================================================

class GrowthLayer(BaseModel):
    """Post-mortem knowledge acquisition layer."""
    layer_id: str = Field(default_factory=lambda: str(uuid4()))
    avatar_id: str
    knowledge_source: str = ""
    knowledge_type: str = "general"
    content_summary: str = ""
    acquired_at: datetime = Field(default_factory=datetime.utcnow)
    clearly_marked_as_post: bool = True
    confidence: float = 0.0


# =============================================================================
# FAMILY FABRIC
# =============================================================================

class FamilyFabric(BaseModel):
    """Cross-avatar family connection management."""
    fabric_id: str = Field(default_factory=lambda: str(uuid4()))
    family_id: str
    member_avatars: Dict[str, str] = Field(default_factory=dict)
    relationship_map: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    shared_memories: List[Dict[str, Any]] = Field(default_factory=list)
    family_themes: List[str] = Field(default_factory=list)
    transgenerational_patterns: List[str] = Field(default_factory=list)
    cross_avatar_interactions: int = 0


# =============================================================================
# MIGRATION
# =============================================================================

class MigrationPhase(str, Enum):
    NOT_STARTED = "not_started"
    GRADUAL_TRANSFER = "gradual_transfer"
    PARALLEL_RUNNING = "parallel_running"
    FINAL_TRANSITION = "final_transition"
    COMPLETE = "complete"


class MigrationRecord(BaseModel):
    """Organic-to-inorganic transition tracking."""
    migration_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    phase: MigrationPhase = MigrationPhase.NOT_STARTED
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    trigger: str = "manual"  # manual | health_directive | estate_executor
    data_completeness_score: float = 0.0
    crystal_quality_score: float = 0.0
    avatar_readiness_score: float = 0.0
    guardian_id: Optional[str] = None
    guardian_notified: bool = False
    legal_trust_linked: bool = False
    final_words_recorded: bool = False


# =============================================================================
# IMPRINT ACCUMULATOR
# =============================================================================

class ImprintEntry(BaseModel):
    """Single imprint absorbed by the accumulator."""
    entry_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    source: str = ""  # session, homework, journal, voice_note, milestone
    content_hash: str = ""
    themes: List[str] = Field(default_factory=list)
    emotions: List[str] = Field(default_factory=list)
    voice_biometrics: Optional[Dict[str, float]] = None
    c_emo_at_capture: float = 0.0
    gamma_at_capture: float = 0.0
    captured_at: datetime = Field(default_factory=datetime.utcnow)
    processed: bool = False


# =============================================================================
# TRUST & LEGAL
# =============================================================================

class TrustBeneficiary(BaseModel):
    """Beneficiary of a Sovereign Legacy Trust."""
    beneficiary_id: str = Field(default_factory=lambda: str(uuid4()))
    trust_id: str
    name: str = ""
    relationship: str = ""
    email: Optional[str] = None
    access_level: str = "visitor"
    age_gate: Optional[int] = None
    age_gate_content_filters: List[str] = Field(default_factory=list)
    guardian_id: Optional[str] = None


class SovereignLegacyTrust(BaseModel):
    """Legal trust structure wrapping a Me-2-Me identity."""
    trust_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    trust_name: str = ""
    grantor_name: str = ""
    trustee_contact: Optional[str] = None
    beneficiaries: List[TrustBeneficiary] = Field(default_factory=list)
    funding_method: str = "subscription"
    annual_funding_amount: float = 0.0
    tax_id: Optional[str] = None
    jurisdiction: str = "US"
    established_date: Optional[datetime] = None
    perpetuity_duration_years: int = 100
    successor_guardian_chain: List[str] = Field(default_factory=list)
    status: str = "draft"  # draft, active, funded, dissolved
