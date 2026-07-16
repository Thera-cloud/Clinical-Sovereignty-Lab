"""Offline tests for CLI-Mac/Cloud capability expansion (LN-FAB sandbox + tool defs)."""

import os
import tempfile

from app.websocket.cli_tools import (
    _apply_sandbox_overlay_args,
    _cloud_sandbox_active,
    _cloud_shell_allowed,
    _map_tool_to_mac_agent,
    _prefer_sandbox_path,
    _prepare_cloud_sandbox_path,
    _sandbox_diff_sync,
    get_tool_definitions,
    get_truncation_limit,
)
from app.websocket.cli_chat_handler import (
    _MAX_TOOL_TURNS,
    _align_keep_tail,
    _compact_conversation,
    _persist_session,
    _SESSION_HISTORY,
    _truncate_tool_result,
)


def _tool_names(mode: str, cli: str):
    return {t["function"]["name"] for t in get_tool_definitions(mode, cli) if "function" in t}


def test_cloud_ln_fab_exposes_sandbox_write_tools():
    names = _tool_names("ln_fab", "cloud")
    assert "write_file" in names
    assert "str_replace" in names
    assert "shell" in names
    assert "repo_map" in names
    assert "read_lints" in names
    assert "sandbox_diff" in names
    assert "sandbox_promote" in names
    assert "web_search" in names
    assert "build_promote" not in names


def test_mac_ln_fab_keeps_full_write_surface():
    names = _tool_names("ln_fab", "mac")
    assert "write_file" in names
    assert "shell" in names
    assert "repo_map" in names
    assert "build_start" in names or "build_status" in names


def test_ask_mode_still_read_only_on_cloud():
    names = _tool_names("ask", "cloud")
    assert "write_file" not in names
    assert "shell" not in names
    assert "repo_map" in names
    assert "web_search" in names


def test_no_bare_web_search_type_advertised():
    tools = get_tool_definitions("ask", "cloud")
    bare = [t for t in tools if t.get("type") == "web_search" and "function" not in t]
    assert bare == []
    assert any(t.get("function", {}).get("name") == "web_search" for t in tools if "function" in t)


def test_cloud_sandbox_active_flag():
    assert _cloud_sandbox_active("cloud", "ln_fab") is True
    assert _cloud_sandbox_active("cloud", "ask") is False
    assert _cloud_sandbox_active("mac", "ln_fab") is False


def test_cloud_shell_allowlist():
    assert _cloud_shell_allowed("python3 -m py_compile backend/app/main.py")
    assert _cloud_shell_allowed("git status")
    assert not _cloud_shell_allowed("rm -rf /")
    assert not _cloud_shell_allowed("python3 -m py_compile a.py && rm -rf /")


def test_max_tool_turns_expanded():
    assert _MAX_TOOL_TURNS["ln_fab"] >= 40
    assert _MAX_TOOL_TURNS["debug"] >= 35


def test_compact_conversation_summarizes():
    conv = [{"role": "system", "content": "sys"}]
    for i in range(30):
        conv.append({"role": "user", "content": "u" * 4000})
        conv.append({
            "role": "assistant",
            "content": "a" * 100,
            "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}],
        })
        conv.append({"role": "tool", "tool_call_id": f"c{i}", "content": "t" * 2000})
    out = _compact_conversation(conv, max_chars=20_000)
    assert len(out) < len(conv)
    assert any("CONTEXT COMPACTED" in (m.get("content") or "") for m in out)
    # No orphan tool messages
    open_ids = set()
    for m in out:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            open_ids = {tc["id"] for tc in m["tool_calls"]}
        elif m.get("role") == "tool":
            assert m.get("tool_call_id") in open_ids


def test_align_keep_tail_includes_assistant():
    body = [
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "x1", "function": {"name": "grep"}}]},
        {"role": "tool", "tool_call_id": "x1", "content": "r1"},
        {"role": "tool", "tool_call_id": "x1", "content": "r2"},
        {"role": "user", "content": "more"},
    ]
    # Force start mid-tool chain
    tail = _align_keep_tail(body, min_keep=2)
    assert tail[0].get("role") == "assistant" or tail[0].get("role") == "user"


def test_read_lints_maps_to_mac_lint_endpoint():
    endpoint, payload = _map_tool_to_mac_agent("read_lints", {"paths": ["a.py", "b.py"]})
    assert endpoint == "/lint"
    assert payload["paths"] == ["a.py", "b.py"]


def test_truncation_applied():
    assert get_truncation_limit("ln_fab", "mac") >= 16000
    short = _truncate_tool_result("hello", 100)
    assert short == "hello"
    long = _truncate_tool_result("x" * 5000, 1000)
    assert len(long) < 5000
    assert "truncated" in long


def test_sandbox_overlay_prefers_sandbox_file(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("CLI_CLOUD_SANDBOX_ROOT", tmp)
        # reload module constants would be hard — call prepare with patched path via import
        import app.websocket.cli_tools as ct
        old = ct._CLOUD_SANDBOX_ROOT
        ct._CLOUD_SANDBOX_ROOT = tmp
        try:
            dest = _prepare_cloud_sandbox_path("plan1", "foo.txt", copy_from_project=False)
            assert dest
            with open(dest, "w") as f:
                f.write("sandbox")
            preferred = _prefer_sandbox_path("plan1", "foo.txt")
            assert preferred == dest
            overlaid = _apply_sandbox_overlay_args("read_file", {"path": "foo.txt"}, "plan1")
            assert overlaid["path"] == dest
            # Allowlisted read-only cmds use project root; non-project cmds stay in sandbox
            shell_ls = _apply_sandbox_overlay_args("shell", {"command": "ls"}, "plan1")
            assert shell_ls["working_directory"] == ct._get_project_root()
            shell_sb = _apply_sandbox_overlay_args(
                "shell", {"command": "python3 -c 'print(1)'"}, "plan1"
            )
            assert shell_sb["working_directory"].endswith("plan1")
            diff = _sandbox_diff_sync("plan1")
            assert diff["status"] == "ok"
            assert any(f.get("path") == "foo.txt" for f in diff.get("files", []))
        finally:
            ct._CLOUD_SANDBOX_ROOT = old


def test_session_history_lru():
    _SESSION_HISTORY.clear()
    for i in range(55):
        _persist_session(f"k{i}", [], f"u{i}", f"a{i}")
    assert len(_SESSION_HISTORY) <= 50
    assert "k0" not in _SESSION_HISTORY
    assert "k54" in _SESSION_HISTORY


def test_token_limit_fields_azure_vs_grok():
    from app.websocket.cli_chat_handler import _token_limit_fields
    assert _token_limit_fields("azure", "gpt-4o", 1000) == {"max_tokens": 1000}
    assert _token_limit_fields("azure", "gpt-5.2-chat", 1000) == {"max_completion_tokens": 1000}
    assert _token_limit_fields("grok", "grok-4-1-fast-non-reasoning", 1000) == {
        "max_completion_tokens": 1000
    }


def test_cloud_shell_project_root_for_pytest():
    from app.websocket.cli_tools import _cloud_shell_uses_project_root
    assert _cloud_shell_uses_project_root("python3 -m pytest backend/tests/test_x.py -q")
    assert _cloud_shell_uses_project_root("git status")
    assert not _cloud_shell_uses_project_root("python3 -c 'print(1)'")


def test_infer_test_path_for_source():
    from app.websocket.cli_tools import infer_test_path_for_source
    # May or may not exist in tree; function should not crash
    result = infer_test_path_for_source("backend/app/websocket/cli_tools.py")
    if result:
        assert "test_" in result or result.endswith(".py")


def test_shell_overlay_pytest_sets_project_cwd_and_pythonpath(monkeypatch):
    import app.websocket.cli_tools as ct
    with tempfile.TemporaryDirectory() as tmp:
        old = ct._CLOUD_SANDBOX_ROOT
        ct._CLOUD_SANDBOX_ROOT = tmp
        try:
            args = _apply_sandbox_overlay_args(
                "shell",
                {"command": "python3 -m pytest backend/tests/test_cli_capability_expand.py -q"},
                "planX",
            )
            assert args["working_directory"] == ct._get_project_root()
            assert "_env" in args
            assert tmp in args["_env"]["PYTHONPATH"]
        finally:
            ct._CLOUD_SANDBOX_ROOT = old


def test_reasoning_modes_constant():
    from app.websocket.cli_chat_handler import _REASONING_MODES
    assert "ln_fab" in _REASONING_MODES
    assert "debug" in _REASONING_MODES
    assert "ask" not in _REASONING_MODES
