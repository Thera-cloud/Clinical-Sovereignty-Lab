"""Phase 2 Adaptive Growth Engine offline unit tests.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

from app.services.growth.brand_checklist import run_brand_checklist
from app.services.growth.keyword_queue import compute_priority_score
from app.services.growth.skyeye_handoff import _clip_for_platform


def test_priority_formula_weights():
    score = compute_priority_score(
        volume_norm=1.0,
        intent=1.0,
        audience_value=1.0,
        buyer_prior=1.0,
        demand_prior=1.0,
        weights={
            "volume_norm": 0.30,
            "intent": 0.25,
            "audience_value": 0.25,
            "buyer_prior": 0.20,
        },
    )
    assert abs(score - 1.0) < 1e-6


def test_priority_demand_prior_bound():
    # Phase 2b lever — v1 keeps 1.0; bound still enforced.
    lo = compute_priority_score(
        volume_norm=1, intent=0, audience_value=0, buyer_prior=0, demand_prior=0.5
    )
    hi = compute_priority_score(
        volume_norm=1, intent=0, audience_value=0, buyer_prior=0, demand_prior=9.0
    )
    base = compute_priority_score(
        volume_norm=1, intent=0, audience_value=0, buyer_prior=0, demand_prior=1.0
    )
    assert abs(lo - base) < 1e-6  # clamped to min 1.0
    assert abs(hi - base * 1.5) < 1e-6


def test_brand_checklist_blocks_diagnosis_and_stats():
    bad = run_brand_checklist(
        "Cure anxiety",
        "We diagnose PTSD and 87% of patients improve overnight.",
    )
    assert not bad["passed"]
    assert "diagnosis_claim" in bad["fails"] or "outcome_claim" in bad["fails"]
    assert "fabricated_stat" in bad["fails"]


def test_brand_checklist_requires_ymyl_on_long_body():
    body = ("Practice presence. " * 40).strip()
    result = run_brand_checklist("Steady coaching", body)
    assert not result["passed"]
    assert "missing_ymyl_footer" in result["fails"]


def test_brand_checklist_passes_safe_article():
    body = (
        "Coaches help clients name what is happening without pretending certainty.\n\n"
        "---\n"
        "This article is educational and not a substitute for professional care. "
        "If you or someone you love is in crisis, call or text 988."
    )
    result = run_brand_checklist("Presence over slogans", body)
    assert result["passed"]
    assert result["ymyl_footer"] is True


def test_skyeye_clip_limits():
    title = "Hello"
    body = "x" * 5000
    assert len(_clip_for_platform("x", title, body)) <= 260
    assert len(_clip_for_platform("linkedin", title, body)) <= 2800
