"""VS Code / code-server workspace tool provider routing.

Feature-flagged via ENABLE_WORKSPACE_PROVIDER=1.
Extension registers as provider; CLI tools route through it with local fallback.
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

WORKSPACE_TOOLS = frozenset({
    "read_file", "search_code", "list_directory", "glob_files",
    "read_diagnostics", "read_git_status", "proposed_edit",
    "write_file", "create_file", "delete_file", "rename_file",
    "run_command", "read_open_editors",
})

_ENABLED_VALUES = frozenset({"1", "true", "TRUE", "yes", "on"})

_provider_ws: Any = None
_provider_id: str = ""
_workspace_root: str = ""
_capabilities: Set[str] = set()
_pending: Dict[str, asyncio.Future] = {}
_pending_acks: Dict[str, float] = {}
_request_created: Dict[str, float] = {}
_cli_sockets: Set[Any] = set()


def enabled() -> bool:
    return os.getenv("ENABLE_WORKSPACE_PROVIDER", "0") in _ENABLED_VALUES


def register_cli_socket(ws: Any) -> None:
    _cli_sockets.add(ws)


def unregister_cli_socket(ws: Any) -> None:
    _cli_sockets.discard(ws)


def is_provider(ws: Any) -> bool:
    return ws is not None and ws is _provider_ws


def provider_snapshot() -> Dict[str, Any]:
    return {
        "active": _provider_ws is not None,
        "provider_id": _provider_id,
        "workspace_root": _workspace_root,
        "capabilities": sorted(_capabilities),
    }


async def _safe_send(ws: Any, payload: dict) -> None:
    if ws is None:
        return
    try:
        await ws.send(json.dumps(payload))
    except Exception as exc:
        logger.debug("workspace send failed: %s", exc)


async def _broadcast_available() -> None:
    msg = {
        "type": "workspace_provider_available",
        "workspace_root": _workspace_root,
        "capabilities": sorted(_capabilities),
    }
    dead = []
    for ws in list(_cli_sockets):
        try:
            await ws.send(json.dumps(msg))
        except Exception:
            dead.append(ws)
    for ws in dead:
        _cli_sockets.discard(ws)


async def handle_register(ws: Any, data: dict, role: str) -> None:
    global _provider_ws, _provider_id, _workspace_root, _capabilities
    if not enabled():
        await _safe_send(ws, {
            "type": "workspace_provider_registered",
            "status": "disabled",
            "error": "ENABLE_WORKSPACE_PROVIDER is off",
        })
        return
    if role != "ADMIN":
        await _safe_send(ws, {
            "type": "workspace_provider_registered",
            "status": "rejected",
            "error": "Admin role required",
        })
        return

    if _provider_ws is not None and _provider_ws is not ws:
        await _safe_send(_provider_ws, {
            "type": "workspace_provider_replaced",
            "reason": "superseded_by_new_registration",
        })
        print(">>> [WORKSPACE] Provider replaced by new registration")

    _provider_ws = ws
    _provider_id = str(data.get("provider_id") or f"vscode-{int(time.time())}")
    _workspace_root = str(data.get("workspace_root") or "")
    caps = data.get("capabilities") or []
    _capabilities = {str(c) for c in caps if str(c) in WORKSPACE_TOOLS}
    register_cli_socket(ws)
    await _safe_send(ws, {"type": "workspace_provider_registered", "status": "active"})
    await _broadcast_available()
    print(f">>> [WORKSPACE] Provider active root={_workspace_root!r} caps={len(_capabilities)}")


def handle_tool_call_result(data: dict) -> None:
    rid = str(data.get("request_id") or "")
    fut = _pending.pop(rid, None)
    _request_created.pop(rid, None)
    _pending_acks.pop(rid, None)
    if fut is None or fut.done():
        return
    fut.set_result({
        "success": bool(data.get("success", False)),
        "content": data.get("content", ""),
        "error": data.get("error"),
        "error_code": data.get("error_code"),
        "metadata": data.get("metadata") or {},
        "action": data.get("action"),
        "duration_ms": data.get("duration_ms"),
        "fallback": False,
    })


def handle_tool_call_ack(data: dict) -> None:
    rid = str(data.get("request_id") or "")
    if rid in _pending:
        _pending_acks[rid] = time.time()


async def handle_tool_call_cancel(data: dict) -> None:
    rid = str(data.get("request_id") or "")
    if _provider_ws is not None:
        await _safe_send(_provider_ws, {
            "type": "tool_call_cancel",
            "request_id": rid,
            "reason": data.get("reason") or "cli_cancelled",
        })
    fut = _pending.pop(rid, None)
    _request_created.pop(rid, None)
    _pending_acks.pop(rid, None)
    if fut is not None and not fut.done():
        fut.set_result({
            "success": False,
            "action": "cancelled",
            "error_code": "CANCELLED",
            "fallback": False,
        })


async def handle_workspace_event(ws: Any, data: dict) -> None:
    if not is_provider(ws):
        return
    msg = {
        "type": "workspace_event",
        "event_type": data.get("event_type"),
        "file": data.get("file"),
        "language": data.get("language"),
        "errors": data.get("errors"),
    }
    for cli_ws in list(_cli_sockets):
        if cli_ws is ws:
            continue
        await _safe_send(cli_ws, msg)


async def on_disconnect(ws: Any) -> None:
    global _provider_ws, _provider_id, _workspace_root, _capabilities
    unregister_cli_socket(ws)
    if ws is not _provider_ws:
        return
    _provider_ws = None
    _provider_id = ""
    _workspace_root = ""
    _capabilities = set()
    for rid, fut in list(_pending.items()):
        if not fut.done():
            fut.set_result({
                "fallback": True,
                "reason": "workspace_disconnected",
                "error_code": "WORKSPACE_DISCONNECTED",
            })
    _pending.clear()
    _pending_acks.clear()
    _request_created.clear()
    print(">>> [WORKSPACE] VS Code disconnected — falling back to local")


async def route_tool_call(tool_call: dict) -> dict:
    """Callable for cli_tools.execute_tool(workspace_router=...)."""
    tool_name = str(tool_call.get("tool") or "")
    request_id = str(tool_call.get("request_id") or uuid.uuid4())
    if (
        not enabled()
        or _provider_ws is None
        or tool_name not in WORKSPACE_TOOLS
        or tool_name not in _capabilities
    ):
        return {
            "fallback": True,
            "reason": "no_workspace_provider",
            "error_code": "WORKSPACE_DISCONNECTED",
            "request_id": request_id,
        }

    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    _pending[request_id] = fut
    _request_created[request_id] = time.time()
    await _safe_send(_provider_ws, {
        "type": "tool_call_request",
        "request_id": request_id,
        "tool": tool_name,
        "params": tool_call.get("params") or {},
        "requesting_cli": tool_call.get("requesting_cli") or "nate_cli",
    })

    timeout = 300.0 if tool_name == "proposed_edit" else 30.0
    try:
        if tool_name == "proposed_edit":
            # Wait briefly for ack; then allow long human review window.
            try:
                await asyncio.wait_for(_wait_ack(request_id), timeout=5.0)
            except asyncio.TimeoutError:
                _pending.pop(request_id, None)
                _request_created.pop(request_id, None)
                return {
                    "fallback": True,
                    "reason": "workspace_ack_timeout",
                    "error_code": "TIMEOUT",
                    "request_id": request_id,
                }
        result = await asyncio.wait_for(fut, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        _pending.pop(request_id, None)
        _request_created.pop(request_id, None)
        _pending_acks.pop(request_id, None)
        await _safe_send(_provider_ws, {
            "type": "tool_call_cancel",
            "request_id": request_id,
            "reason": "bridge_timeout",
        })
        return {
            "fallback": True,
            "reason": "workspace_timeout",
            "error_code": "TIMEOUT",
            "request_id": request_id,
        }


async def _wait_ack(request_id: str) -> None:
    while request_id not in _pending_acks:
        if request_id not in _pending:
            return
        await asyncio.sleep(0.05)


async def sweep_stale_requests() -> None:
    """Resolve pending futures older than 300s."""
    now = time.time()
    for rid, created in list(_request_created.items()):
        if now - created <= 300:
            continue
        fut = _pending.pop(rid, None)
        _request_created.pop(rid, None)
        _pending_acks.pop(rid, None)
        if fut is not None and not fut.done():
            fut.set_result({
                "fallback": True,
                "reason": "stale_request_cleaned",
                "error_code": "TIMEOUT",
            })


async def handle_workspace_message(
    msg_type: str,
    data: dict,
    ws: Any,
    role: str,
) -> bool:
    """Dispatch inbound workspace messages. Returns True if handled."""
    if msg_type == "workspace_provider_register":
        await handle_register(ws, data, role)
        return True
    if msg_type == "tool_call_result":
        handle_tool_call_result(data)
        return True
    if msg_type == "tool_call_ack":
        handle_tool_call_ack(data)
        return True
    if msg_type == "tool_call_cancel":
        await handle_tool_call_cancel(data)
        return True
    if msg_type == "workspace_event":
        await handle_workspace_event(ws, data)
        return True
    return False


WORKSPACE_SENTINEL_TYPES = (
    "workspace_provider_register",
    "workspace_provider_replaced",
    "workspace_provider_available",
    "tool_call_result",
    "tool_call_ack",
    "tool_call_cancel",
    "workspace_event",
)
