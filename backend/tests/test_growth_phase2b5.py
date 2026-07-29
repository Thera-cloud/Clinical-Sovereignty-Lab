"""Phase 2b + Phase 5 Adaptive Growth Engine offline unit tests.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

from app.services.growth.crystal_bridge import harvest_marketing_insight, reject_reason
from app.services.growth.demand_prior import compute_demand_prior_from_themes
from app.websocket.cli_task_bus import GROWTH_TASK_KINDS


def test_demand_prior_default_when_no_themes():
    assert compute_demand_prior_from_themes("anxiety coaching", []) == 1.0


def test_demand_prior_clamped_and_matches():
    themes = [
        {"theme": "anxiety_presence", "total": 100},
        {"theme": "sleep_rhythm", "total": 10},
        {"theme": "ops_only", "total": 999},
    ]
    hi = compute_demand_prior_from_themes("anxiety coaching presence", themes)
    lo = compute_demand_prior_from_themes("unrelated widgets", themes)
    assert 1.0 <= hi <= 1.5
    assert hi > lo
    assert lo == 1.0
    assert hi == 1.5  # full match on max theme


def test_crystal_bridge_rejects_try_and_crisis():
    assert reject_reason("x" * 50, "public_trial_merge") == "denied_source"
    assert reject_reason("I want to die tomorrow " + ("x" * 40), "skyeye_activity") == "crisis"
    assert reject_reason("reach me at test@example.com " + ("x" * 40), "bwas_weekly") == "pii"
    assert reject_reason("short", "skyeye_activity") == "too_short"
    assert reject_reason("Measured engagement rose on LinkedIn posts this week.", "skyeye_activity") is None


def test_crystal_bridge_harvest_no_crystallizer():
    out = harvest_marketing_insight(
        None,
        text="Measured engagement rose on LinkedIn posts this week with real metrics.",
        source="skyeye_activity",
    )
    assert out["ok"] is False
    assert out["rejected"] == "no_crystallizer"


def test_growth_task_kinds_registered():
    assert "growth_policy_cross_review" in GROWTH_TASK_KINDS
    assert "growth_weekly_digest" in GROWTH_TASK_KINDS
    assert "growth_segment_propose" in GROWTH_TASK_KINDS
    assert "growth_experiment_conclude" in GROWTH_TASK_KINDS
    assert len(GROWTH_TASK_KINDS) == 4
