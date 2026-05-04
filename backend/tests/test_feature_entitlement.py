"""Unit tests for family feature entitlement (non-billing)."""

from app.constants import tiers as tier_c
from app.websocket.feature_entitlement import effective_feature_tier, resolve_feature_entitlement


def _reg_entry(profile: dict) -> dict:
    return {"profile": profile}


def test_effective_no_family_top_payer():
    reg = {}
    p = {"role": "CLIENT", "tier": "TOP_TIER", "subscription_plan": "TOP_TIER"}
    assert effective_feature_tier(p, reg) == "TOP_TIER"


def test_dependent_inherits_sovereign_head():
    reg = {
        "k_head": _reg_entry(
            {
                "username": "head1",
                "hardware_id": "H_HEAD",
                "family_id": "F1",
                "family_role": "HEAD",
                "tier": "TOP",
                "subscription_plan": "TOP_TIER",
            }
        ),
        "k_dep": _reg_entry(
            {
                "username": "dep1",
                "hardware_id": "H_DEP",
                "family_id": "F1",
                "tier": "DEPENDENT",
                "subscription_plan": "DEPENDENT_UNDER_SOVEREIGN_CIRCLE",
            }
        ),
    }
    dep = reg["k_dep"]["profile"]
    assert effective_feature_tier(dep, reg) == "TOP_TIER"
    band, own_r, mx, head = resolve_feature_entitlement(dep, reg)
    assert band == "TOP_TIER"
    assert head is not None
    assert head["username"] == "head1"
    assert mx > own_r


def test_dependent_inner_chamber_head_no_sanctuary_band():
    reg = {
        "k_head": _reg_entry(
            {
                "username": "head2",
                "hardware_id": "H2",
                "family_id": "F2",
                "family_role": "HEAD",
                "tier": "STANDARD",
                "subscription_plan": "STANDARD",
            }
        ),
        "k_dep": _reg_entry(
            {
                "username": "dep2",
                "hardware_id": "H2D",
                "family_id": "F2",
                "tier": "DEPENDENT",
                "subscription_plan": "DEPENDENT_UNDER_INNER_CHAMBER",
            }
        ),
    }
    dep = reg["k_dep"]["profile"]
    assert effective_feature_tier(dep, reg) == "STANDARD"


def test_max_own_top_overrides_inner_head():
    reg = {
        "k_head": _reg_entry(
            {
                "username": "head3",
                "hardware_id": "H3",
                "family_id": "F3",
                "family_role": "HEAD",
                "tier": "STANDARD",
                "subscription_plan": "STANDARD",
            }
        ),
        "k_mem": _reg_entry(
            {
                "username": "mem3",
                "hardware_id": "H3M",
                "family_id": "F3",
                "tier": "TOP_TIER",
                "subscription_plan": "TOP_TIER",
            }
        ),
    }
    mem = reg["k_mem"]["profile"]
    assert effective_feature_tier(mem, reg) == "TOP_TIER"


def test_coach_skips_family_inheritance():
    reg = {
        "any": _reg_entry(
            {
                "username": "headz",
                "hardware_id": "HZ",
                "family_id": "FZ",
                "tier": "TOP_TIER",
                "subscription_plan": "TOP_TIER",
            }
        ),
    }
    coach = {
        "role": "COACH",
        "username": "coach1",
        "tier": "TRIAL",
        "subscription_plan": "TRIAL",
        "family_id": "FZ",
    }
    assert effective_feature_tier(coach, reg) == "TRIAL"


def test_long_plan_aliases_normalize_to_billing_buckets():
    assert tier_c.normalize_tier("DEPENDENT_UNDER_SOVEREIGN_CIRCLE") == tier_c.TIER_DEPENDENT
    assert tier_c.normalize_tier("SPOUSE_UNDER_INNER_CHAMBER") == tier_c.TIER_SPOUSE


def test_surrogate_head_when_no_explicit_head():
    reg = {
        "a": _reg_entry(
            {
                "username": "payer",
                "hardware_id": "HP",
                "family_id": "F4",
                "tier": "TOP_TIER",
                "subscription_plan": "TOP_TIER",
            }
        ),
        "b": _reg_entry(
            {
                "username": "kid",
                "hardware_id": "HK",
                "family_id": "F4",
                "tier": "DEPENDENT",
                "subscription_plan": "DEPENDENT_UNDER_SOVEREIGN_CIRCLE",
            }
        ),
    }
    kid = reg["b"]["profile"]
    assert effective_feature_tier(kid, reg) == "TOP_TIER"
