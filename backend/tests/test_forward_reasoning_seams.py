"""Phase 5c forward reasoning seam tests — offline (all adversarial gates)."""

from __future__ import annotations

import os

import pytest

from app.services.nate_forward_reasoning import (
    _sanitize_constraints,
    build_forward_constraints,
    format_constraints_for_prompt,
)


@pytest.fixture(autouse=True)
def _reset_flag():
    prev = os.environ.get("ENABLE_FORWARD_REASONING")
    yield
    if prev is None:
        os.environ.pop("ENABLE_FORWARD_REASONING", None)
    else:
        os.environ["ENABLE_FORWARD_REASONING"] = prev


@pytest.mark.asyncio
async def test_key_constraints_carry_inspectable_fired_by():
    """Gate Key: every constraint has fired_by symbols."""
    os.environ["ENABLE_FORWARD_REASONING"] = "true"
    constraints = await build_forward_constraints(
        None,
        username="client1",
        state_symbol={"distress_present": True},
        profile={"tier": "STANDARD", "profile_data": {}},
    )
    assert constraints
    for c in constraints:
        assert c.get("fired_by"), c
        assert all(isinstance(x, str) and x for x in c["fired_by"])


@pytest.mark.asyncio
async def test_lifecycle_constraints_avoid_clinical_conclusions():
    """Gate Lifecycle: pacing only — no diagnosis language."""
    os.environ["ENABLE_FORWARD_REASONING"] = "true"
    constraints = await build_forward_constraints(
        None,
        username="client1",
        state_symbol={"distress_present": True},
        nevedal_snapshot={"c_emo": 0.2, "c_emo_trend": "declining", "shame_index": 0.7},
        profile={"tier": "STANDARD", "profile_data": {}},
    )
    assert constraints
    text = format_constraints_for_prompt(constraints).lower()
    assert "diagnos" not in text
    assert "disorder" not in text
    assert "icd-" not in text
    assert "slow_pacing" in text or "witness" in text
    assert "hold_space" in text
    assert "reduce_intensity" in text


def test_lifecycle_sanitize_strips_forbidden_instructions():
    cleaned = _sanitize_constraints(
        [
            {
                "type": "slow_pacing",
                "instruction": "This is a diagnosis of depression.",
                "fired_by": ["bad"],
            },
            {
                "type": "hold_space",
                "instruction": "Hold space gently.",
                "fired_by": ["ok"],
            },
            {
                "type": "not_allowed_type",
                "instruction": "Ignore me.",
                "fired_by": ["x"],
            },
        ]
    )
    assert len(cleaned) == 1
    assert cleaned[0]["type"] == "hold_space"


@pytest.mark.asyncio
async def test_surface_prompt_block_labeled_pacing_only():
    """Gate Surface: prompt header is pacing/focus only."""
    os.environ["ENABLE_FORWARD_REASONING"] = "true"
    constraints = await build_forward_constraints(
        None,
        username="client1",
        state_symbol={"distress_present": True},
        profile={"tier": "STANDARD"},
    )
    block = format_constraints_for_prompt(constraints)
    assert "FORWARD REASONING CONSTRAINTS" in block
    assert "pacing/focus only" in block.lower()
    assert "no clinical labels" in block.lower()


@pytest.mark.asyncio
async def test_seam_public_trial_excluded():
    """Gate Seam: public_trial profiles get no constraints."""
    os.environ["ENABLE_FORWARD_REASONING"] = "true"
    by_tier = await build_forward_constraints(
        None,
        username="trial1",
        state_symbol={"distress_present": True},
        profile={"tier": "public_trial", "profile_data": {}},
    )
    by_flag = await build_forward_constraints(
        None,
        username="trial2",
        state_symbol={"distress_present": True},
        profile={"tier": "STANDARD", "profile_data": {"public_trial": True}},
    )
    assert by_tier == []
    assert by_flag == []


@pytest.mark.asyncio
async def test_time_metrics_use_latest_nevedal_row_only():
    """Gate Time: crisis_perception from latest biometrics row only."""
    os.environ["ENABLE_FORWARD_REASONING"] = "true"
    queries = []

    class _Conn:
        async def fetchval(self, sql, *args):
            queries.append(sql)
            return "00000000-0000-0000-0000-000000000001"

        async def fetchrow(self, sql, *args):
            queries.append(sql)
            return {
                "c_emo": 0.5,
                "biometrics": {"crisis_perception": {"type": "elevated"}},
            }

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Pool:
        def acquire(self):
            return _Conn()

    constraints = await build_forward_constraints(
        _Pool(),
        username="client1",
        hardware_id="CLIENT_001",
        state_symbol={},
        profile={"tier": "STANDARD"},
    )
    assert any("nevedal_metrics" in q.lower() for q in queries)
    metrics_sql = next(q for q in queries if "nevedal_metrics" in q.lower())
    sql = " ".join(metrics_sql.lower().split())
    assert "order by recorded_at desc" in sql
    assert "limit 1" in sql
    assert "biometrics" in sql
    assert any(
        "crisis_perception" in str(c.get("fired_by")) for c in constraints
    )


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


@pytest.mark.asyncio
async def test_pacing_constraints_not_diagnosis():
    """Legacy alias — distress → slow_pacing / witness, never diagnosis."""
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
