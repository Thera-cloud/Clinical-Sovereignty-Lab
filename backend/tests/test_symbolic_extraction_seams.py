"""Phase 5a symbolic extraction seam tests — offline."""

import pytest

from app.services.nate_commitment_extractor import (
    build_state_symbol,
    classify_sensitivity,
    heuristic_prefilter,
    validate_commitment_symbol,
)


def test_heuristic_prefilter_requires_temporal_and_intent():
    assert heuristic_prefilter("I'm going to therapy next Tuesday") is True
    assert heuristic_prefilter("hello") is False


def test_schema_rejects_partial_commitment():
    assert validate_commitment_symbol({"text": "x"}) is None
    assert validate_commitment_symbol({"text": "valid plan", "type": "bogus"}) is None
    sym = validate_commitment_symbol(
        {"text": "Practice breathing daily", "type": "practice_goal", "sensitivity": "routine"}
    )
    assert sym is not None
    assert sym.type == "practice_goal"


def test_sensitivity_deterministic_from_bridge_markers():
    assert classify_sensitivity("I was abused as a child") == "sensitive"
    assert classify_sensitivity("I'll walk tomorrow") == "routine"


def test_state_symbol_distress_from_audit_metadata():
    state = build_state_symbol(
        "I'm panicking",
        audit_metadata={"distress_present": True, "tmc_class": "crisis"},
    )
    assert state.distress_present is True
    assert state.emotional_valence == "distressed"


@pytest.mark.asyncio
async def test_trial_exclusion_no_username_short_circuits_extract(monkeypatch):
    monkeypatch.setenv("ENABLE_PROACTIVE_COMMITMENTS", "true")
    from app.services.nate_commitment_extractor import extract_commitment_candidate

    result = await extract_commitment_candidate(
        None,
        username=None,
        hardware_id="anon_hash",
        user_text="I'm planning to call my coach tomorrow",
    )
    assert result is None
