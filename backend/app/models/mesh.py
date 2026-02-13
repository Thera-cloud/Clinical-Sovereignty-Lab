"""
SOVEREIGN SWARM — Wisdom Mesh Models
Message types and convergence detection (Code Guidelines Section IX / XII).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# ENUMERATIONS
# =============================================================================

class MeshMessageType(str, Enum):
    """Message archetypes on the Wisdom Mesh."""
    OBSERVATION = "observation"         # Raw insight from a Fibre
    DIRECTIVE = "directive"             # Downward from Sovereign Mind
    CONVERGENCE = "convergence"         # Multiple Fibres reached similar conclusion
    QUERY = "query"                     # Request for information
    RESPONSE = "response"              # Answer to a query
    HEARTBEAT = "heartbeat"            # Liveness signal
    ALIGNMENT_CHECK = "alignment_check"  # Ethical/strategic alignment request
    QUARANTINE_NOTICE = "quarantine_notice"  # Fibre has been quarantined
    WISDOM_SHARE = "wisdom_share"      # Cross-Fibre knowledge transfer


class MeshPriority(str, Enum):
    """Delivery priority for mesh messages."""
    LOW = "low"           # Batched delivery (1-5 min window)
    NORMAL = "normal"     # Standard delivery (<30s)
    HIGH = "high"         # Immediate delivery
    CRITICAL = "critical"  # Interrupt + alert


class MeshTopology(str, Enum):
    """Communication topology tiers (Section XII.2)."""
    LEVEL_0_SOVEREIGN = "level_0"   # Sovereign Mind — synthesized reports
    LEVEL_1_COORDINATOR = "level_1"  # Domain Coordinators — aggregate clusters
    LEVEL_2_OPERATIONAL = "level_2"  # Standard Fibres — observe/execute
    LEVEL_3_TASK = "level_3"         # Ephemeral micro-agents


# =============================================================================
# MESH MESSAGE
# =============================================================================

class MeshMessage(BaseModel):
    """A single message on the Wisdom Mesh."""
    message_id: UUID = Field(default_factory=uuid4)
    message_type: MeshMessageType
    priority: MeshPriority = MeshPriority.NORMAL

    # Routing
    sender_id: UUID                    # Fibre or Sovereign Mind UUID
    sender_type: str = "fibre"         # fibre | sovereign_mind | system
    recipient_id: Optional[UUID] = None  # Direct delivery (None = topic-based)
    domain_tags: List[str] = Field(default_factory=list)  # Topic routing
    topology_level: MeshTopology = MeshTopology.LEVEL_2_OPERATIONAL

    # Payload
    subject: str = ""
    body: Dict[str, Any] = Field(default_factory=dict)

    # Identity verification
    signature: Optional[str] = None    # Ed25519 signature of body
    identity_chain: Optional[List[str]] = None  # signing chain for verification

    # Metadata
    ttl_seconds: int = Field(default=3600, ge=0)  # Time-to-live
    created_at: datetime = Field(default_factory=datetime.utcnow)
    delivered_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# CONVERGENCE
# =============================================================================

class ConvergenceAlert(BaseModel):
    """Detected when multiple Fibres independently reach similar conclusions."""
    alert_id: UUID = Field(default_factory=uuid4)
    converging_fibre_ids: List[UUID] = Field(default_factory=list)
    converging_message_ids: List[UUID] = Field(default_factory=list)
    topic: str
    convergence_score: float = Field(..., ge=0.0, le=1.0)  # cosine similarity
    temporal_correlation: float = Field(default=0.0, ge=0.0, le=1.0)
    synthesis: str = ""  # AI-generated summary of the convergence
    domain_tags: List[str] = Field(default_factory=list)
    promoted_to_insight: bool = False
    insight_id: Optional[UUID] = None
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# MESH HEALTH
# =============================================================================

class MeshHealth(BaseModel):
    """Real-time health metrics for the Wisdom Mesh."""
    total_messages_24h: int = 0
    messages_per_minute: float = 0.0
    average_latency_ms: float = 0.0
    delivery_success_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    bandwidth_utilization: float = Field(default=0.0, ge=0.0, le=1.0)
    active_subscriptions: int = 0
    pending_messages: int = 0
    convergence_alerts_24h: int = 0
    anomaly_indicators: List[str] = Field(default_factory=list)
    measured_at: datetime = Field(default_factory=datetime.utcnow)
