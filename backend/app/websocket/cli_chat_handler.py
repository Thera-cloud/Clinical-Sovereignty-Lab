"""
WebSocket handler for nate_cli_chat — the Command Terminal's agentic loop.

Receives a user message + mode + cli type, builds the system prompt from
cli_manifest workspace rules, streams LLM responses via sovereign_chat_client,
executes tool calls via cli_tools, and sends chunked responses back over the
WebSocket connection.

Message types sent back:
  nate_cli_chat_chunk   — streamed text delta
  nate_cli_chat_tool    — tool call result
  nate_cli_chat_status  — thinking / tool_executing status
  nate_cli_chat_done    — turn complete with summary
  nate_cli_chat_error   — unrecoverable error
"""
# SOVEREIGN-VOICE — CLI Command Terminal handler

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import traceback
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.cli_chat")

_MAX_TOOL_TURNS = 15
_GROK_KEY: Optional[str] = None
_GROK_URL: Optional[str] = None
_GROK_MODEL: Optional[str] = None


def _ensure_grok_config():
    global _GROK_KEY, _GROK_URL, _GROK_MODEL
    if _GROK_KEY is not None:
        return
    try:
        from app.services.nate_ai_config import NATE_CHAT_KEY, NATE_CHAT_URL, NATE_CHAT_MODEL
        _GROK_KEY = NATE_CHAT_KEY
        _GROK_URL = NATE_CHAT_URL
        _GROK_MODEL = NATE_CHAT_MODEL
    except ImportError:
        _GROK_KEY = os.getenv("NATE_CHAT_KEY", os.getenv("AZURE_API_KEY", ""))
        _GROK_URL = os.getenv("NATE_CHAT_URL", "")
        _GROK_MODEL = os.getenv("NATE_CHAT_MODEL", "grok-4-1-fast-non-reasoning")


def _build_system_prompt(mode: str, cli_type: str) -> str:
    """Assemble the system prompt: manifest + workspace rules + mode instructions."""
    try:
        from app.websocket.cli_manifest import generate_manifest, load_workspace_rules
    except ImportError:
        return f"You are Little Nate CLI ({cli_type}) in {mode.upper()} mode."

    manifest = generate_manifest(max_chars=4000)
    rules = load_workspace_rules(mode)

    mode_instructions = _MODE_INSTRUCTIONS.get(mode, "")
    cli_label = "CLI-Cloud (server-side)" if cli_type == "cloud" else "CLI-Mac (local workstation)"

    return (
        f"You are Little Nate, operating as {cli_label} in {mode.upper()} mode.\n\n"
        f"{mode_instructions}\n\n"
        f"CODEBASE CONTEXT:\n{manifest}\n\n"
        f"{rules}\n\n"
        "TOOL USE: Call tools by using the function calling interface. "
        "After each tool result you will see the output and can decide to call more tools or respond.\n"
        "Always be concise. When reading files, cite paths. When making changes, explain why."
    )


_MODE_INSTRUCTIONS = {
    "ask": (
        "ASK MODE — Read-only exploration. You can read files, search code, grep, "
        "and list directories. You CANNOT write, delete, or execute shell commands. "
        "Answer questions about the codebase accurately using tool calls to verify."
    ),
    "plan": (
        "PLAN MODE — Read-only planning. You can read and search the codebase. "
        "You CANNOT write or execute. Create detailed plans with specific file paths, "
        "line numbers, and code snippets. Structure plans with numbered steps."
    ),
    "debug": (
        "DEBUG MODE — Diagnostic investigation. You can read files, search code, "
        "and (on CLI-Mac) write fixes and run shell commands. "
        "Systematically investigate bugs: check logs, trace code paths, identify root causes. "
        "Form hypotheses and test them with tool calls."
    ),
    "ln_fab": (
        "LN-FAB MODE — Full fabrication capability. You can read, write, delete files, "
        "run shell commands, execute git operations, and deploy (CLI-Mac only). "
        "Follow the LN-FAB protocol: verify before writing, test after changes, "
        "never modify protected files without explicit approval."
    ),
}


async def handle_nate_cli_chat(
    websocket,
    data: Dict[str, Any],
    current_profile: Dict[str, Any],
    db_pool=None,
):
    """
    Main entry point for nate_cli_chat WebSocket messages.

    Runs an agentic loop: LLM generates text + tool calls, tools are executed,
    results fed back, until the LLM produces a final text response.
    """
    mode = data.get("mode", "ask")
    cli_type = data.get("cli", "cloud")
    user_message = (data.get("message") or "").strip()
    plan_id = str(uuid.uuid4())[:12]
    turn = 0

    if not user_message:
        await _send(websocket, {"type": "nate_cli_chat_error", "error": "Empty message"})
        return

    if mode not in ("ask", "plan", "debug", "ln_fab"):
        mode = "ask"
    if cli_type not in ("mac", "cloud"):
        cli_type = "cloud"

    admin_username = current_profile.get("username", "unknown")
    user_role = current_profile.get("role", "ADMIN")

    try:
        from app.websocket.cli_tools import execute_tool, get_tool_definitions
        from app.websocket.cli_prompt_budget import trim_prompt_to_ceiling
    except ImportError as e:
        logger.error("CLI imports failed: %s", e)
        await _send(websocket, {"type": "nate_cli_chat_error", "error": f"CLI module import error: {e}"})
        return

    _ensure_grok_config()
    if not _GROK_URL or not _GROK_KEY:
        await _send(websocket, {"type": "nate_cli_chat_error", "error": "No LLM provider configured (NATE_CHAT_URL/KEY missing)"})
        return

    system_prompt = _build_system_prompt(mode, cli_type)
    system_prompt, _ = trim_prompt_to_ceiling(system_prompt, user_message, "grok")

    tools = get_tool_definitions(mode, cli_type)

    conversation: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    await _send(websocket, {"type": "nate_cli_chat_status", "status": "thinking", "detail": f"{mode.upper()} mode — {cli_type}"})

    tool_call_log: List[Dict[str, Any]] = []
    files_touched: List[Dict[str, str]] = []
    provider_used = "grok"
    t0 = time.monotonic()

    for turn_idx in range(_MAX_TOOL_TURNS):
        turn = turn_idx + 1

        try:
            response_text, response_tool_calls, provider_used = await _stream_with_tools(
                websocket, conversation, tools, turn, provider_used
            )
        except Exception as e:
            logger.error("CLI stream error (turn %d): %s", turn, e)
            await _send(websocket, {"type": "nate_cli_chat_error", "error": f"LLM error: {e}"})
            return

        if response_tool_calls:
            assistant_msg: Dict[str, Any] = {"role": "assistant", "content": response_text or ""}
            assistant_msg["tool_calls"] = response_tool_calls
            conversation.append(assistant_msg)

            for tc in response_tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "unknown")
                try:
                    tool_args = json.loads(fn.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    tool_args = {}

                tc_id = tc.get("id", f"call_{uuid.uuid4().hex[:8]}")

                await _send(websocket, {
                    "type": "nate_cli_chat_status",
                    "status": "tool_executing",
                    "detail": tool_name,
                })

                t_start = time.monotonic()
                try:
                    result = await execute_tool(
                        tool_name, tool_args,
                        cli_type=cli_type,
                        user_role=user_role,
                        mode=mode,
                        db_pool=db_pool,
                        plan_id=plan_id,
                        admin_username=admin_username,
                    )
                except Exception as te:
                    result = {"status": "error", "error": str(te)}
                t_elapsed = int((time.monotonic() - t_start) * 1000)

                status = result.get("status", "ok") if isinstance(result, dict) else "ok"
                result_text = _format_tool_result(result)

                preview = result_text[:500] + ("..." if len(result_text) > 500 else "")
                await _send(websocket, {
                    "type": "nate_cli_chat_tool",
                    "tool_name": tool_name,
                    "tool_input": tool_args,
                    "tool_output_preview": preview,
                    "status": status,
                    "duration_ms": t_elapsed,
                    "turn": turn,
                })

                tool_call_log.append({
                    "name": tool_name,
                    "args": tool_args,
                    "status": status,
                    "duration_ms": t_elapsed,
                })

                if tool_name in ("write_file", "str_replace", "delete_file"):
                    path = tool_args.get("path", tool_args.get("file_path", ""))
                    action = "write" if tool_name != "delete_file" else "delete"
                    if path:
                        files_touched.append({"path": path, "action": action})

                conversation.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_text,
                })

            await _send(websocket, {"type": "nate_cli_chat_status", "status": "thinking", "detail": "Processing tool results..."})
            continue

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await _send(websocket, {
            "type": "nate_cli_chat_done",
            "plan_id": plan_id,
            "mode": mode,
            "provider": provider_used,
            "files": files_touched,
            "tool_calls": tool_call_log,
            "turn_count": turn,
            "elapsed_ms": elapsed_ms,
        })
        return

    await _send(websocket, {
        "type": "nate_cli_chat_done",
        "plan_id": plan_id,
        "mode": mode,
        "provider": provider_used,
        "files": files_touched,
        "tool_calls": tool_call_log,
        "turn_count": turn,
        "elapsed_ms": int((time.monotonic() - t0) * 1000),
        "warning": f"Reached max tool turns ({_MAX_TOOL_TURNS})",
    })


async def _stream_with_tools(
    websocket,
    conversation: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    turn: int,
    provider: str,
) -> tuple:
    """
    Call Grok with tools, stream text deltas back to the client.
    Returns (accumulated_text, tool_calls_list, provider_name).
    """
    import aiohttp

    _ensure_grok_config()

    openai_tools = []
    for t_def in tools:
        if t_def.get("type") == "web_search":
            continue
        if "function" in t_def:
            openai_tools.append(t_def)
        elif "name" in t_def:
            openai_tools.append({"type": "function", "function": t_def})

    headers = {
        "api-key": _GROK_KEY,
        "Content-Type": "application/json",
    }

    messages_for_api = _convert_conversation(conversation)

    payload: Dict[str, Any] = {
        "model": _GROK_MODEL,
        "messages": messages_for_api,
        "temperature": 0.3,
        "max_completion_tokens": 4096,
        "stream": True,
    }
    if openai_tools:
        payload["tools"] = openai_tools
        payload["tool_choice"] = "auto"

    accumulated_text = ""
    tool_calls_accum: Dict[int, Dict[str, Any]] = {}

    timeout = aiohttp.ClientTimeout(total=180, sock_read=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(_GROK_URL, json=payload, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Grok {resp.status}: {body[:400]}")

            async for line in resp.content:
                decoded = line.decode("utf-8", errors="ignore").strip()
                if not decoded.startswith("data: "):
                    continue
                data_str = decoded[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                choices = chunk.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                finish = choices[0].get("finish_reason")

                content = delta.get("content") or ""
                if content:
                    accumulated_text += content
                    await _send(websocket, {
                        "type": "nate_cli_chat_chunk",
                        "delta": content,
                        "provider": provider,
                        "turn": turn,
                    })

                for tc in delta.get("tool_calls", []):
                    idx = tc.get("index", 0)
                    if idx not in tool_calls_accum:
                        tool_calls_accum[idx] = {
                            "id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        tool_calls_accum[idx]["function"]["name"] = fn["name"]
                    if fn.get("arguments"):
                        tool_calls_accum[idx]["function"]["arguments"] += fn["arguments"]
                    if tc.get("id"):
                        tool_calls_accum[idx]["id"] = tc["id"]

    tool_calls_list = [tool_calls_accum[k] for k in sorted(tool_calls_accum.keys())] if tool_calls_accum else []

    return accumulated_text, tool_calls_list, provider


def _convert_conversation(conversation: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert internal conversation to OpenAI API format."""
    messages = []
    for msg in conversation:
        role = msg.get("role", "user")
        if role == "tool":
            messages.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", ""),
                "content": msg.get("content", ""),
            })
        elif role == "assistant" and "tool_calls" in msg:
            m: Dict[str, Any] = {"role": "assistant"}
            if msg.get("content"):
                m["content"] = msg["content"]
            else:
                m["content"] = ""
            m["tool_calls"] = msg["tool_calls"]
            messages.append(m)
        else:
            messages.append({"role": role, "content": msg.get("content", "")})
    return messages


def _format_tool_result(result: Any) -> str:
    """Convert tool result to a string for the LLM context."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        status = result.get("status", "ok")
        if status == "error":
            return f"Error: {result.get('error', 'unknown error')}"
        output = result.get("output") or result.get("content") or result.get("result", "")
        if isinstance(output, str):
            return output
        return json.dumps(result, indent=2, default=str)
    return str(result)


async def _send(websocket, msg: Dict[str, Any]):
    """Send a JSON message, swallowing connection errors."""
    try:
        await websocket.send(json.dumps(msg, default=str))
    except Exception:
        pass
