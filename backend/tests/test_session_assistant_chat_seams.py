"""Seam tests for session assistant live chat memory assembly."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "session_assistant_chat.py"
)
_spec = importlib.util.spec_from_file_location("session_assistant_chat_under_test", _PATH)
sa = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(sa)


@pytest.mark.asyncio
async def test_empty_message_short_circuits():
    out = await sa.generate_coach_assist_reply(
        None, client_id="CLIENT_X", coach_message="  "
    )
    assert out.get("error") == "empty"
    assert out.get("reply") == ""


def test_mode_hint_covers_modes():
    assert "observe" in sa._MODE_HINT
    assert "suggest" in sa._MODE_HINT
    assert "challenge" in sa._MODE_HINT


@pytest.mark.asyncio
async def test_generate_uses_memory_flag(monkeypatch):
    async def _fake_memory(db_pool, client_id):
        return "[MAIN CHAT MEMORY]\nClient: I fear abandonment"

    async def _fake_llm(system, user):
        assert "abandonment" in user
        assert "Coach asks:" in user
        return "Prior chat shows abandonment fear — stay with longing, not fixing."

    monkeypatch.setattr(sa, "_load_client_memory", _fake_memory)
    monkeypatch.setattr(sa, "_llm_reply", _fake_llm)
    out = await sa.generate_coach_assist_reply(
        None,
        client_id="CLIENT_LETSGOLISA_ID",
        coach_message="What pattern am I seeing?",
        nate_mode="suggest",
        client_name="Lisa West",
    )
    assert out["memory_used"] is True
    assert "abandonment" in out["reply"].lower() or "longing" in out["reply"].lower()
