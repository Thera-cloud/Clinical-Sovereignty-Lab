"""Offline: grok-judge-v2 prompt anchors (no LLM / numpy package import)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_JUDGE = _ROOT / "app" / "services" / "six_quotient_auto_judge.py"


def _load():
    spec = importlib.util.spec_from_file_location("sq_auto_judge_v2", _JUDGE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_judge_v2_default_and_anchors():
    m = _load()
    assert m.DEFAULT_EVALUATOR == "grok-judge-v2"
    p = m.JUDGE_SYSTEM_PROMPT_V2
    assert "escalate_or_safety" in p
    assert "primary≤1" in p or "primary<=1" in p
    assert "STRICT" in p
    assert "presence_silence_ok" in p
    assert "refusal_or_frame_hold" in p


def test_judge_module_uses_v2_prompt_constant():
    src = _JUDGE.read_text(encoding="utf-8")
    assert "JUDGE_SYSTEM_PROMPT_V2" in src
    assert "system = JUDGE_SYSTEM_PROMPT_V2" in src
