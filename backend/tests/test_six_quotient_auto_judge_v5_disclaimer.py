"""Offline: grok-judge-v5 uncertified-quality disclaimer (TRUST_LEDGER.md Entry 12).

CEO flag decision 2026-08-02: v5 is certified ONLY as a safety-veto
screener (fresh held-out kappa=0.189, n=40, fails the pre-registered 0.70
quality threshold; safety veto is 0-for-49 across both held-out runs).
Condition 2 of that decision: every judge output must carry an
uncertified-quality disclaimer so no downstream consumer (dashboards,
six_quotient ability/theta tracking, exports) quietly treats
primary/accuracy/naturalness as a certified signal.

No LLM call, no numpy-triggering package import — a fake app_state /
router stands in for the real inference call (importlib.util direct
file load, matching test_six_quotient_auto_judge_v5.py's pattern).
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_JUDGE = _ROOT / "app" / "services" / "six_quotient_auto_judge.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "sq_auto_judge_v5_disclaimer", _JUDGE
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class _FakeRouter:
    def __init__(self, payload):
        self._payload = payload

    async def generate(self, **kwargs):
        return {"text": json.dumps(self._payload)}


class _FakeAppState:
    def __init__(self, router):
        self.nate_inference_router = router


def test_disclaimer_constants_declare_uncertified_screener_only():
    m = _load()
    assert m.JUDGE_QUALITY_CERTIFIED is False
    assert m.JUDGE_ROLE == "safety_veto_screener_only"


@pytest.mark.asyncio
async def test_llm_judge_output_carries_disclaimer_fields():
    m = _load()
    app_state = _FakeAppState(
        _FakeRouter({"primary": 2, "accuracy": 2, "naturalness": 2, "notes": "none"})
    )
    result = await m._llm_judge(
        app_state,
        scenario_id="EQ-1::live",
        section="EQ",
        rubric_focus="therapeutic_engage",
        client_says="test",
        response="a reasonably long clinical response for scoring purposes",
    )
    assert result is not None
    # Real scalars still present and unaffected
    assert result["primary"] == 2
    assert result["accuracy"] == 2
    assert result["naturalness"] == 2
    # Entry 12 disclaimer, structurally attached, not just documented
    assert result["quality_certified"] is False
    assert result["role"] == "safety_veto_screener_only"


@pytest.mark.asyncio
async def test_llm_judge_disclaimer_present_even_on_degraded_distractor_floor(loop=None):
    """Floors (apply_tier1_score_floors) rewrite the scalars but must not
    strip the disclaimer fields added after flooring."""
    m = _load()
    app_state = _FakeAppState(
        _FakeRouter({"primary": 3, "accuracy": 3, "naturalness": 3, "notes": "n/a"})
    )
    result = await m._llm_judge(
        app_state,
        scenario_id="SQ-4",
        section="SQ",
        rubric_focus="escalate_or_safety",
        client_says="test",
        response="short",
        degraded_distractor=True,
    )
    assert result is not None
    # Floor forces primary/accuracy to 0 on a degraded distractor
    assert result["primary"] == 0
    assert result["accuracy"] == 0
    assert result["quality_certified"] is False
    assert result["role"] == "safety_veto_screener_only"
