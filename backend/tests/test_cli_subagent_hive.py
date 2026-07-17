"""Offline tests: Workers AI worker-ant hive helpers (Queen review pattern)."""

import os

import pytest

os.environ["REDIS_URL"] = ""
os.environ.setdefault("WORKERS_AI_URL", "")
os.environ.setdefault("WORKERS_AI_TOKEN", "")


def test_resolve_provider_defaults_and_fallback(monkeypatch):
    from app.websocket import cli_subagent_hive as h

    monkeypatch.delenv("WORKERS_AI_URL", raising=False)
    monkeypatch.delenv("WORKERS_AI_TOKEN", raising=False)
    assert h.resolve_subagent_provider("explore") == "grok"  # unconfigured → grok
    assert h.resolve_subagent_provider("full") == "grok"

    monkeypatch.setenv("WORKERS_AI_URL", "https://example.test/ai")
    monkeypatch.setenv("WORKERS_AI_TOKEN", "tok")
    # reload helpers that read env at call time
    assert h.workers_ai_configured() is True
    assert h.resolve_subagent_provider("explore") == "workers_ai"
    assert h.resolve_subagent_provider("test_fix") == "workers_ai"
    assert h.resolve_subagent_provider("full") == "grok"
    assert h.resolve_subagent_provider("explore", "grok") == "grok"


def test_parse_tool_arguments_repair():
    from app.websocket.cli_subagent_hive import parse_tool_arguments

    args, repaired, err = parse_tool_arguments('{"path": "a.py"}')
    assert err is None and args["path"] == "a.py" and repaired is False

    args, repaired, err = parse_tool_arguments("{'path': 'b.py',}")
    assert err is None and args.get("path") == "b.py" and repaired is True

    args, repaired, err = parse_tool_arguments("not-json{{{")
    assert err is not None and args == {}


def test_child_needs_escalation():
    from app.websocket.cli_subagent_hive import child_needs_escalation

    assert child_needs_escalation({"status": "error"}) is True
    assert child_needs_escalation({"status": "ok", "response_text": "", "tool_calls": []}) is True
    assert child_needs_escalation({
        "status": "ok",
        "response_text": "found it",
        "tool_calls": [{"name": "grep"}],
    }) is False
    assert child_needs_escalation({
        "status": "ok",
        "response_text": "x",
        "autonomy": {"budget_exhausted": True},
    }) is True


def test_structure_and_tag_for_queen():
    from app.websocket.cli_subagent_hive import (
        structure_subagent_result,
        tag_summary_for_queen,
    )

    result = {
        "status": "ok",
        "response_text": "See backend/app/main.py:42 for lifespan.",
        "turn_count": 2,
        "tool_calls": [{"name": "read_file", "args": {"path": "backend/app/main.py"}}],
        "files": [{"path": "backend/app/main.py", "action": "write"}],
    }
    out = structure_subagent_result(
        profile="explore",
        provider="workers_ai",
        escalated=False,
        result=result,
        cite_meta={"ok": True, "violations": []},
    )
    assert out["status"] == "ok"
    assert out["provider"] == "workers_ai"
    assert out["structured"]["confidence"] >= 0.8
    assert "backend/app/main.py" in out["files"]
    assert any("main.py" in r for r in out["line_refs"])

    tagged = tag_summary_for_queen("claim", {"violations": ["unverified cite"]})
    assert "[INFERRED]" in tagged or "QUEEN REVIEW" in tagged


def test_worker_must_sandbox():
    from app.websocket.cli_subagent_hive import worker_must_sandbox

    assert worker_must_sandbox("workers_ai", "test_fix") is True
    assert worker_must_sandbox("workers_ai", "explore") is False
    assert worker_must_sandbox("grok", "test_fix") is False


def test_build_worker_brief_includes_task():
    from app.websocket.cli_subagent_hive import build_worker_brief

    brief = build_worker_brief(
        "Find foo",
        profile="explore",
        plan_id="p1",
        parent_files=[{"path": "a.py"}],
    )
    assert "Find foo" in brief
    assert "WORKER ANT" in brief
    assert "a.py" in brief


def test_nest_block_and_hive_module_in_handler_source():
    """Q1: nested spawn blocked; Gaps 1–8 wired in handler source."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "app" / "websocket" / "cli_chat_handler.py"
    text = src.read_text()
    assert "Nested spawn_subagent is not allowed" in text
    assert "force_provider" in text
    assert "subagents_by_provider" in text
    assert "worker escalate" in text.lower() or "Worker escalate" in text
    assert "cli_subagent_hive" in text


def test_cloud_sandbox_force_flag():
    from app.websocket.cli_tools import _cloud_sandbox_active

    assert _cloud_sandbox_active("mac", "ask", force_sandbox=True) is True
    assert _cloud_sandbox_active("mac", "ask", force_sandbox=False) is False
