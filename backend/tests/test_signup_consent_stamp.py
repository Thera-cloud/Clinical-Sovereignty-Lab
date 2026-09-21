"""Offline: paid signup stamps live covenant and CHECK-safe users.tier."""
from app.constants.consent import REQUIRED_CONSENT_VERSION, stamp_signup_consent
from app.constants.tiers import (
    TIER_COACH,
    TIER_COACH_ONLY,
    TIER_SPOUSE,
    TIER_STANDARD,
    TIER_TOP_TIER,
    TIER_TRIAL,
    users_tier_column,
)


def test_stamp_signup_consent_upgrades_stale_default():
    assert stamp_signup_consent(None) == REQUIRED_CONSENT_VERSION
    assert stamp_signup_consent("") == REQUIRED_CONSENT_VERSION
    assert stamp_signup_consent("v13.0_2026") == REQUIRED_CONSENT_VERSION
    assert stamp_signup_consent("v13.1_2026") == "v13.1_2026"
    assert REQUIRED_CONSENT_VERSION == "v13.1_2026"


def test_users_tier_column_maps_plan_only_labels():
    assert users_tier_column(TIER_COACH_ONLY) == TIER_STANDARD
    assert users_tier_column(TIER_COACH) == TIER_STANDARD
    assert users_tier_column(TIER_SPOUSE) == TIER_STANDARD
    assert users_tier_column(TIER_TOP_TIER) == TIER_TOP_TIER
    assert users_tier_column(TIER_TRIAL) == TIER_TRIAL
    assert users_tier_column("INNER_CHAMBER") == TIER_STANDARD
    assert users_tier_column("SOVEREIGN_CIRCLE") == TIER_TOP_TIER
