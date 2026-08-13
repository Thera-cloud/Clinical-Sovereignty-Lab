"""
Canonical tier strings for users.tier and inbound alias normalization.

SOVEREIGN-VOICE / onboarding-billing Phase 2 — single source of truth.
"""

from __future__ import annotations

from typing import Dict

# Column values for users.tier (CHECK-aligned)
TIER_TRIAL = "TRIAL"
TIER_STANDARD = "STANDARD"
TIER_TOP_TIER = "TOP_TIER"
TIER_COACH_ONLY = "COACH_ONLY"
TIER_DEPENDENT = "DEPENDENT"
TIER_SPOUSE = "SPOUSE"
TIER_COACH = "COACH"  # coach accounts

# Long Stripe / invite plan strings → billing buckets (never TOP_TIER / STANDARD — entitlement is separate).
TIER_LONG_PLAN_ALIASES: Dict[str, str] = {
    "DEPENDENT_UNDER_SOVEREIGN_CIRCLE": TIER_DEPENDENT,
    "DEPENDENT_UNDER_INNER_CHAMBER": TIER_DEPENDENT,
    "DEPENDENT_UNDER_THRESHOLD": TIER_DEPENDENT,
    "SPOUSE_UNDER_SOVEREIGN_CIRCLE": TIER_SPOUSE,
    "SPOUSE_UNDER_INNER_CHAMBER": TIER_SPOUSE,
}

# Display / legacy input → canonical DB tier
TIER_ALIASES: Dict[str, str] = {
    "TRIAL": TIER_TRIAL,
    "THRESHOLD": TIER_TRIAL,
    "STANDARD": TIER_STANDARD,
    "INNER_CHAMBER": TIER_STANDARD,
    "TOP_TIER": TIER_TOP_TIER,
    "SOVEREIGN_CIRCLE": TIER_TOP_TIER,
    "SOVEREIGN": TIER_TOP_TIER,
    "TOP": TIER_TOP_TIER,
    "COACH_ONLY": TIER_COACH_ONLY,
    "COACH": TIER_COACH_ONLY,
    "DEPENDENT": TIER_DEPENDENT,
    "SPOUSE": TIER_SPOUSE,
    "FAMILY_MEMBER": TIER_DEPENDENT,
    "MASTER": TIER_STANDARD,
    "SUPERVISOR": TIER_STANDARD,
}

# Initial lump-sum grants when a tier is first assigned (signup / upgrade floor)
TIER_INITIAL_TOKENS: Dict[str, int] = {
    TIER_TRIAL: 10_000,
    TIER_STANDARD: 50_000,
    TIER_TOP_TIER: 200_000,
    TIER_COACH_ONLY: 0,
    TIER_DEPENDENT: 50_000,
    TIER_SPOUSE: 50_000,
    TIER_COACH: 50_000,
}

# Monthly subscription-token cap (subscription_token_balance top-up target per billing period)
TIER_MONTHLY_TOKENS: Dict[str, int] = {
    TIER_TRIAL: 0,
    TIER_STANDARD: 50_000,
    TIER_TOP_TIER: 200_000,
    TIER_DEPENDENT: 50_000,
    TIER_SPOUSE: 50_000,
    TIER_COACH_ONLY: 0,
    TIER_COACH: 0,
}

# Ordering for upgrade detection (higher = better paid client tier)
_TIER_RANK = {
    TIER_TRIAL: 0,
    TIER_COACH_ONLY: 0,
    TIER_DEPENDENT: 1,
    TIER_SPOUSE: 1,
    TIER_STANDARD: 2,
    TIER_TOP_TIER: 3,
    TIER_COACH: 4,
}


def normalize_tier(raw: str | None) -> str:
    """Map any known alias to canonical users.tier value; default TRIAL."""
    if not raw:
        return TIER_TRIAL
    key = str(raw).upper().strip()
    long = TIER_LONG_PLAN_ALIASES.get(key)
    if long:
        return long
    if key.startswith("DEPENDENT_UNDER_"):
        return TIER_DEPENDENT
    if key.startswith("SPOUSE_UNDER_"):
        return TIER_SPOUSE
    return TIER_ALIASES.get(key, TIER_TRIAL)


def tier_rank(tier: str | None) -> int:
    """Higher means more privileged paid tier for CLIENT upgrades."""
    t = normalize_tier(tier)
    return _TIER_RANK.get(t, 0)


def monthly_cap_tokens(tier: str | None) -> int:
    """Subscription bucket ceiling for invoice.paid top-up (Option C)."""
    t = normalize_tier(tier)
    return int(TIER_MONTHLY_TOKENS.get(t, 0))


def initial_grant_tokens(tier: str | None) -> int:
    """Lump-sum subscription tokens for tier assignment."""
    t = normalize_tier(tier)
    return int(TIER_INITIAL_TOKENS.get(t, TIER_INITIAL_TOKENS[TIER_TRIAL]))


def is_paid_subscription_tier(tier: str | None) -> bool:
    t = normalize_tier(tier)
    return t in (TIER_STANDARD, TIER_TOP_TIER)


def can_access_nate(tier: str | None) -> bool:
    """COACH_ONLY cannot reach Nate; every other client plan can."""
    raw = str(tier or "").upper().strip()
    if raw == TIER_COACH_ONLY or normalize_tier(tier) == TIER_COACH_ONLY:
        return False
    return True


def session_plan_bucket(plan: str | None) -> str:
    """IC / SC / NONE for session-charge discounts (family dependents included)."""
    raw = str(plan or "").upper()
    if "SOVEREIGN" in raw or "TOP_TIER" in raw or raw == "TOP":
        return "SC"
    if "INNER" in raw or "CHAMBER" in raw or "STANDARD" in raw:
        return "IC"
    t = normalize_tier(plan)
    if t == TIER_TOP_TIER:
        return "SC"
    if t == TIER_STANDARD:
        return "IC"
    return "NONE"
