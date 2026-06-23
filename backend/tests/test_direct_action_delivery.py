"""Direct action step / teaching delivery when client explicitly requests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "backend"))

from app.services.little_nate_clinical_output_policy import (  # noqa: E402
    classify_direct_action_request,
    count_deliverable_list_items,
    direct_action_audit_violations,
    response_delivers_direct_action,
)
from app.services.therapeutic_controller import (  # noqa: E402
    _audit_violations,
    audit_therapeutic_response,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("suggest 2-3 action steps that would be helpful", "action_steps"),
        ("generate some good action steps for me to consider", "action_steps"),
        ("You are asking questions instead of suggesting", "action_steps"),
        ("I welcome you to offer one", "single_suggestion"),
        ("teach me one idea", "teaching"),
        ("how are you today", None),
    ],
)
def test_classify_direct_action_request(text: str, expected: str | None) -> None:
    assert classify_direct_action_request(text) == expected


def test_empty_action_steps_promise_fails_audit() -> None:
    bad = (
        "Here are a few action steps that might be helpful:\n\n"
        "These steps are not meant to be prescriptive."
    )
    assert count_deliverable_list_items(bad) == 0
    v = direct_action_audit_violations(bad, "action_steps")
    assert "action_steps_promised_empty" in v
    assert not response_delivers_direct_action(bad, "action_steps")


def test_bullet_action_steps_pass() -> None:
    good = (
        "Lisa, here are three invitations:\n"
        "* Continue story panels 2–3 times daily\n"
        "* Block 20 minutes for rest and prayer\n"
        "* Plan one unhurried conversation with Bill this week"
    )
    assert response_delivers_direct_action(good, "action_steps")
    assert direct_action_audit_violations(good, "action_steps") == []


def test_audit_violations_includes_direct_action() -> None:
    meta = {
        "locale": "en-US",
        "autonomic_state": "in_window",
        "max_tokens": 600,
        "direct_action_request_kind": "action_steps",
    }
    bad = "What feels like the next small step for you?"
    v = _audit_violations(bad, meta, [])
    assert "direct_action_not_delivered" in v


@pytest.mark.asyncio
async def test_direct_action_repair_regenerates() -> None:
    meta = {
        "locale": "en-US",
        "autonomic_state": "in_window",
        "max_tokens": 450,
        "mismatch_available": False,
        "direct_action_request_kind": "action_steps",
        "user_text_for_audit": "suggest 2-3 action steps please",
    }
    bad = "What feels present for you as you consider next steps?"
    fixed = (
        "Here are three gentle invitations:\n"
        "* Story panels twice daily\n"
        "* Protect rest and prayer rhythm\n"
        "* One intentional check-in with Bill"
    )
    with patch(
        "app.sse.llm_fallback.chat_completion_with_fallback",
        new_callable=AsyncMock,
        return_value=fixed,
    ):
        out = await audit_therapeutic_response(
            response_text=bad,
            audit_metadata=meta,
            user_id="CLIENT_TEST_ID",
            db_pool=None,
        )
    assert "* Story panels" in out["response_text"]
    assert out["audit_passed"] is True
