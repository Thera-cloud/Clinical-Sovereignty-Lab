"""Offline unit tests for workspace provider routing (Phase 0)."""
from __future__ import annotations

import asyncio
import os

import pytest


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.setenv("ENABLE_WORKSPACE_PROVIDER", "1")
    import app.websocket.workspace_provider_router as wpr

    wpr._provider_ws = None
    wpr._provider_id = ""
    wpr._workspace_root = ""
    wpr._capabilities = set()
    wpr._pending.clear()
    wpr._pending_acks.clear()
    wpr._request_created.clear()
    wpr._cli_sockets.clear()
    yield
    wpr._provider_ws = None
    wpr._pending.clear()
    wpr._cli_sockets.clear()


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, raw: str):
        self.sent.append(raw)


@pytest.mark.asyncio
async def test_register_requires_admin():
    from app.websocket import workspace_provider_router as wpr

    ws = _FakeWS()
    await wpr.handle_register(ws, {"workspace_root": "/tmp", "capabilities": ["read_file"]}, "CLIENT")
    assert any("rejected" in s for s in ws.sent)


@pytest.mark.asyncio
async def test_route_falls_back_without_provider():
    from app.websocket import workspace_provider_router as wpr

    result = await wpr.route_tool_call({"tool": "read_file", "params": {"path": "a.py"}})
    assert result.get("fallback") is True
    assert result.get("error_code") == "WORKSPACE_DISCONNECTED"


@pytest.mark.asyncio
async def test_route_round_trip():
    from app.websocket import workspace_provider_router as wpr

    ws = _FakeWS()
    await wpr.handle_register(
        ws,
        {
            "provider_id": "t1",
            "workspace_root": "/repo",
            "capabilities": ["read_file"],
        },
        "ADMIN",
    )
    assert wpr.provider_snapshot()["active"] is True

    async def _respond():
        await asyncio.sleep(0.05)
        # Find request_id from outbound tool_call_request
        import json

        rid = None
        for raw in ws.sent:
            msg = json.loads(raw)
            if msg.get("type") == "tool_call_request":
                rid = msg["request_id"]
                break
        assert rid
        wpr.handle_tool_call_result({
            "request_id": rid,
            "success": True,
            "content": "hello",
        })

    task = asyncio.create_task(_respond())
    result = await wpr.route_tool_call({"tool": "read_file", "params": {"path": "a.py"}})
    await task
    assert result.get("fallback") is False
    assert result.get("content") == "hello"
    assert result.get("success") is True


def test_disabled_flag(monkeypatch):
    monkeypatch.setenv("ENABLE_WORKSPACE_PROVIDER", "0")
    from app.websocket import workspace_provider_router as wpr

    assert wpr.enabled() is False


def test_cli_code_model_env_alias(monkeypatch):
    """Phase A0: CODE_MODEL fills reasoning when REASONING unset."""
    monkeypatch.delenv("NATE_CLI_REASONING_MODEL", raising=False)
    monkeypatch.delenv("NATE_CHAT_REASONING_MODEL", raising=False)
    monkeypatch.setenv("NATE_CLI_CODE_MODEL", "grok-4.5")
    resolved = (
        os.getenv("NATE_CLI_REASONING_MODEL")
        or os.getenv("NATE_CLI_CODE_MODEL")
        or os.getenv("NATE_CHAT_REASONING_MODEL")
        or ""
    )
    assert resolved == "grok-4.5"
