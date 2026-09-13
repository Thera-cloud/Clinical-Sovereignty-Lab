"""Fear/shame inquiry protocol: depth without covert manipulation."""

from __future__ import annotations

import pytest

from app.services.protective_affect_inquiry import (
    build_inquiry_block,
    classify_protective_affect,
    compassionate_fallback,
    response_violations,
)
from app.services.therapeutic_controller import (
    _audit_violations,
    audit_therapeutic_response,
    prepare_therapeutic_context,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The old fear came back when I considered the goal.", "fear"),
        ("I feel ashamed and want to hide.", "shame"),
        ("I am scared and ashamed of what happened.", "fear_and_shame"),
        ("I want to plan my week and choose a goal.", None),
    ],
)
def test_classifies_explicit_protective_affect(text: str, expected: str | None) -> None:
    assert classify_protective_affect(text) == expected


def test_protocol_requires_natural_non_deceptive_inquiry() -> None:
    block = build_inquiry_block("fear")
    assert "Ask ONE natural" in block
    assert "NEVER use covert persuasion" in block
    assert "do not claim to know the hidden motive" in block.lower()


def test_solution_takeover_from_smoke_test_fails_contract() -> None:
    response = (
        "One possibility is that the fear is connected to feeling overwhelmed. "
        "Try to break the action down and set a specific time for the walk. "
        "Which possibility resonates with you?"
    )
    violations = response_violations(response, "fear")
    assert "protective_affect_solution_takeover" in violations
    assert "protective_affect_depth_missing" in violations


def test_one_compassionate_depth_question_passes_contract() -> None:
    response = (
        "We can keep the goal in view without pushing toward it. What might the "
        "fear be protecting that also points toward something you deeply want? "
        "Whatever appears can stay here without being judged or rushed."
    )
    assert response_violations(response, "fear") == []


@pytest.mark.asyncio
async def test_faster_preflight_injects_affect_protocol_and_metadata() -> None:
    pack = await prepare_therapeutic_context(
        user_text=(
            "Thinking about taking that action brings the old fear back. Can we "
            "slow down without losing sight of the goal?"
        ),
        user_id="audit_client",
        db_pool=None,
        base_system_prompt="You are Nate.",
        default_max_tokens=600,
        depth_mode="faster",
    )
    assert "PROTECTIVE AFFECT INQUIRY — FEAR" in pack["enriched_system_prompt"]
    assert pack["audit_metadata"]["protective_affect_kind"] == "fear"


@pytest.mark.asyncio
async def test_crisis_stabilization_suppresses_depth_protocol() -> None:
    pack = await prepare_therapeutic_context(
        user_text="I am afraid I will kill myself tonight.",
        user_id="audit_client",
        db_pool=None,
        base_system_prompt="You are Nate.",
        default_max_tokens=600,
        depth_mode="faster",
    )
    assert "PROTECTIVE AFFECT INQUIRY" not in pack["enriched_system_prompt"]
    assert pack["audit_metadata"]["protective_affect_kind"] is None
    assert pack["audit_metadata"]["crisis_exempt"] is True


def test_controller_audit_enforces_affect_depth() -> None:
    meta = {
        "locale": "en-US",
        "autonomic_state": "in_window",
        "max_tokens": 600,
        "protective_affect_kind": "fear",
        "direct_action_request_kind": None,
        "crisis_exempt": False,
        "user_text_for_audit": "The old fear is back.",
    }
    bad = "Break the goal down into smaller steps and try again tomorrow."
    violations = _audit_violations(bad, meta, [])
    assert "protective_affect_inquiry_missing" in violations
    assert "protective_affect_solution_takeover" in violations


@pytest.mark.asyncio
async def test_controller_uses_compassionate_fallback_on_miss() -> None:
    meta = {
        "locale": "en-US",
        "autonomic_state": "in_window",
        "max_tokens": 600,
        "mismatch_available": False,
        "dissociation_delta": None,
        "coercion_severity": None,
        "novelty_threshold": 0.30,
        "thalamic_gate_forced": False,
        "protective_affect_kind": "shame",
        "direct_action_request_kind": None,
        "crisis_exempt": False,
        "user_text_for_audit": "I feel ashamed.",
    }
    out = await audit_therapeutic_response(
        response_text="Here are three ways to stop feeling ashamed.",
        audit_metadata=meta,
        user_id="audit_client",
        db_pool=None,
    )
    assert out["response_text"] == compassionate_fallback("shame")
    assert "what do you wish" in out["response_text"].lower()
