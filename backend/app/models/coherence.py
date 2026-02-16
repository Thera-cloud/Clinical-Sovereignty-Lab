"""
SOVEREIGN SWARM — Coherence Models
5-layer coherence measurement system (Code Guidelines Section V).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# LAYERS
# =============================================================================

class CoherenceLayer(str, Enum):
    """Five nested coherence measurement scopes."""
    INDIVIDUAL = "individual"       # Single-person CEE aggregation
    FAMILY = "family"               # Family-system resonance
    COMMUNITY = "community"         # 50+ family-systems aggregate
    CULTURAL = "cultural"           # Internal-vs-external gap (SkyEye bridge)
    GLOBAL = "global"               # Planetary emotional weather


# =============================================================================
# THRESHOLDS
# =============================================================================

class LayerThresholds(BaseModel):
    """Minimum data thresholds before a layer becomes reportable."""
    individual_min_sessions: int = 3
    family_min_members: int = 2
    community_min_families: int = 50
    cultural_min_individuals: int = 200
    cultural_min_families: int = 30
    global_min_communities: int = 5


# =============================================================================
# MEASUREMENTS
# =============================================================================

class CoherenceMeasurement(BaseModel):
    """A single coherence reading at any layer."""
    measurement_id: UUID = Field(default_factory=uuid4)
    layer: CoherenceLayer
    score: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    # Scope identifiers (populated based on layer — UUIDs per migration 007 schema)
    user_id: Optional[UUID] = None          # Individual
    family_id: Optional[UUID] = None        # Family
    community_id: Optional[str] = None     # Community
    cultural_context: Optional[str] = None # Cultural
    region: Optional[str] = None           # Global

    # Component breakdown
    components: Dict[str, float] = Field(default_factory=dict)
    # e.g. {"cee_aggregate": 0.72, "quiz_signal": 0.65, "behavioral": 0.80}

    # Trend
    delta_24h: Optional[float] = None  # change vs 24 hours ago
    delta_7d: Optional[float] = None   # change vs 7 days ago

    # Metadata
    sample_size: int = 0
    measured_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# GAP ANALYSIS
# =============================================================================

class CoherenceGap(BaseModel):
    """Inside/Outside coherence gap analysis (Section V Layer 4)."""
    gap_id: UUID = Field(default_factory=uuid4)
    internal_score: float = Field(..., ge=0.0, le=1.0)
    external_score: float = Field(..., ge=0.0, le=1.0)
    gap_magnitude: float = Field(..., ge=-1.0, le=1.0)
    statistical_significance: float = Field(default=0.0, ge=0.0, le=1.0)
    trending_themes_internal: List[str] = Field(default_factory=list)
    trending_themes_external: List[str] = Field(default_factory=list)
    cultural_context: Optional[str] = None
    measured_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# PULSE AGGREGATES
# =============================================================================

class PulseSnapshot(BaseModel):
    """Aggregated data for The Pulse dashboard."""
    global_coherence_index: float = Field(default=0.0, ge=0.0, le=1.0)
    layer_scores: Dict[str, float] = Field(default_factory=dict)
    trending_themes: List[str] = Field(default_factory=list)
    gap_analysis: Optional[CoherenceGap] = None
    active_alerts: int = 0
    notable_changes: List[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
