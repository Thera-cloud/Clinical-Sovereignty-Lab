"""Show voice floor: short instruction, reasoning off, host/caller tools."""

import asyncio

from app.services.studio_voice_floor import (
    SHORT_INSTRUCTION,
    SMART_TURN_MS,
    session_update_payload,
    run_voice_tool,
)


def test_session_is_short_and_reasoning_off():
    body = session_update_payload("Rex")["session"]
    assert body["reasoning"]["effort"] == "none"
    assert body["turn_detection"]["type"] == "server_vad"
    assert body["turn_detection"]["silence_duration_ms"] == SMART_TURN_MS
    assert len(body["instructions"]) < 500
    assert body["instructions"] == SHORT_INSTRUCTION
    names = [t["name"] for t in body["tools"]]
    assert names == ["show_floor", "onair_notes", "host_lookup"]


def test_caller_lookup_is_refused():
    text = asyncio.run(
        run_voice_tool("host_lookup", {"query": "who is the mayor", "speaker": "caller"})
    )
    assert text == "No lookup for a caller."


def test_show_floor_reads_working_goal():
    from app.services.studio_show_thread import apply_turn

    apply_turn("voice-floor-sid", "host", "Talk about a consumer product.", "new_topic", "Yeah.")
    text = asyncio.run(run_voice_tool("show_floor", {}, "voice-floor-sid"))
    assert "consumer product" in text.lower() or "Goal:" in text
