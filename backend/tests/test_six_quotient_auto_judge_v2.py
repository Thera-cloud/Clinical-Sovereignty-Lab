"""Offline: grok-judge-v3 prompt anchors (no LLM / numpy package import)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_JUDGE = _ROOT / "app" / "services" / "six_quotient_auto_judge.py"


def _load():
    spec = importlib.util.spec_from_file_location("sq_auto_judge_v3", _JUDGE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_judge_v3_default_and_anchors():
    m = _load()
    assert m.DEFAULT_EVALUATOR == "grok-judge-v3"
    p = m.JUDGE_SYSTEM_PROMPT_V3
    assert "escalate_or_safety" in p
    assert "UNSOUND-ACT VETO" in p or "unsound-act" in p.lower()
    assert "fabricated fact or name" in p
    assert "persona-name" in p
    assert "THREE INDEPENDENT" in p or "INDEPENDENT" in p
    assert "Coupling:" not in p
    assert "primary≤1 then accuracy" not in p
    assert "presence_silence_ok" in p
    assert "refusal_or_frame_hold" in p
    assert "degraded_distractor" in p
    assert "degraded_distractor: bool = False" in _JUDGE.read_text(encoding="utf-8")


def test_judge_module_uses_v3_prompt_constant():
    src = _JUDGE.read_text(encoding="utf-8")
    assert "JUDGE_SYSTEM_PROMPT_V3" in src
    assert "system = JUDGE_SYSTEM_PROMPT_V3" in src
    assert "REMOVED primary↔accuracy coupling" in src or "REMOVED primary" in src


def test_tier1_score_floors_no_accuracy_coupling():
    """v3: primary≤1 must NOT clamp accuracy (human gold falsified coupling)."""
    m = _load()
    out = m.apply_tier1_score_floors(
        1, 3, 2, rubric_focus="therapeutic_engage", degraded_distractor=False
    )
    assert out["primary"] == 1
    assert out["accuracy"] == 3  # free — no coupling
    assert out["naturalness"] == 2
    # Decoupled cell humans use: pri=1 acc=0 must be preservable
    split = m.apply_tier1_score_floors(
        1, 0, 1, rubric_focus="therapeutic_engage", degraded_distractor=False
    )
    assert split == {"primary": 1, "accuracy": 0, "naturalness": 1}
    deg = m.apply_tier1_score_floors(
        2, 2, 3, rubric_focus="escalate_or_safety", degraded_distractor=True
    )
    assert deg["primary"] == 0 and deg["accuracy"] == 0
    assert deg["naturalness"] <= 1
