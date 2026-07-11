"""Phase 5c forward reasoning seam tests — offline."""

import os

import pytest

from app.services.nate_forward_reasoning import (
    build_forward_constraints,
    format_constraints_for_prompt,
)


@pytest.mark.asyncio
async def test_pacing_constraints_not_diagnosis():
    os.environ["ENABLE_FORWARD_REASONING"] = "true"
    constraints = await build_forward_constraints(
        None,
        username="client1",
        state_symbol={"distress_present": True},
        profile={"tier": "STANDARD", "profile_data": {}},
    )
    assert constraints
    text = format_constraints_for_prompt(constraints).lower()
    assert "diagnos" not in text
    assert "slow_pacing" in text or "witness" in text


@pytest.mark.asyncio
async def test_trial_excluded_returns_empty():
    os.environ["ENABLE_FORWARD_REASONING"] = "true"
    constraints = await build_forward_constraints(
        None,
        username="trial1",
        profile={"tier": "public_trial", "profile_data": {"public_trial": True}},
    )
    assert constraints == []


@pytest.mark.asyncio
async def test_disabled_flag_returns_empty():
    os.environ["ENABLE_FORWARD_REASONING"] = "false"
    constraints = await build_forward_constraints(
        None,
        username="client1",
        state_symbol={"distress_present": True},
        profile={"tier": "STANDARD"},
    )
    assert constraints == []
