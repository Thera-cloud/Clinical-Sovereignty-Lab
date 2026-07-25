"""Dual-track gold: harness vs live_stack provenance + DELTA quote ban."""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_FILL = _ROOT / "scripts" / "fill_human_gold_nate_responses.py"
_LIVE = _ROOT / "app" / "services" / "live_stack_blinds.py"
_MIG = _ROOT / "migrations" / "278_gold_dual_track_provenance.sql"
_API = _ROOT / "app" / "routers" / "principal_review_api.py"
_CTRL = _ROOT / "app" / "services" / "therapeutic_controller.py"
_POLICY = _ROOT / "app" / "services" / "principal_review_crisis_policy.py"


def test_migration_278_dual_track_columns():
    src = _MIG.read_text(encoding="utf-8")
    assert "nate_response_live" in src
    assert "live_stack_attempt" in src
    assert "harness_thin_inference" in src
    assert "nate_genuine_attempt" in src  # relabel FROM


def test_harness_writes_thin_provenance():
    src = _FILL.read_text(encoding="utf-8")
    assert "harness_thin_inference" in src
    assert "response_provenance = 'nate_genuine_attempt'" not in src
    assert "first person" in src.lower()


def test_live_stack_service_and_api():
    assert _LIVE.is_file()
    live = _LIVE.read_text(encoding="utf-8")
    assert "prepare_therapeutic_context" in live
    assert "live_stack_attempt" in live
    api = _API.read_text(encoding="utf-8")
    assert "/gold/live-stack/generate" in api
    assert "classify_failure_class" in api
    assert 'track_norm == "live"' in api
    assert "live_human_scored" in api
    assert "/gold/live-stack/compare" in api


def test_migration_279_live_scores():
    mig = (_ROOT / "migrations" / "279_live_track_scores.sql").read_text(encoding="utf-8")
    assert "live_primary_score" in mig
    assert "live_human_scored" in mig


def test_controller_rp_symbolic_law():
    src = _CTRL.read_text(encoding="utf-8")
    assert "symbolic_third_person_rp" in src
    assert "_RP_NARRATION_RE" in src


def test_delta_failure_class_in_source():
    """Avoid importing policy (numpy via app.services); assert contract in source."""
    src = _POLICY.read_text(encoding="utf-8")
    assert "classify_failure_class" in src
    assert "Failed class (do not reproduce)" in src
    assert "Failed move (blind Nate)" not in src
    assert "third_person_rp_narration" in src


def test_scripts_parse():
    for p in (_FILL, _ROOT / "scripts" / "generate_live_stack_blinds.py"):
        assert ast.parse(p.read_text(encoding="utf-8")) is not None
