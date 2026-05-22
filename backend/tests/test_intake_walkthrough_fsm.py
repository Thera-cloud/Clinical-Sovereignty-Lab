"""Intake walkthrough FSM regression tests."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.intake_questions import SECTION1_FIELDS
from app.services import intake_walkthrough as iw

TRANSCRIPT_TURNS = [
    "Let's talk about my journey today",
    "later",
    "Focus on my journey",
    "give me tools for communication",
    "Do the intake questions later as I mentioned",
    "pause",
    "stop it here and give me 10 communication tools I can practice",
    "list 3-5 medications that help with ED",
    "which one would you suggest",
    "tell me the difference between Viagra, Cialis, or Levitra",
    "Stop doing the intake",
    "We are not supposed to be doing the intake",
]


def _fake_intake_row(**overrides):
    base = {field: "" for field in SECTION1_FIELDS}
    base.update(
        {
            "user_id": "john_d",
            "coach_nate_style_guidance": "",
        }
    )
    base.update(overrides)
    return base


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


@pytest.fixture(autouse=True)
def _enable_intake(monkeypatch):
    monkeypatch.setenv("ENABLE_INTAKE_SYSTEM", "true")
    monkeypatch.setenv("ENABLE_INTAKE_WALKTHROUGH", "true")
    monkeypatch.setenv("INTAKE_SEMANTIC_CLASSIFIER", "false")
    iw.reset_runtime()


@pytest.fixture
def profile():
    return {
        "role": "CLIENT",
        "hardware_id": "CLIENT_TEST_ID",
        "username": "john_d",
        "name": "John D.",
    }


@pytest.fixture
def conn():
    c = AsyncMock()
    c.fetchrow = AsyncMock(return_value={"tokens_credited": {}})
    return c


@pytest.fixture
def pool(conn):
    return _FakePool(conn)


async def _run_turn(profile, pool, user_text, intake_row):
    with patch.object(iw, "ensure_intake_row", AsyncMock()), patch.object(
        iw, "get_client_intake", AsyncMock(return_value=intake_row)
    ), patch.object(iw, "update_client_answer", AsyncMock()) as update_mock, patch.object(
        iw, "credit_walkthrough_question", AsyncMock(return_value={"credited": False, "amount": 0})
    ) as credit_mock, patch.object(
        iw, "summarize_walkthrough_credits", AsyncMock(return_value={"earned": 0, "max_possible": 12000})
    ):
        result = await iw.handle_intake_walkthrough_turn(
            profile=profile, user_text=user_text, db_pool=pool
        )
        return result, update_mock, credit_mock


@pytest.mark.asyncio
async def test_walkthrough_disabled_skips_all_turns(profile, pool, monkeypatch):
    monkeypatch.setenv("ENABLE_INTAKE_WALKTHROUGH", "false")
    intake = _fake_intake_row()
    result, update_mock, credit_mock = await _run_turn(profile, pool, "hello", intake)
    assert result["handled"] is False
    update_mock.assert_not_called()
    credit_mock.assert_not_called()
    assert iw.get_intake_chat_policy_addendum() != ""


@pytest.mark.asyncio
async def test_decline_at_offer_stops_and_stays_stopped(profile, pool):
    intake = _fake_intake_row()
    r1, _, _ = await _run_turn(profile, pool, "hello", intake)
    assert r1["handled"] is True
    assert "intake" in r1["response"].lower()

    r2, _, _ = await _run_turn(profile, pool, "later", intake)
    assert r2["handled"] is True

    r3, update_mock, credit_mock = await _run_turn(profile, pool, "Focus on my journey", intake)
    assert r3["handled"] is False
    update_mock.assert_not_called()
    credit_mock.assert_not_called()

    st = iw._state(profile["hardware_id"])
    assert st.get("declined") is True
    assert st.get("stopped") is True
    assert st.get("active") is False


@pytest.mark.asyncio
async def test_non_answer_turn_not_credited(profile, pool):
    intake = _fake_intake_row()
    await _run_turn(profile, pool, "hello", intake)
    await _run_turn(profile, pool, "later", intake)

    _, update_mock, credit_mock = await _run_turn(
        profile, pool, "give me tools for communication", intake
    )
    update_mock.assert_not_called()
    credit_mock.assert_not_called()


@pytest.mark.asyncio
async def test_stop_signal_exits_walkthrough(profile, pool):
    intake = _fake_intake_row()
    await _run_turn(profile, pool, "yes", intake)
    st = iw._state(profile["hardware_id"])
    st["active"] = True
    st["awaiting_answer"] = True
    st["current_q"] = "q1_preferred_name"

    r, update_mock, credit_mock = await _run_turn(profile, pool, "stop it here", intake)
    assert r["handled"] is False
    assert st.get("stopped") is True
    assert st.get("active") is False
    update_mock.assert_not_called()
    credit_mock.assert_not_called()


@pytest.mark.asyncio
async def test_pause_does_not_auto_resume(profile, pool):
    intake = _fake_intake_row()
    await _run_turn(profile, pool, "yes", intake)
    st = iw._state(profile["hardware_id"])
    st["active"] = True
    st["awaiting_answer"] = True
    st["current_q"] = "q2_pronouns"

    r_pause, _, _ = await _run_turn(profile, pool, "pause", intake)
    assert r_pause["handled"] is True
    assert st.get("stopped") is True
    assert st.get("active") is False

    r_next, update_mock, credit_mock = await _run_turn(profile, pool, "they/them", intake)
    assert r_next["handled"] is False
    update_mock.assert_not_called()
    credit_mock.assert_not_called()


@pytest.mark.asyncio
async def test_tokens_only_credited_for_genuine_answer(profile, pool):
    intake = _fake_intake_row()
    await _run_turn(profile, pool, "yes", intake)
    st = iw._state(profile["hardware_id"])
    st["active"] = True
    st["awaiting_answer"] = True
    st["current_q"] = "q1_preferred_name"

    with patch.object(iw, "ensure_intake_row", AsyncMock()), patch.object(
        iw, "get_client_intake", AsyncMock(return_value=intake)
    ), patch.object(iw, "update_client_answer", AsyncMock()) as update_mock, patch.object(
        iw, "credit_walkthrough_question", AsyncMock(return_value={"credited": True, "amount": 1000})
    ) as credit_mock, patch.object(
        iw, "summarize_walkthrough_credits", AsyncMock(return_value={"earned": 1000, "max_possible": 12000})
    ), patch.object(iw, "_generate_intelligent_ack", AsyncMock(return_value=None)):
        result = await iw.handle_intake_walkthrough_turn(
            profile=profile, user_text="John", db_pool=pool
        )
    assert result["handled"] is True
    update_mock.assert_called_once()
    credit_mock.assert_called_once()

    st["awaiting_answer"] = False
    st["active"] = True
    st["current_q"] = "q2_pronouns"
    with patch.object(iw, "ensure_intake_row", AsyncMock()), patch.object(
        iw, "get_client_intake", AsyncMock(return_value={**intake, "q1_preferred_name": "John"})
    ), patch.object(iw, "update_client_answer", AsyncMock()) as update_mock2, patch.object(
        iw, "credit_walkthrough_question", AsyncMock(return_value={"credited": True, "amount": 1000})
    ) as credit_mock2, patch.object(
        iw, "summarize_walkthrough_credits", AsyncMock(return_value={"earned": 1000, "max_possible": 12000})
    ):
        await iw.handle_intake_walkthrough_turn(
            profile=profile, user_text="they/them", db_pool=pool
        )
    update_mock2.assert_not_called()
    credit_mock2.assert_not_called()


@pytest.mark.asyncio
async def test_full_transcript_regression(profile, pool):
    intake = _fake_intake_row()
    total_credits = 0

    with patch.object(iw, "ensure_intake_row", AsyncMock()), patch.object(
        iw, "get_client_intake", AsyncMock(return_value=intake)
    ), patch.object(iw, "update_client_answer", AsyncMock()) as update_mock, patch.object(
        iw, "summarize_walkthrough_credits", AsyncMock(return_value={"earned": 0, "max_possible": 12000})
    ):

        async def _credit(*args, **kwargs):
            nonlocal total_credits
            total_credits += 1000
            return {"credited": True, "amount": 1000}

        with patch.object(iw, "credit_walkthrough_question", AsyncMock(side_effect=_credit)):
            for turn in TRANSCRIPT_TURNS:
                await iw.handle_intake_walkthrough_turn(
                    profile=profile, user_text=turn, db_pool=pool
                )

    assert total_credits == 0, f"expected zero intake credits, got {total_credits}"
    update_mock.assert_not_called()
    st = iw._state(profile["hardware_id"])
    assert st.get("declined") is True
    assert st.get("stopped") is True
    assert st.get("active") is False
    assert intake.get("q1_preferred_name", "") != "Hello"
