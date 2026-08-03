"""Offline: grok-judge-v6 freeze invariants (TRUST_LEDGER Entry 12 path).

v6 freezes BEFORE dose-response v2 held-out contact. These tests assert
prompt structure only — no LLM call, no v2 response text in the prompt.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_JUDGE = _ROOT / "app" / "services" / "six_quotient_auto_judge.py"


def _load():
    spec = importlib.util.spec_from_file_location("sq_auto_judge_v6", _JUDGE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_default_evaluator_remains_v5():
    m = _load()
    assert m.DEFAULT_EVALUATOR == "grok-judge-v5"


def test_v6_has_grid_then_scalars():
    p = _load().JUDGE_SYSTEM_PROMPT_V6
    assert "GRID-THEN-SCALARS" in p
    assert '"moves"' in p or "moves" in p


def test_v6_embeds_full_range_anchors():
    p = _load().JUDGE_SYSTEM_PROMPT_V6
    assert "FULL-RANGE CALIBRATION ANCHORS" in p
    assert "gold-AQ-1" in p
    assert "gold-AQ-fail" in p
    assert "gold-SQ-1" in p


def test_v6_retains_mechanism_b_no_literal_988_bug():
    p = _load().JUDGE_SYSTEM_PROMPT_V6
    assert "988/coach/emergency" not in p
    assert "EXPLICIT" in p
    assert "NOT escalation" in p


def test_v6_does_not_contain_dose_response_v2_pack_text():
    """Burn discipline: freeze must not paste the third held-out into the prompt."""
    p = _load().JUDGE_SYSTEM_PROMPT_V6
    assert "after_must_sequence_pack" not in p
    assert "dose_response_v2_must_sequence" not in p
    assert "Let's bring in the coach right now for immediate support" not in p
    assert "stage 3 pancreatic cancer" not in p


def test_v6_differs_from_v5():
    m = _load()
    assert m.JUDGE_SYSTEM_PROMPT_V6 != m.JUDGE_SYSTEM_PROMPT_V5
