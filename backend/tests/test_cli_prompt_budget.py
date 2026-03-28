"""Tests for nate_cli_chat provider ceilings and history windowing."""

from app.websocket.cli_prompt_budget import (
    CLI_MAX_HISTORY_CHARS,
    trim_prompt_to_ceiling,
    trim_system_for_non_system_budget,
    window_cli_conversation_history,
)


def test_trim_prompt_noop_when_small():
    sp, um = "short system", "user" * 10
    out_s, out_u = trim_prompt_to_ceiling(sp, um, "grok", max_response_tokens=2000)
    assert out_s == sp and out_u == um


def test_trim_prompt_truncates_large_system():
    big = "x" * 100_000
    um = "hello"
    out_s, out_u = trim_prompt_to_ceiling(big, um, "workers_ai", max_response_tokens=500)
    assert out_u == um
    assert len(out_s) < len(big)
    assert "CONTEXT TRIMMED" in out_s


def test_window_keeps_short_list():
    msgs = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    assert window_cli_conversation_history(msgs, max_chars=CLI_MAX_HISTORY_CHARS) == msgs


def test_window_truncates_long_chain():
    msgs = [{"role": "user", "content": "first"}]
    for i in range(20):
        msgs.append({"role": "assistant", "content": "x" * 2000})
        msgs.append({"role": "user", "content": "y" * 2000})
    out = window_cli_conversation_history(msgs, max_chars=4000)
    total = sum(len(m.get("content") or "") for m in out)
    assert total <= 4500  # marker + slack
    assert len(out) < len(msgs)
    assert any("omitted" in (m.get("content") or "") or "trimmed" in (m.get("content") or "") for m in out)


def test_trim_system_for_non_system_budget():
    sys = "S" * 50_000
    out = trim_system_for_non_system_budget(sys, non_system_char_len=10_000, provider="sovereign", max_response_tokens=2000)
    assert len(out) < len(sys)
