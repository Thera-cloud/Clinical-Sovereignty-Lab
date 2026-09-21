"""Offline: promo codes can target Coach Only, Inner Chamber, Sovereign Circle."""

from app.constants.tiers import (
    TIER_COACH_ONLY,
    TIER_STANDARD,
    TIER_TOP_TIER,
    canonicalize_promo_plan,
    normalize_promo_plans,
    promo_applies_to_plan,
)


def test_canonicalize_aliases():
    assert canonicalize_promo_plan("coach-only") is None
    assert canonicalize_promo_plan("COACH_ONLY") == TIER_COACH_ONLY
    assert canonicalize_promo_plan("INNER_CHAMBER") == TIER_STANDARD
    assert canonicalize_promo_plan("STANDARD") == TIER_STANDARD
    assert canonicalize_promo_plan("SOVEREIGN_CIRCLE") == TIER_TOP_TIER
    assert canonicalize_promo_plan("TOP_TIER") == TIER_TOP_TIER
    assert canonicalize_promo_plan("TRIAL") is None


def test_empty_applies_to_every_package():
    assert promo_applies_to_plan([], "STANDARD") is True
    assert promo_applies_to_plan(None, "TOP_TIER") is True
    assert promo_applies_to_plan([], "TRIAL") is True


def test_clergy_sovereign_only():
    allowed = ["TOP_TIER"]
    assert promo_applies_to_plan(allowed, "TOP_TIER") is True
    assert promo_applies_to_plan(allowed, "SOVEREIGN_CIRCLE") is True
    assert promo_applies_to_plan(allowed, "STANDARD") is False
    assert promo_applies_to_plan(allowed, "INNER_CHAMBER") is False
    assert promo_applies_to_plan(allowed, "COACH_ONLY") is False
    assert promo_applies_to_plan(allowed, "TRIAL") is False


def test_welcome20_inner_chamber_only():
    allowed = ["INNER_CHAMBER"]
    assert promo_applies_to_plan(allowed, "STANDARD") is True
    assert promo_applies_to_plan(allowed, "INNER_CHAMBER") is True
    assert promo_applies_to_plan(allowed, "TOP_TIER") is False
    assert promo_applies_to_plan(allowed, "COACH_ONLY") is False


def test_two_of_three():
    allowed = normalize_promo_plans(["COACH_ONLY", "SOVEREIGN_CIRCLE"])
    assert allowed == [TIER_COACH_ONLY, TIER_TOP_TIER]
    assert promo_applies_to_plan(allowed, "COACH_ONLY") is True
    assert promo_applies_to_plan(allowed, "TOP_TIER") is True
    assert promo_applies_to_plan(allowed, "STANDARD") is False


def test_all_three_excludes_trial():
    allowed = normalize_promo_plans(["COACH_ONLY", "STANDARD", "TOP_TIER"])
    assert promo_applies_to_plan(allowed, "COACH_ONLY") is True
    assert promo_applies_to_plan(allowed, "STANDARD") is True
    assert promo_applies_to_plan(allowed, "TOP_TIER") is True
    assert promo_applies_to_plan(allowed, "TRIAL") is False
