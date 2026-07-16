"""Offline verification: Full Agentic Reasoning & Coding Agent + partner API plug-in."""

import os
from pathlib import Path

import pytest

# Force no Redis side effects during unit tests
os.environ["REDIS_URL"] = ""


def test_spawn_subagent_in_agentic_modes_only():
    from app.websocket.cli_tools import get_tool_definitions

    def names(mode, cli):
        return {t["function"]["name"] for t in get_tool_definitions(mode, cli) if "function" in t}

    assert "spawn_subagent" in names("ln_fab", "cloud")
    assert "spawn_subagent" in names("debug", "mac")
    assert "spawn_subagent" not in names("ask", "cloud")
    assert "spawn_subagent" not in names("plan", "mac")


def test_todo_task_state_machine():
    from app.websocket.cli_tools import (
        _SESSION_TODO_STORE,
        _todo_write_sync,
        format_open_todos_prompt,
        get_todos_for_plan,
    )

    _SESSION_TODO_STORE.pop("plan-agentic", None)
    r1 = _todo_write_sync(
        [
            {"id": "t1", "content": "Explore cli_tools", "status": "in_progress"},
            {"id": "t2", "content": "Add tests", "status": "pending"},
        ],
        merge=False,
        session_key="plan-agentic",
    )
    assert r1["status"] == "ok"
    assert r1["total"] == 2
    prompt = format_open_todos_prompt("plan-agentic")
    assert "OPEN TASKS" in prompt
    assert "Explore cli_tools" in prompt

    r2 = _todo_write_sync(
        [{"id": "t1", "content": "Explore cli_tools", "status": "completed"}],
        merge=True,
        session_key="plan-agentic",
    )
    assert r2["completed"] == 1
    todos = get_todos_for_plan("plan-agentic")
    assert any(t["id"] == "t1" and t["status"] == "completed" for t in todos)
    # only t2 remains open
    open_prompt = format_open_todos_prompt("plan-agentic")
    assert "Add tests" in open_prompt
    assert "Explore cli_tools" not in open_prompt


def test_autonomy_budget_constants():
    from app.websocket.cli_chat_handler import (
        _CLI_MAX_FIX_ATTEMPTS,
        _CLI_MAX_SUBAGENT_TURNS,
        _SUBAGENT_PROFILES,
        _pytest_failed,
        _filter_tools_by_profile,
    )

    assert _CLI_MAX_FIX_ATTEMPTS >= 1
    assert _CLI_MAX_SUBAGENT_TURNS >= 4
    assert "explore" in _SUBAGENT_PROFILES
    assert "test_fix" in _SUBAGENT_PROFILES
    assert _pytest_failed({"auto_pytest": {"status": "error", "exit_code": 1}})
    assert not _pytest_failed({"auto_pytest": {"status": "ok", "exit_code": 0}})
    assert not _pytest_failed({})

    tools = [
        {"type": "function", "function": {"name": "read_file"}},
        {"type": "function", "function": {"name": "write_file"}},
        {"type": "function", "function": {"name": "spawn_subagent"}},
        {"type": "function", "function": {"name": "shell"}},
    ]
    explore = {t["function"]["name"] for t in _filter_tools_by_profile(tools, "explore")}
    assert "read_file" in explore
    assert "write_file" not in explore
    assert "spawn_subagent" not in explore
    full = {t["function"]["name"] for t in _filter_tools_by_profile(tools, "full")}
    assert "write_file" in full
    assert "spawn_subagent" not in full


def test_run_agentic_loop_exported():
    from app.websocket.cli_chat_handler import handle_nate_cli_chat, run_agentic_loop

    assert callable(run_agentic_loop)
    assert callable(handle_nate_cli_chat)


def _load_agents_api_module():
    """Load agents_api.py without importing app.routers package (avoids numpy crash in CI)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "app" / "routers" / "agents_api.py"
    spec = importlib.util.spec_from_file_location("agents_api_isolated", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_partner_agents_api_capabilities_and_routes():
    mod = _load_agents_api_module()
    caps = mod.AGENTIC_CAPABILITIES
    required = [
        "agentic_tool_loop",
        "retry_until_green",
        "spawn_subagent",
        "todo_task_state",
        "partner_agents_api",
        "cloud_sandbox_isolation",
        "autonomy_budget",
        "openai_compatible_completions",
    ]
    for key in required:
        assert caps.get(key) is True, f"missing capability: {key}"

    paths = [getattr(r, "path", "") or "" for r in mod.router.routes]
    assert any(p.endswith("/agents") or p == "/api/v1/agents" for p in paths)
    assert any("capabilities" in p for p in paths)
    assert any("promote" in p for p in paths)


def test_partner_auth_sk_sovereign_contract():
    mod = _load_agents_api_module()
    src = open(mod.__file__).read()
    assert "sk-sovereign-" in src
    assert "SOVEREIGN_PROXY_KEY" in src
    assert mod._tier_from_user({"source": "sovereign_proxy_key"}) == "ENTERPRISE"
    assert mod._tier_from_user({"role": "ADMIN"}) == "ENTERPRISE"
    assert mod._tier_from_user({"role": "COACH"}) == "PRO"
    # Proxy key must never elevate to ADMIN for the agentic loop
    assert mod._role_for_loop({"source": "sovereign_proxy_key"}) == "PARTNER"
    assert mod._role_for_loop({"role": "ADMIN"}) == "ADMIN"


@pytest.mark.asyncio
async def test_empty_message_fails_fast():
    from app.websocket.cli_chat_handler import run_agentic_loop

    events = []

    async def emit(msg):
        events.append(msg)

    result = await run_agentic_loop(
        user_message="   ",
        mode="ask",
        cli_type="cloud",
        emit=emit,
        allow_subagents=False,
    )
    assert result.get("status") == "error" or result.get("type") == "nate_cli_chat_error"
    assert any(e.get("type") == "nate_cli_chat_error" for e in events)


@pytest.mark.asyncio
async def test_partner_role_blocks_data_tools():
    """PARTNER must not query PHI/data tools (ADMIN-only)."""
    from app.websocket.cli_tools import execute_tool

    for name in ("query_sessions", "query_coherence_data", "query_user_profile"):
        result = await execute_tool(
            name, {}, cli_type="cloud", user_role="PARTNER", mode="ln_fab",
        )
        assert result.get("status") == "error"
        assert "ADMIN" in (result.get("error") or "")


@pytest.mark.asyncio
async def test_partner_role_blocks_sandbox_promote_tool():
    from app.websocket.cli_tools import execute_tool

    result = await execute_tool(
        "sandbox_promote",
        {"plan_id": "x"},
        cli_type="cloud",
        user_role="PARTNER",
        mode="ln_fab",
    )
    assert result.get("status") == "error"
    assert "ADMIN" in (result.get("error") or "")


def test_protected_promote_denylist():
    from app.websocket.cli_tools import _is_protected_promote_path

    assert _is_protected_promote_path("backend/app/websocket/bridge_server.py")
    assert _is_protected_promote_path("backend/app/main.py")
    assert _is_protected_promote_path("backend/migrations/999_evil.sql")
    assert _is_protected_promote_path("docker-compose.prod.yml")
    assert not _is_protected_promote_path("backend/app/routers/agents_api.py")
    assert not _is_protected_promote_path("backend/tests/test_agentic_coding_agent.py")


def test_retry_until_green_preserves_pending_failures():
    """Regression: read-only tools must not wipe pending_test_failures."""
    src = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "websocket"
        / "cli_chat_handler.py"
    ).read_text()
    # Old bug zeroed pending at every tool batch
    assert "pending_test_failures = 0\n            for tc, result" not in src
    assert "Do NOT zero pending_test_failures" in src


def test_proxy_cannot_promote_contract():
    mod = _load_agents_api_module()
    src = open(mod.__file__).read()
    assert "proxy key cannot promote" in src
    assert "PARTNER" in src
    assert mod.AGENTIC_CAPABILITIES.get("partner_role_isolation") is True
    assert mod.AGENTIC_CAPABILITIES.get("promote_protected_denylist") is True
    assert mod._MAX_CONCURRENT_RUNS >= 1


def test_feature_scorecard_pass_criteria():
    """
    PASS requires all Full Agentic features present in code + API plug-in.
    """
    mod = _load_agents_api_module()
    from app.websocket.cli_chat_handler import (
        _CLI_MAX_FIX_ATTEMPTS,
        run_agentic_loop,
        _run_spawn_subagent,
    )
    from app.websocket.cli_tools import format_open_todos_prompt, get_tool_definitions

    checks = {
        "shared_agentic_loop": callable(run_agentic_loop),
        "spawn_subagent_impl": callable(_run_spawn_subagent),
        "spawn_subagent_tool": any(
            t.get("function", {}).get("name") == "spawn_subagent"
            for t in get_tool_definitions("ln_fab", "cloud")
        ),
        "todo_prompt_injection": callable(format_open_todos_prompt),
        "fix_budget": _CLI_MAX_FIX_ATTEMPTS >= 1,
        "api_capabilities_all_true": all(mod.AGENTIC_CAPABILITIES.values()),
        "main_registers_agents_api": "agents_api" in (
            Path(__file__).resolve().parents[1] / "app" / "main.py"
        ).read_text(),
        "partner_role_isolation": mod.AGENTIC_CAPABILITIES.get("partner_role_isolation"),
        "promote_denylist": mod.AGENTIC_CAPABILITIES.get("promote_protected_denylist"),
        "concurrency_cap": mod.AGENTIC_CAPABILITIES.get("agent_run_concurrency_cap"),
    }
    failed = [k for k, v in checks.items() if not v]
    assert not failed, f"FAIL features: {failed}"
    assert len(checks) >= 6
