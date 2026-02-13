"""
SOVEREIGN SWARM — Fibre Models
Pydantic data contracts for the Fibre architecture (Code Guidelines Section 5 / 8 / 10).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# ENUMERATIONS
# =============================================================================

class FibreType(str, Enum):
    """All recognized Fibre archetypes."""
    CAMPAIGN = "campaign"
    CULTURAL_SENTINEL = "cultural_sentinel"
    FORESIGHT_ANALYST = "foresight_analyst"
    COACH_SUPPORT = "coach_support"
    QUIZ_FUNNEL = "quiz_funnel"
    COMMUNITY = "community"
    CUSTOM = "custom"


class FibreStatus(str, Enum):
    """Lifecycle state of a Fibre."""
    INITIALIZING = "initializing"
    ACTIVE = "active"
    IDLE = "idle"
    QUARANTINED = "quarantined"
    PRUNING = "pruning"
    ARCHIVED = "archived"


class AutonomyLevel(str, Enum):
    """Graduated autonomy tiers — every Fibre starts at observation."""
    OBSERVATION = "observation"       # Can only observe & report
    RESTRICTED = "restricted"         # Can act within pre-approved scope
    AUTONOMOUS = "autonomous"         # Full autonomy within Standing Orders


# =============================================================================
# CONFIGURATION
# =============================================================================

class FibreConfig(BaseModel):
    """Configuration supplied at Fibre spawn time."""
    fibre_type: FibreType
    name: str = Field(..., min_length=1, max_length=128)
    description: str = ""
    domain_tags: List[str] = Field(default_factory=list)
    token_budget_per_hour: int = Field(default=10_000, ge=0)
    max_concurrent_tasks: int = Field(default=3, ge=1)
    autonomy_level: AutonomyLevel = AutonomyLevel.OBSERVATION
    wisdom_seed: Dict[str, Any] = Field(default_factory=dict)
    parent_fibre_id: Optional[UUID] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# TASK / RESULT
# =============================================================================

class FibreTask(BaseModel):
    """A unit of work dispatched to a Fibre."""
    task_id: UUID = Field(default_factory=uuid4)
    fibre_id: UUID
    task_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=5, ge=1, le=10)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    deadline: Optional[datetime] = None


class FibreResult(BaseModel):
    """Result produced by a Fibre after task execution."""
    task_id: UUID
    fibre_id: UUID
    success: bool
    output: Dict[str, Any] = Field(default_factory=dict)
    tokens_used: int = 0
    duration_ms: int = 0
    ethical_compliance: float = Field(default=1.0, ge=0.0, le=1.0)
    self_alignment_score: float = Field(default=1.0, ge=0.0, le=1.0)
    journal_entry: Optional[str] = None
    completed_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# LIFESPAN TRACKING
# =============================================================================

class FibreLifespan(BaseModel):
    """Full lifecycle record for a Fibre."""
    fibre_id: UUID
    spawned_at: datetime
    spawned_by: str = "sovereign_mind"
    spawn_reason: str = ""
    pruned_at: Optional[datetime] = None
    prune_reason: Optional[str] = None
    total_tasks_executed: int = 0
    total_tokens_consumed: int = 0
    average_alignment_score: float = 1.0
    wisdom_absorbed: bool = False


# =============================================================================
# FIBRE (primary model)
# =============================================================================

class Fibre(BaseModel):
    """Full state representation of a single Fibre."""
    fibre_id: UUID = Field(default_factory=uuid4)
    config: FibreConfig
    status: FibreStatus = FibreStatus.INITIALIZING
    autonomy_level: AutonomyLevel = AutonomyLevel.OBSERVATION

    # Identity (populated by IdentityChainService)
    public_key: Optional[str] = None
    identity_signature: Optional[str] = None  # signed by Sovereign Mind

    # Ethical Core integrity hash
    ethical_core_hash: Optional[str] = None

    # Runtime state
    current_tasks: List[UUID] = Field(default_factory=list)
    tokens_used_this_hour: int = 0
    last_active: Optional[datetime] = None
    alignment_scores: Dict[str, float] = Field(
        default_factory=lambda: {
            "ethical": 1.0,
            "strategic": 1.0,
            "statistical": 1.0,
        }
    )

    # Wisdom & journal
    evolution_journal_ref: Optional[str] = None  # blob storage key
    wisdom_mesh_subscriptions: List[str] = Field(default_factory=list)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # ── helpers ──

    @property
    def is_active(self) -> bool:
        return self.status == FibreStatus.ACTIVE

    @property
    def is_quarantined(self) -> bool:
        return self.status == FibreStatus.QUARANTINED

    def verify_ethical_core(self, core_bytes: bytes) -> bool:
        """Verify the frozen ethical core has not been tampered with."""
        if not self.ethical_core_hash:
            return False
        return hashlib.sha256(core_bytes).hexdigest() == self.ethical_core_hash
