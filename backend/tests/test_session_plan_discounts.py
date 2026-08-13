"""Offline: membership session discounts + Coach Only upgrade token floors."""

from app.constants.tiers import (
    TIER_COACH_ONLY,
    TIER_STANDARD,
    TIER_TOP_TIER,
    can_access_nate,
    initial_grant_tokens,
    session_plan_bucket,
)
from app.services.session_booking_billing import (
    billed_session_cents,
    session_discount_cents,
)


def test_coach_only_cannot_access_nate():
    assert can_access_nate("COACH_ONLY") is False
    assert can_access_nate("STANDARD") is True
    assert can_access_nate("TOP_TIER") is True


def test_upgrade_token_floors():
    assert initial_grant_tokens(TIER_COACH_ONLY) == 0
    assert initial_grant_tokens(TIER_STANDARD) == 50_000
    assert initial_grant_tokens("INNER_CHAMBER") == 50_000
    assert initial_grant_tokens(TIER_TOP_TIER) == 200_000
    assert initial_grant_tokens("SOVEREIGN_CIRCLE") == 200_000


def test_session_plan_bucket_includes_family_dependents():
    assert session_plan_bucket("COACH_ONLY") == "NONE"
    assert session_plan_bucket("STANDARD") == "IC"
    assert session_plan_bucket("INNER_CHAMBER") == "IC"
    assert session_plan_bucket("DEPENDENT_UNDER_INNER_CHAMBER") == "IC"
    assert session_plan_bucket("TOP_TIER") == "SC"
    assert session_plan_bucket("SOVEREIGN_CIRCLE") == "SC"
    assert session_plan_bucket("DEPENDENT_UNDER_SOVEREIGN_CIRCLE") == "SC"
    assert session_plan_bucket("SPOUSE_UNDER_SOVEREIGN_CIRCLE") == "SC"


def test_coachn_inner_chamber_every_session_is_125():
    listed = 175
    disc = session_discount_cents("STANDARD", 0)
    assert billed_session_cents(listed, disc) == 12500
    disc2 = session_discount_cents("STANDARD", 4)
    assert billed_session_cents(listed, disc2) == 12500


def test_coachn_sovereign_circle_first_125_then_90():
    listed = 175
    first = session_discount_cents("TOP_TIER", 0)
    assert billed_session_cents(listed, first) == 12500
    extra = session_discount_cents("TOP_TIER", 1)
    assert billed_session_cents(listed, extra) == 9000
    extra2 = session_discount_cents("DEPENDENT_UNDER_SOVEREIGN_CIRCLE", 2)
    assert billed_session_cents(listed, extra2) == 9000


def test_coach_only_pays_full_coach_rate():
    disc = session_discount_cents("COACH_ONLY", 0)
    assert disc == 0
    assert billed_session_cents(175, disc) == 17500
