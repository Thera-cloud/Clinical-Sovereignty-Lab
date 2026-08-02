"""Offline tests for M4 (Phase M, R6 mirror) — BWAS provenance-weighted
scoring by verified stage. TRUST_LEDGER.md Entry 19.

Kept in its OWN test file, separate from test_phase_m_completion.py:
loading growth/bwas_worker.py in the same process as other Phase M
modules (growth_claims.py, growth/brand_checklist.py) was found to
deterministically trigger the local-Mac numpy SIGFPE (5/5 repro) even
though bwas_worker.py loads cleanly in complete isolation every time.
This is the documented, environment-specific, cross-import-order
floating-point trap noted throughout this test suite (see
test_ln7_structural_verifier_floor.py et al.) — not a defect in the code
under test.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bwas():
    return _load("app/services/growth/bwas_worker.py", "phase_m_bwas_isolated")


def test_verified_stage_counts_fully_regardless_of_attribution(bwas):
    # signup requires a real users-row side effect -- no discount even with
    # zero attribution_link_id coverage.
    score = bwas.provenance_weighted_stage_score(
        "signup", attributed_n=0, orphan_n=10, stage_weight=0.40
    )
    assert score == pytest.approx(0.40 * 10)


def test_active_client_stage_also_counts_fully(bwas):
    score = bwas.provenance_weighted_stage_score(
        "active_client", attributed_n=0, orphan_n=3, stage_weight=1.0
    )
    assert score == pytest.approx(3.0)


def test_unverified_stage_discounts_orphan_events(bwas):
    score = bwas.provenance_weighted_stage_score(
        "click", attributed_n=5, orphan_n=5, stage_weight=0.15,
        orphan_discount=0.5,
    )
    # 5 full-weight + 5 half-weight = 7.5 effective events
    assert score == pytest.approx(0.15 * 7.5)


def test_all_orphan_click_traffic_scores_lower_than_all_attributed(bwas):
    attributed_only = bwas.provenance_weighted_stage_score(
        "impression", attributed_n=100, orphan_n=0, stage_weight=0.05,
    )
    orphan_only = bwas.provenance_weighted_stage_score(
        "impression", attributed_n=0, orphan_n=100, stage_weight=0.05,
    )
    assert orphan_only < attributed_only


def test_zero_discount_config_disables_provenance_weighting(bwas):
    """orphan_discount=1.0 (via growth_config override) must reduce to the
    pre-M4 flat-count behavior -- config is a real off-switch, not cosmetic."""
    score = bwas.provenance_weighted_stage_score(
        "click", attributed_n=3, orphan_n=7, stage_weight=0.15,
        orphan_discount=1.0,
    )
    assert score == pytest.approx(0.15 * 10)


def test_full_discount_config_zeroes_out_orphan_contribution(bwas):
    score = bwas.provenance_weighted_stage_score(
        "click", attributed_n=3, orphan_n=7, stage_weight=0.15,
        orphan_discount=0.0,
    )
    assert score == pytest.approx(0.15 * 3)


def test_custom_verified_stages_override_default(bwas):
    """A caller-supplied verified_stages set (e.g. from growth_config
    bwas_provenance.verified_stages) must actually change which stages
    skip the discount, not just the default constant."""
    score = bwas.provenance_weighted_stage_score(
        "quiz_complete", attributed_n=0, orphan_n=10, stage_weight=0.25,
        orphan_discount=0.5,
        verified_stages=frozenset({"quiz_complete"}),
    )
    assert score == pytest.approx(0.25 * 10)  # no discount, in override set
    score_default = bwas.provenance_weighted_stage_score(
        "quiz_complete", attributed_n=0, orphan_n=10, stage_weight=0.25,
        orphan_discount=0.5,
    )
    assert score_default == pytest.approx(0.25 * 5)  # discounted, default set


def test_bwas_tick_uses_provenance_weighted_score(bwas):
    src = (_ROOT / "app" / "services" / "growth" / "bwas_worker.py").read_text(
        encoding="utf-8"
    )
    assert "provenance_weighted_stage_score(" in src
    assert "attribution_link_id IS NOT NULL" in src
    assert "attribution_link_id IS NULL" in src


def test_provenance_config_reads_growth_config_key_name(bwas):
    src = (_ROOT / "app" / "services" / "growth" / "bwas_worker.py").read_text(
        encoding="utf-8"
    )
    assert "bwas_provenance" in src
    assert "orphan_discount" in src


def test_lead_events_meta_still_strips_pii_no_regression():
    """M4's design explicitly does NOT reintroduce device/IP tracking into
    lead_events -- confirm the existing PII-stripping allowlist in
    lead_events.py is untouched by this pass. Duplicated from
    test_phase_m_completion.py deliberately -- this file must stand alone
    as a complete guard for the M4 change even if the other file is
    skipped/quarantined for the numpy issue."""
    src = (_ROOT / "app" / "services" / "growth" / "lead_events.py").read_text(
        encoding="utf-8"
    )
    for pii_key in ("device_id", "hardware_id", "ip", "email", "phone"):
        assert f'"{pii_key}"' in src
