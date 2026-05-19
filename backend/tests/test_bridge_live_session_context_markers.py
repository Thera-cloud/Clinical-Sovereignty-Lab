from pathlib import Path


def test_bridge_includes_live_session_context_helper_and_prompt_block():
    bridge = Path(__file__).resolve().parents[1] / "app" / "websocket" / "bridge_server.py"
    src = bridge.read_text(encoding="utf-8")

    assert "def _format_live_turn_context" in src
    assert "LIVE SESSION CONTEXT (most recent turns):" in src
    assert "_chat_live_turns" in src
    assert "_live_turn_context" in src
    assert "repeat what you just said" in src

