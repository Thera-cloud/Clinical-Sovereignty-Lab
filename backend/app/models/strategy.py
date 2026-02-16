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


class ApprovalCategory(str, Enum):
    """
    Four-tier approval category system (PhD Architecture §7.3).

    Each proposal is classified into one of these categories based on
    its risk level and action type. The category determines the approval
    workflow:

        OBSERVE   — Pure logging, no approval needed. Fibre acts autonomously.
        SUGGEST   — Implicit approval with auto-execute after timeout.
        ACT       — Explicit single-party human approval required.
        CRITICAL  — Multi-party approval + mandatory cooling period + dead-man switch.
    """
    OBSERVE = "observe"      # No approval needed (log only)
    SUGGEST = "suggest"      # Auto-execute after timeout window
    ACT = "act"              # Requires explicit human approval
    CRITICAL = "critical"    # Multi-party approval + cooling period


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
    approval_category: ApprovalCategory = ApprovalCategory.ACT
    status: ProposalStatus = ProposalStatus.PROPOSED

    # Execution
    execution_payload: Dict[str, Any] = Field(default_factory=dict)
    rollback_payload: Optional[Dict[str, Any]] = None
    auto_execute_after: Optional[datetime] = None  # auto-execute window

    # Approval
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

    # Multi-party approval (for CRITICAL category)
    required_approvers: int = Field(default=1, ge=1)
    approver_list: List[str] = Field(default_factory=list)  # who has approved so far
    cooling_period_hours: int = Field(default=0, ge=0)  # mandatory wait after approval before execution

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


# =============================================================================
# APPROVAL DECISIONS AUDIT (Migration 020, PhD Spec §10.4)
# =============================================================================

class ApprovalDecisionAudit(BaseModel):
    """Immutable audit trail entry for every approval decision. Append-only."""
    audit_id: UUID = Field(default_factory=uuid4)
    proposal_id: UUID
    decision: str  # APPROVE | REJECT | HOLD | MODIFY
    channel: Optional[str] = None  # email | sms | api | admin_panel
    approver: Optional[str] = None
    approval_category: Optional[str] = None  # observe | suggest | act | critical
    raw_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# FIBRE BEHAVIORAL BASELINES (Migration 020, PhD Spec §8.5)
# =============================================================================

class FibreBehavioralBaseline(BaseModel):
    """Statistical baseline for a Fibre's behavioral metrics (anomaly detection)."""
    baseline_id: UUID = Field(default_factory=uuid4)
    fibre_id: UUID
    metric_name: str  # msg_rate_per_min | topic_spread | token_usage | conclusion_diversity
    baseline_mean: float
    baseline_std: float = 0.0
    sample_count: int = 0
    window_hours: int = 24
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# LEGACY VAULT CONSENT (Extended — Migration 020, PhD Spec §11.3)
# =============================================================================

class LegacyVaultConsent(BaseModel):
    """Granular consent record for Legacy Vault data sharing."""
    user_id: UUID
    family_id: UUID
    consented: bool = False
    data_types: Optional[List[str]] = None  # null = all types; e.g. ["emotional_themes", "coping_mechanisms"]
    is_minor: bool = False
    guardian_id: Optional[UUID] = None
    sharing_restricted: bool = False
    updated_at: datetime = Field(default_factory=datetime.utcnow)
