"""
SOVEREIGN SWARM — Swarm State Models
Aggregate swarm state and convergence detection data contracts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# SWARM STATE — Aggregate view of the entire swarm
# =============================================================================

class FibreSummary(BaseModel):
    """Compact summary of one Fibre for fleet-level views."""
    fibre_id: UUID
    fibre_type: str
    status: str
    autonomy_level: str
    domain: Optional[str] = None
    alignment_score: float = 0.0
    token_budget_remaining: float = 0.0
    ring_id: Optional[str] = None
    quakete_mode: Optional[str] = None
    communication_health: Optional[float] = None
    last_active: Optional[datetime] = None


class SwarmState(BaseModel):
    """
    Complete snapshot of the Sovereign Swarm's operational state.
    Used by Swarm Oversight (Layer 6 of Strategic Memory) and
    the Sovereign Mind for fleet-level decision making.
    """
    snapshot_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Fleet summary
    total_fibres: int = 0
    active_fibres: int = 0
    quarantined_fibres: int = 0
    idle_fibres: int = 0

    # By type
    fibres_by_type: Dict[str, int] = Field(default_factory=dict)
    fibres_by_autonomy: Dict[str, int] = Field(default_factory=dict)

    # Fibre list
    fibres: List[FibreSummary] = Field(default_factory=list)

    # Coherence summary
    global_coherence: Optional[float] = None
    coherence_by_layer: Dict[str, float] = Field(default_factory=dict)

    # Quakete summary
    total_rings: int = 0
    healthy_rings: int = 0
    distressed_rings: int = 0
    active_quakete_transfers: int = 0
    silent_fibres: int = 0

    # Wisdom Mesh summary
    mesh_messages_last_hour: int = 0
    convergence_alerts_last_hour: int = 0
    pending_proposals: int = 0

    # ZEFCP summary
    total_endpoints: int = 0
    observations_delivered_last_hour: int = 0
    avg_fragment_loss_rate: float = 0.0


# =============================================================================
# CONVERGENCE ALERT — When independent Fibres reach correlated conclusions
# =============================================================================

class ConvergenceAlert(BaseModel):
    """
    Generated when the Convergence Engine detects that multiple
    independent Fibres have arrived at statistically correlated
    conclusions from different observational vantage points.

    These emergent insights exceed any single Fibre's capability.
    """
    alert_id: UUID = Field(default_factory=uuid4)
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    contributing_fibre_ids: List[str] = Field(default_factory=list)
    contributing_fibre_types: List[str] = Field(default_factory=list)
    convergence_score: float = Field(..., ge=0.0, le=1.0, description="Statistical correlation strength")
    shared_theme: str = Field(..., description="The convergent insight theme")
    shared_insight: str = Field(..., description="Synthesized emergent insight")
    individual_observations: List[Dict[str, Any]] = Field(default_factory=list)
    domains: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    escalated_to_sovereign_mind: bool = False
    human_notified: bool = False


# =============================================================================
# SWARM DIRECTIVE — Orders from Sovereign Mind to Fibres
# =============================================================================

class SwarmDirective(BaseModel):
    """A directive issued by the Sovereign Mind to one or more Fibres."""
    directive_id: UUID = Field(default_factory=uuid4)
    issued_at: datetime = Field(default_factory=datetime.utcnow)
    issued_by: str = "sovereign_mind"
    target_fibre_ids: List[str] = Field(default_factory=list, description="Empty = broadcast to all")
    target_fibre_types: List[str] = Field(default_factory=list)
    directive_type: str = Field(..., description="standing_order | mission_update | priority_shift | recall")
    content: Dict[str, Any] = Field(default_factory=dict)
    priority: str = "normal"
    expires_at: Optional[datetime] = None
    acknowledged_by: List[str] = Field(default_factory=list)
