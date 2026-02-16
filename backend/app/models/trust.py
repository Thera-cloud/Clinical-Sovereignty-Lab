"""
SOVEREIGN SWARM — Trust Models
Re-exports and extensions from me2me.py for backward compatibility.
Also includes additional trust-framework models for the legal integration layer.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

# Re-export core trust models
from app.models.me2me import (  # noqa: F401
    SovereignLegacyTrust,
    TrustBeneficiary,
)


# =============================================================================
# TRUST FUNDING
# =============================================================================

class FundingType(str, Enum):
    SUBSCRIPTION = "subscription"
    LUMP_SUM = "lump_sum"
    ESTATE_TRANSFER = "estate_transfer"
    INSURANCE_ASSIGNMENT = "insurance_assignment"


class TrustFunding(BaseModel):
    """Funding record for a Sovereign Legacy Trust."""
    funding_id: str = Field(default_factory=lambda: str(uuid4()))
    trust_id: str
    funding_type: FundingType = FundingType.SUBSCRIPTION
    amount: float = 0.0
    currency: str = "USD"
    stripe_subscription_id: Optional[str] = None
    stripe_payment_intent_id: Optional[str] = None
    funded_at: datetime = Field(default_factory=datetime.utcnow)
    next_funding_due: Optional[datetime] = None
    status: str = "active"


# =============================================================================
# AGE GATE
# =============================================================================

class AgeGate(BaseModel):
    """Age-gated access control for beneficiaries."""
    gate_id: str = Field(default_factory=lambda: str(uuid4()))
    beneficiary_id: str
    min_age: int = 18
    current_age: Optional[int] = None
    content_filters: List[str] = Field(default_factory=list)
    unlocked_topics: List[str] = Field(default_factory=list)
    restricted_topics: List[str] = Field(default_factory=list)
    guardian_override_allowed: bool = True
    guardian_id: Optional[str] = None


# =============================================================================
# GUARDIAN SUCCESSION
# =============================================================================

class GuardianSuccession(BaseModel):
    """Chain of guardians for a trust."""
    trust_id: str
    primary_guardian_id: str
    successor_chain: List[str] = Field(default_factory=list)
    last_verified: Optional[datetime] = None
    verification_interval_days: int = 365
    auto_transfer_on_inactivity_days: int = 180
    notification_contacts: List[str] = Field(default_factory=list)
