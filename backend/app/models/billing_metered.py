"""
SOVEREIGN SWARM — Metered Billing Models
Data contracts for usage-based billing, session cost caps, and
legacy vault storage tiers.

Operational Specifications §4 — Metered Billing.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# =============================================================================
# ENUMERATIONS
# =============================================================================

class BillingTier(str, Enum):
    THRESHOLD = "TRIAL"
    INNER_CHAMBER = "STANDARD"
    SOVEREIGN_CIRCLE = "TOP_TIER"

    @classmethod
    def from_subscription_tier(cls, tier: str) -> "BillingTier":
        """Map subscription tier name to billing tier."""
        mapping = {
            "TRIAL": cls.THRESHOLD,
            "STANDARD": cls.INNER_CHAMBER,
            "TOP_TIER": cls.SOVEREIGN_CIRCLE,
            # Legacy lowercase values
            "threshold": cls.THRESHOLD,
            "inner_chamber": cls.INNER_CHAMBER,
            "sovereign_circle": cls.SOVEREIGN_CIRCLE,
        }
        return mapping.get(tier, cls.THRESHOLD)


class UsageType(str, Enum):
    AI_SESSION_MINUTE = "ai_session_minute"
    COACH_SESSION = "coach_session"
    FAMILY_SANCTUARY_SESSION = "family_sanctuary_session"
    LEGACY_VAULT_STORAGE_GB = "legacy_vault_storage_gb"
    ME2ME_AVATAR_HOUR = "me2me_avatar_hour"
    ME2ME_GROWTH_QUERY = "me2me_growth_query"
    VOICE_ANALYSIS_MINUTE = "voice_analysis_minute"
    NIGHT_SCHOOL_INGESTION_MB = "night_school_ingestion_mb"
    NEVEDAL_REPORT = "nevedal_report"
    FORESIGHT_REPORT = "foresight_report"
    ARCHIVIST_CHAPTER = "archivist_chapter"


# =============================================================================
# METERED BILLING LAYER
# =============================================================================

class UsageRecord(BaseModel):
    """A single metered usage event."""
    record_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    usage_type: UsageType
    quantity: float = 0.0
    unit_cost: float = 0.0
    total_cost: float = 0.0
    session_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    stripe_usage_record_id: Optional[str] = None
    reported_to_stripe: bool = False


class MeteredBillingLayer(BaseModel):
    """Per-user billing state for the current billing period."""
    user_id: str
    billing_tier: BillingTier = BillingTier.THRESHOLD
    billing_period_start: Optional[datetime] = None
    billing_period_end: Optional[datetime] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    included_ai_minutes: float = 0.0
    used_ai_minutes: float = 0.0
    included_coach_sessions: int = 0
    used_coach_sessions: int = 0
    overage_charges: float = 0.0
    session_cost_cap: float = 500.0
    session_cost_cap_hit: bool = False
    total_current_period: float = 0.0
    usage_records: List[str] = Field(default_factory=list)


# =============================================================================
# LEGACY VAULT BILLING
# =============================================================================

class LegacyVaultBilling(BaseModel):
    """Long-term storage billing for Me-2-Me data."""
    user_id: str
    vault_size_gb: float = 0.0
    tier: str = "standard"  # standard, archive, deep_archive
    monthly_cost: float = 0.0
    last_billed: Optional[datetime] = None
    retention_years: int = 100
    auto_migrate_to_archive_after_days: int = 365
    stripe_price_id: Optional[str] = None


# =============================================================================
# COST THRESHOLDS
# =============================================================================

class CostThresholdConfig(BaseModel):
    """Configuration for session cost caps and alerts."""
    user_id: str
    per_session_cap: float = 500.0
    monthly_cap: float = 2000.0
    warning_threshold_pct: float = 0.8
    hard_stop_enabled: bool = True
    overage_allowed: bool = False
    notification_on_warning: bool = True
    notification_on_cap: bool = True
