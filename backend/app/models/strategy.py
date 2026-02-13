"""
SOVEREIGN SWARM — Strategic Memory Models
6-layer strategic memory system (Code Guidelines Section II / III).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# ENUMERATIONS
# =============================================================================

class ProposalStatus(str, Enum):
    PROPOSED = "proposed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"
    AUTO_EXECUTED = "auto_executed"


class ProposalRisk(str, Enum):
    LOW = "low"          # auto-execute eligible
    MEDIUM = "medium"    # requires approval
    HIGH = "high"        # requires explicit confirmation
    CRITICAL = "critical"  # requires multi-factor confirmation


class InsightDomain(str, Enum):
    CLINICAL = "clinical"
    MARKETING = "marketing"
    CULTURAL = "cultural"
    OPERATIONAL = "operational"
    FORESIGHT = "foresight"
    SWARM = "swarm"


class OrderOrigin(str, Enum):
    """Where a Standing Order came from."""
    BIG_NATE_DIRECT = "big_nate_direct"
    STRATEGY_SESSION = "strategy_session"
    INSIGHT_PROMOTION = "insight_promotion"
    SYSTEM_DEFAULT = "system_default"


# =============================================================================
# LAYER 1 — STANDING ORDERS
# =============================================================================

class StandingOrder(BaseModel):
    """Persistent directives that govern Fibre behavior."""
    order_id: UUID = Field(default_factory=uuid4)
    title: str = Field(..., min_length=1, max_length=256)
    directive: str
    origin: OrderOrigin = OrderOrigin.BIG_NATE_DIRECT
    domain_tags: List[str] = Field(default_factory=list)
    priority: int = Field(default=5, ge=1, le=10)
    active: bool = True
    performance_score: Optional[float] = None  # 0-1, tracked over time
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = "big_nate"
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# LAYER 2 — INSIGHT LOG
# =============================================================================

class Insight(BaseModel):
    """Tagged observations with confidence and domain classification."""
    insight_id: UUID = Field(default_factory=uuid4)
    title: str = Field(..., min_length=1, max_length=256)
    body: str
    domain: InsightDomain = InsightDomain.OPERATIONAL
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list)
    source_fibre_id: Optional[UUID] = None
    source_type: str = "system"  # system | fibre | human | convergence
    related_insight_ids: List[UUID] = Field(default_factory=list)
    promoted_to_order: bool = False
    promoted_order_id: Optional[UUID] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# LAYER 3 — STRATEGY PROPOSALS (DEPLOY QUEUE)
# =============================================================================

class StrategyProposal(BaseModel):
    """Actionable strategy proposal requiring approval or auto-execution."""
    proposal_id: UUID = Field(default_factory=uuid4)
    title: str = Field(..., min_length=1, max_length=256)
    description: str
    action_type: str  # create_quiz, shift_content_mix, campaign_launch, etc.
    proposed_by: str = "sovereign_mind"
    risk: ProposalRisk = ProposalRisk.MEDIUM
    status: ProposalStatus = ProposalStatus.PROPOSED

    # Execution
    execution_payload: Dict[str, Any] = Field(default_factory=dict)
    rollback_payload: Optional[Dict[str, Any]] = None
    auto_execute_after: Optional[datetime] = None  # auto-execute window

    # Approval
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

    # Results
    execution_result: Optional[Dict[str, Any]] = None
    executed_at: Optional[datetime] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# LAYER 4 — COHERENCE BRIEFINGS
# =============================================================================

class CoherenceBriefing(BaseModel):
    """Periodic synthesis report from the coherence engine."""
    briefing_id: UUID = Field(default_factory=uuid4)
    period_start: datetime
    period_end: datetime
    global_coherence_index: float = Field(default=0.0, ge=0.0, le=1.0)
    layer_summaries: Dict[str, Any] = Field(default_factory=dict)
    # e.g. {"individual": {"avg": 0.72, "count": 145, "trend": "rising"}, ...}
    trending_themes: List[str] = Field(default_factory=list)
    gap_analysis_summary: Optional[str] = None
    notable_changes: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# LAYER 5 — FORESIGHT ALERTS
# =============================================================================

class ForesightAlert(BaseModel):
    """Predictive entry with confidence intervals and alternative scenarios."""
    alert_id: UUID = Field(default_factory=uuid4)
    signal_description: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_interval_lower: float = 0.0
    confidence_interval_upper: float = 1.0
    time_horizon_hours: int = 24
    affected_populations: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    alternative_scenarios: List[Dict[str, Any]] = Field(default_factory=list)
    monitoring_indicators: List[str] = Field(default_factory=list)
    source_fibre_id: Optional[UUID] = None
    source_data_streams: List[str] = Field(default_factory=list)
    # e.g. ["internal_therapeutic", "external_cultural", "historical_pattern", "contextual"]
    actual_outcome: Optional[str] = None  # filled post-facto for accuracy tracking
    accuracy_score: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# LAYER 6 — SWARM OVERSIGHT
# =============================================================================

class SwarmOversightEntry(BaseModel):
    """Fibre inventory, spawning log, mesh health — Layer 6."""
    entry_id: UUID = Field(default_factory=uuid4)
    event_type: str  # spawn | prune | alignment_check | convergence | quarantine | health
    fibre_id: Optional[UUID] = None
    fibre_type: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    mesh_health: Optional[Dict[str, float]] = None
    active_fibre_count: int = 0
    total_tokens_consumed: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)
