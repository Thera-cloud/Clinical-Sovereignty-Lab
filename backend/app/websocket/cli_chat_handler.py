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
import uuid
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nate.cli_chat")

# Mode-aware turn budgets (was hard-coded 15)
_MAX_TOOL_TURNS = {
    "ask": 25,
    "plan": 25,
    "debug": 40,
    "ln_fab": 45,
}
_MAX_COMPLETION_TOKENS = {
    "ask": 6144,
    "plan": 6144,
    "debug": 8192,
    "ln_fab": 12288,
}
_WRITE_TOOLS = frozenset({"write_file", "str_replace", "delete_file", "inject_log"})
_REASONING_MODES = frozenset({"ln_fab", "debug"})
_CONV_COMPACT_CHARS = 72_000
_SESSION_HISTORY: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
_SESSION_HISTORY_MAX = 40  # messages retained per session key
_SESSION_HISTORY_KEYS_MAX = 50  # LRU cap on distinct session keys
_SESSION_REDIS_TTL = int(os.getenv("CLI_SESSION_REDIS_TTL", "86400"))  # 24h
_CLI_MAX_FIX_ATTEMPTS = int(os.getenv("CLI_MAX_FIX_ATTEMPTS", "3"))
_CLI_MAX_SUBAGENT_TURNS = int(os.getenv("CLI_MAX_SUBAGENT_TURNS", "8"))
_PATH_WRITE_LOCKS: Dict[str, asyncio.Lock] = {}
_PATH_WRITE_LOCKS_GUARD: Optional[asyncio.Lock] = None
_SUBAGENT_PROFILES: Dict[str, Optional[frozenset]] = {
    "explore": frozenset({
        "read_file", "list_directory", "grep", "glob", "repo_map",
        "read_lints", "web_search", "web_fetch", "web_search_local",
        "todo_write", "self_capabilities",
    }),
    "test_fix": frozenset({
        "read_file", "grep", "glob", "write_file", "str_replace",
        "shell", "read_lints", "todo_write", "repo_map", "self_capabilities",
    }),
    "full": None,  # inherit parent tool set
}
# QUANTUM-CRYSTAL-ARCH — Queen budgets (Q2); defaults also in cli_subagent_hive
try:
    from app.websocket.cli_subagent_hive import (
        CLI_MAX_SUBAGENTS_PER_RUN as _CLI_MAX_SUBAGENTS_PER_RUN,
        CLI_MAX_SUBAGENTS_PER_TURN as _CLI_MAX_SUBAGENTS_PER_TURN,
    )
except ImportError:
    _CLI_MAX_SUBAGENTS_PER_TURN = int(os.getenv("CLI_MAX_SUBAGENTS_PER_TURN", "4"))
    _CLI_MAX_SUBAGENTS_PER_RUN = int(os.getenv("CLI_MAX_SUBAGENTS_PER_RUN", "8"))

_GROK_KEY: Optional[str] = None
_GROK_URL: Optional[str] = None
_GROK_MODEL: Optional[str] = None
_GROK_REASONING_MODEL: Optional[str] = None


def _ensure_grok_config():
    global _GROK_KEY, _GROK_URL, _GROK_MODEL, _GROK_REASONING_MODEL
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
    # Phase A0: LN-FAB/DEBUG prefer NATE_CLI_REASONING_MODEL, else NATE_CLI_CODE_MODEL
    _GROK_REASONING_MODEL = (
        os.getenv("NATE_CLI_REASONING_MODEL")
        or os.getenv("NATE_CLI_CODE_MODEL")
        or os.getenv("NATE_CHAT_REASONING_MODEL")
        or ""
    )


_CLI_REDIS = None
_CLI_REDIS_TRIED = False


def _cli_redis_client():
    """Best-effort sync Redis for session persistence (env-built; no bridge import)."""
    global _CLI_REDIS, _CLI_REDIS_TRIED
    if _CLI_REDIS_TRIED:
        return _CLI_REDIS
    _CLI_REDIS_TRIED = True
    # Offline/unit tests: empty REDIS_URL means skip Redis entirely
    if os.getenv("REDIS_URL", "__unset__") == "":
        _CLI_REDIS = None
        return None
    try:
        import redis as sync_redis
        url = os.getenv("REDIS_URL", "")
        if url:
            _CLI_REDIS = sync_redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.5)
            return _CLI_REDIS
        host = os.getenv("REDIS_HOST")
        if not host:
            _CLI_REDIS = None
            return None
        port = int(os.getenv("REDIS_PORT", "6379"))
        password = os.getenv("REDIS_PASSWORD") or None
        _CLI_REDIS = sync_redis.Redis(
            host=host, port=port, password=password,
            decode_responses=True, socket_connect_timeout=0.5,
        )
        return _CLI_REDIS
    except Exception:
        _CLI_REDIS = None
        return None


def _session_redis_key(sk: str) -> str:
    prefix = os.getenv("REDIS_KEY_PREFIX", "nate")
    env = os.getenv("ENVIRONMENT", "production")
    return f"{prefix}:{env}:cli_session:{sk}"


def _load_session_from_redis(sk: str) -> Optional[List[Dict[str, Any]]]:
    client = _cli_redis_client()
    if not client:
        return None
    try:
        raw = client.get(_session_redis_key(sk))
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, list) else None
    except Exception as e:
        logger.debug("CLI session redis load failed: %s", e)
        return None


def _save_session_to_redis(sk: str, hist: List[Dict[str, Any]]) -> None:
    client = _cli_redis_client()
    if not client:
        return
    try:
        client.setex(
            _session_redis_key(sk),
            _SESSION_REDIS_TTL,
            json.dumps(hist[-_SESSION_HISTORY_MAX:]),
        )
    except Exception as e:
        logger.debug("CLI session redis save failed: %s", e)


async def _path_lock(path: str) -> asyncio.Lock:
    global _PATH_WRITE_LOCKS_GUARD
    if _PATH_WRITE_LOCKS_GUARD is None:
        _PATH_WRITE_LOCKS_GUARD = asyncio.Lock()
    key = os.path.normpath(str(path or "")).lower()
    async with _PATH_WRITE_LOCKS_GUARD:
        lock = _PATH_WRITE_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _PATH_WRITE_LOCKS[key] = lock
        return lock


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

    try:
        from app.websocket.cli_grounding import (
            ACCURACY_CONTRACT,
            DESIGN_DISCIPLINE,
            VERIFICATION_BEFORE_CLAIM,
        )
        grounding_block = (
            f"{ACCURACY_CONTRACT}\n\n{VERIFICATION_BEFORE_CLAIM}\n\n{DESIGN_DISCIPLINE}"
        )
    except ImportError:
        grounding_block = (
            "ACCURACY: Verify codebase claims with tools. "
            "Do not invent capabilities. Label design ideas as [DESIGN PROPOSAL]."
        )

    bus_block = ""
    if mode in ("ln_fab", "debug"):
        try:
            from app.websocket.cli_task_bus import task_bus_enabled

            if task_bus_enabled():
                bus_block = (
                    "\nMAC↔CLOUD TASK BUS (CLI_TASK_BUS_ENABLED): "
                    "Use task_bus_publish after significant work; task_bus_claim to pick peer reviews; "
                    "task_bus_review to post findings. sandbox_promote / git_commit auto-enqueue a "
                    "cross-CLI review when the bus is on. An autonomous consumer reviews peer tasks.\n"
                )
        except Exception:
            bus_block = ""

    return (
        f"You are Little Nate, operating as {cli_label} in {mode.upper()} mode.\n\n"
        f"{mode_instructions}\n\n"
        f"{grounding_block}\n"
        f"{bus_block}\n"
        f"CODEBASE CONTEXT:\n{manifest}\n\n"
        f"{rules}\n\n"
        "TOOL USE: Call tools by using the function calling interface. "
        "After each tool result you will see the output and can decide to call more tools or respond.\n"
        "Always be concise. When reading files, cite paths. When making changes, explain why.\n"
        "VERIFICATION: After writing files, check lint/test feedback in tool results and fix errors before finishing.\n"
        "Use repo_map for orientation before deep file reads on large tasks.\n"
        "Use self_capabilities before answering what you can do / Phase / neuro-symbolic / Mac vs Cloud.\n"
        "AGENTIC: For complex multi-step work, use todo_write to track tasks. "
        "Use spawn_subagent for scoped explore/test_fix child loops. "
        "When AUTO-PYTEST FAILED appears, fix and continue until tests pass or autonomy budget is exhausted."
        + ("" if mode not in ("ln_fab", "debug") else _queen_hive_prompt())
    )


def _queen_hive_prompt() -> str:
    try:
        from app.websocket.cli_subagent_hive import queen_system_addon
        return queen_system_addon()
    except Exception:
        return ""



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
        "run shell commands, execute git operations, and deploy (CLI-Mac only for live deploy). "
        "On CLI-Cloud, writes go to a sandboxed worktree — verify with lints/tests, call "
        "sandbox_diff, then sandbox_promote (admin) when ready. "
        "Follow the LN-FAB protocol: verify before writing, test after changes, "
        "never modify protected files without explicit approval."
    ),
}


def _session_key(admin: str, cli_type: str, mode: str, session_id: str) -> str:
    return f"{admin}:{cli_type}:{mode}:{session_id}"


def _align_keep_tail(body: List[Dict[str, Any]], min_keep: int = 8) -> List[Dict[str, Any]]:
    """Slice a keep-tail that never starts with an orphan role=tool message."""
    if len(body) <= min_keep:
        return body
    start = len(body) - min_keep
    while start > 0 and body[start].get("role") == "tool":
        start -= 1
    # If we landed inside a tool-call turn, include the owning assistant
    if body[start].get("role") == "assistant" and body[start].get("tool_calls"):
        pass
    elif start > 0 and body[start].get("role") == "tool":
        i = start
        while i > 0 and not (body[i].get("role") == "assistant" and body[i].get("tool_calls")):
            i -= 1
        if body[i].get("role") == "assistant" and body[i].get("tool_calls"):
            start = i
    return body[start:]


def _sanitize_tool_sequence(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop orphan tool messages whose parent assistant tool_calls were compacted away."""
    out: List[Dict[str, Any]] = []
    open_ids: set = set()
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            open_ids = {tc.get("id") for tc in m["tool_calls"] if tc.get("id")}
            out.append(m)
        elif role == "tool":
            tid = m.get("tool_call_id")
            if tid and tid in open_ids:
                out.append(m)
            # else drop orphan
        else:
            open_ids = set()
            out.append(m)
    return out


def _compact_conversation(conversation: List[Dict[str, Any]], max_chars: int = _CONV_COMPACT_CHARS) -> List[Dict[str, Any]]:
    """Summarize old tool outputs when context exceeds budget; keep system + recent turns."""
    total = sum(len(str(m.get("content") or "")) for m in conversation)
    if total <= max_chars or len(conversation) <= 6:
        return conversation

    system = conversation[0] if conversation and conversation[0].get("role") == "system" else None
    body = conversation[1:] if system else list(conversation)
    keep_tail = _align_keep_tail(body, min_keep=8)
    head = body[:2] if len(body) > 10 else []
    dropped = body[len(head): len(body) - len(keep_tail)]
    if not dropped:
        return conversation

    tool_names = []
    for m in dropped:
        if m.get("role") == "tool":
            tool_names.append("tool")
        elif m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                tool_names.append(tc.get("function", {}).get("name", "tool"))

    summary = {
        "role": "user",
        "content": (
            f"[CONTEXT COMPACTED: {len(dropped)} earlier messages summarized. "
            f"Prior tools used: {', '.join(tool_names[:40]) or 'n/a'}. "
            "Re-read files if you need exact prior content.]"
        ),
    }
    out: List[Dict[str, Any]] = []
    if system:
        out.append(system)
    out.extend(head)
    out.append(summary)
    out.extend(keep_tail)
    return _sanitize_tool_sequence(out)


def _truncate_tool_result(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    half = max(500, limit // 2)
    omitted = len(text) - (half * 2)
    return text[:half] + f"\n...[{omitted} chars truncated]...\n" + text[-half:]


async def _check_mac_agent_ready() -> Tuple[bool, str]:
    """Health-gate Mac write modes before the agentic loop starts."""
    try:
        from app.websocket.cli_tools import mac_agent_health
        return await mac_agent_health()
    except Exception as e:
        return False, f"Mac agent health check failed: {e}"


async def _emit(emit, msg: Dict[str, Any]) -> None:
    if emit is not None:
        await emit(msg)


def _pytest_failed(result: Dict[str, Any]) -> bool:
    ap = result.get("auto_pytest") if isinstance(result, dict) else None
    if not isinstance(ap, dict):
        return False
    if ap.get("exit_code", 0) not in (0, None) and ap.get("exit_code") != 0:
        return True
    return ap.get("status") not in (None, "ok")


def _filter_tools_by_profile(tools: List[Dict[str, Any]], profile: str) -> List[Dict[str, Any]]:
    allowed = _SUBAGENT_PROFILES.get(profile)
    if allowed is None:
        # full — drop spawn_subagent to prevent recursion
        return [
            t for t in tools
            if (t.get("function") or {}).get("name") != "spawn_subagent"
        ]
    out = []
    for t in tools:
        name = (t.get("function") or {}).get("name")
        if name and name in allowed:
            out.append(t)
    return out


async def run_agentic_loop(
    *,
    user_message: str,
    mode: str = "ln_fab",
    cli_type: str = "cloud",
    plan_id: Optional[str] = None,
    session_id: Optional[str] = None,
    admin_username: str = "api-agent",
    user_role: str = "ADMIN",
    db_pool=None,
    emit=None,
    max_turns_override: Optional[int] = None,
    allow_subagents: bool = True,
    is_subagent: bool = False,
    tools_override: Optional[List[Dict[str, Any]]] = None,
    cancel_check=None,
    llm_provider: Optional[str] = None,
    force_sandbox: bool = False,
    parent_files: Optional[List[Any]] = None,
    parent_session_key: str = "",
) -> Dict[str, Any]:
    """
    Full agentic coding loop — WebSocket CLI and partner Agents API share this.

    Features: tool loop, parallel tools, path locks, auto-lint, auto-pytest,
    retry-until-green, todo task state, spawn_subagent, autonomy budget.
    cancel_check: optional async callable() -> bool; True aborts between turns.
    llm_provider: force stream provider (workers_ai / grok) for worker ants.
    force_sandbox: worker-ant writes never touch live trees.
    """
    user_message = (user_message or "").strip()
    if not user_message:
        err = {"type": "nate_cli_chat_error", "error": "Empty message", "status": "error"}
        await _emit(emit, err)
        return err

    if mode not in ("ask", "plan", "debug", "ln_fab"):
        mode = "ask"
    if cli_type not in ("mac", "cloud"):
        cli_type = "cloud"
    if not session_id:
        session_id = str(uuid.uuid4())[:12]
    if not plan_id:
        plan_id = str(uuid.uuid4())[:12]

    # QUANTUM-CRYSTAL-ARCH — Dual-COO Queen heartbeat (peer monitors liveness)
    if not is_subagent:
        try:
            from app.websocket.cli_dual_coo import beat_queen, dual_coo_enabled

            if dual_coo_enabled():
                beat_queen(cli_type, meta={"mode": mode, "session": session_id})
        except Exception:
            pass

    max_turns = max_turns_override or _MAX_TOOL_TURNS.get(mode, 25)
    force_provider = (llm_provider or "").strip().lower() or None
    if force_provider and force_provider not in ("workers_ai", "grok", "azure"):
        force_provider = None

    try:
        from app.websocket.cli_tools import (
            execute_tool,
            format_open_todos_prompt,
            get_tool_definitions,
            get_truncation_limit,
        )
        from app.websocket.cli_prompt_budget import (
            trim_prompt_to_ceiling,
            window_cli_conversation_history,
            CLI_MAX_HISTORY_CHARS,
        )
    except ImportError as e:
        err = {"type": "nate_cli_chat_error", "error": f"CLI module import error: {e}", "status": "error"}
        await _emit(emit, err)
        return err

    _ensure_grok_config()
    if not _GROK_URL or not _GROK_KEY:
        err = {
            "type": "nate_cli_chat_error",
            "error": "No LLM provider configured (NATE_CHAT_URL/KEY missing)",
            "status": "error",
        }
        await _emit(emit, err)
        return err

    if cli_type == "mac" and mode in ("ln_fab", "debug") and not is_subagent:
        ok, detail = await _check_mac_agent_ready()
        if not ok:
            err = {
                "type": "nate_cli_chat_error",
                "error": f"CLI-Mac {mode.upper()} requires Mac agent online. {detail}",
                "error_code": "MAC_AGENT_OFFLINE",
                "status": "error",
            }
            await _emit(emit, err)
            return err

    system_prompt = _build_system_prompt(mode, cli_type)
    system_prompt, _ = trim_prompt_to_ceiling(system_prompt, user_message, "grok")
    if tools_override is not None:
        tools = list(tools_override)
    else:
        tools = get_tool_definitions(mode, cli_type)
    if is_subagent or not allow_subagents:
        tools = [t for t in tools if (t.get("function") or {}).get("name") != "spawn_subagent"]

    sk = _session_key(admin_username, cli_type, mode, session_id)
    prior = list(_SESSION_HISTORY.get(sk, []))
    if not prior and not is_subagent:
        redis_hist = await asyncio.to_thread(_load_session_from_redis, sk)
        if redis_hist:
            _SESSION_HISTORY[sk] = redis_hist
            _SESSION_HISTORY.move_to_end(sk)
            prior = list(redis_hist)
    if prior:
        hist_budget = CLI_MAX_HISTORY_CHARS * 3 if mode == "ln_fab" else CLI_MAX_HISTORY_CHARS * 2
        prior = window_cli_conversation_history(prior, max_chars=hist_budget)

    conversation: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *prior,
    ]
    todos_block = format_open_todos_prompt(plan_id)
    if todos_block:
        conversation.append({"role": "user", "content": todos_block})
    conversation.append({"role": "user", "content": user_message})

    # Sol 1–5 + extra: force capability/speculative grounding before first model turn
    grounding_temp: Optional[float] = None
    sess_key = _session_key(admin_username or "admin", cli_type, mode, session_id or plan_id or "default")
    try:
        from app.websocket.cli_grounding import (
            capability_nudge_message,
            is_capability_question,
            is_speculative_question,
            speculative_nudge_message,
        )
        from app.websocket.cli_tools import execute_tool as _exec_ground_tool

        if not is_subagent and is_capability_question(user_message):
            caps = await _exec_ground_tool(
                "self_capabilities", {}, mode=mode, cli_type=cli_type, plan_id=plan_id,
                session_key=sess_key,
            )
            caps_body = ""
            if isinstance(caps, dict):
                caps_body = caps.get("content") or caps.get("result") or json.dumps(caps, default=str)
            conversation.append({
                "role": "user",
                "content": (
                    f"{capability_nudge_message(cli_type, mode)}\n\n"
                    f"[INJECTED self_capabilities OUTPUT — answer from this only]\n{caps_body}"
                ),
            })
            tool_call_log_seed = [{
                "name": "self_capabilities",
                "args": {},
                "status": (caps or {}).get("status", "ok") if isinstance(caps, dict) else "ok",
                "duration_ms": 0,
                "injected": True,
                "evidence_excerpt": (caps_body or "")[:6000],
            }]
            grounding_temp = 0.15
        else:
            tool_call_log_seed = []
            if not is_subagent and is_speculative_question(user_message):
                conversation.append({"role": "user", "content": speculative_nudge_message()})
                grounding_temp = 0.2 if mode in ("ask", "plan") else None
    except Exception as _g_err:
        logger.debug("CLI grounding inject skipped: %s", _g_err)
        tool_call_log_seed = []

    # QUANTUM-CRYSTAL-ARCH — CLI neuro-symbolic: inject typed facts before turn 1
    try:
        from app.websocket.cli_symbol_store import (
            cli_symbolic_enabled,
            format_symbols_block,
        )

        if not is_subagent and cli_symbolic_enabled():
            clinical_extra = []
            if db_pool and admin_username:
                try:
                    from app.services.ask_nate_clinical_intelligence import _load_symbols

                    _sym_txt = await _load_symbols(db_pool, admin_username)
                    if _sym_txt:
                        clinical_extra.append(_sym_txt)
                except Exception:
                    pass
            sym_block = format_symbols_block(sess_key, extra=clinical_extra or None)
            if sym_block:
                conversation.append({"role": "user", "content": sym_block})
    except Exception as _ns_err:
        logger.debug("CLI symbolic inject skipped: %s", _ns_err)

    async def send_to_extension(msg: Dict[str, Any]) -> None:
        await _emit(emit, msg)

    await _emit(emit, {
        "type": "nate_cli_chat_status",
        "status": "thinking",
        "detail": (
            f"{mode.upper()} mode — {cli_type}"
            + (" [subagent]" if is_subagent else "")
            + (f" [{force_provider}]" if force_provider else "")
        ),
        "session_id": session_id,
        "plan_id": plan_id,
    })

    tool_call_log: List[Dict[str, Any]] = list(tool_call_log_seed)
    files_touched: List[Dict[str, str]] = []
    provider_used = force_provider or "grok"
    t0 = time.monotonic()
    max_tokens = _MAX_COMPLETION_TOKENS.get(mode, 6144)
    trunc_limit = get_truncation_limit(mode, cli_type)
    fix_attempts = 0
    grounding_regen = 0
    _CLI_MAX_GROUNDING_REGEN = int(os.getenv("CLI_MAX_GROUNDING_REGEN", "1"))
    # Per-path set so a pass on file B cannot clear an unresolved fail on file A
    pending_failed_paths: set = set()
    subagents_spawned = 0
    subagents_this_turn = 0
    subagents_by_provider: Dict[str, int] = {}
    subagent_budget_lock = asyncio.Lock()
    turn = 0
    final_text = ""
    redis_lock_owner = f"{cli_type}:{sess_key[:48]}"

    async def _cancelled() -> bool:
        if not cancel_check:
            return False
        try:
            return bool(await cancel_check())
        except Exception:
            return False

    for turn_idx in range(max_turns):
        turn = turn_idx + 1
        if await _cancelled():
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            done = {
                "type": "nate_cli_chat_done",
                "status": "cancelled",
                "plan_id": plan_id,
                "session_id": session_id,
                "mode": mode,
                "cli": cli_type,
                "provider": provider_used,
                "files": files_touched,
                "tool_calls": tool_call_log,
                "turn_count": turn,
                "elapsed_ms": elapsed_ms,
                "response_text": "",
                "autonomy": {
                    "fix_attempts": fix_attempts,
                    "max_fix_attempts": _CLI_MAX_FIX_ATTEMPTS,
                    "max_turns": max_turns,
                    "subagents_spawned": subagents_spawned,
                    "subagents_by_provider": dict(subagents_by_provider),
                    "is_subagent": is_subagent,
                    "cancelled": True,
                },
            }
            await _emit(emit, done)
            return done
        conversation = _compact_conversation(conversation)

        # Q2 — reset per-turn worker budget at the start of each LLM turn
        subagents_this_turn = 0

        try:
            response_text, response_tool_calls, provider_used = await _stream_with_tools(
                emit, conversation, tools, turn, provider_used,
                max_tokens=max_tokens, mode=mode,
                temperature=grounding_temp,
                force_provider=force_provider,
            )
        except Exception as e:
            logger.error("CLI stream error (turn %d): %s", turn, e)
            if not is_subagent:
                _persist_session(sk, conversation, user_message, f"[LLM error: {e}]")
            err = {"type": "nate_cli_chat_error", "error": f"LLM error: {e}", "status": "error"}
            await _emit(emit, err)
            return err

        if response_tool_calls:
            assistant_msg: Dict[str, Any] = {"role": "assistant", "content": response_text or ""}
            assistant_msg["tool_calls"] = response_tool_calls
            conversation.append(assistant_msg)

            async def _run_one(tc: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], int, str]:
                nonlocal subagents_spawned, subagents_this_turn
                fn = tc.get("function", {})
                tool_name = fn.get("name", "unknown")
                # Gap 6 — malformed tool-call repair (Workers AI)
                try:
                    from app.websocket.cli_subagent_hive import parse_tool_arguments
                    tool_args, _repaired, parse_err = parse_tool_arguments(fn.get("arguments", "{}"))
                except Exception:
                    try:
                        tool_args = json.loads(fn.get("arguments", "{}"))
                        parse_err = None
                    except (json.JSONDecodeError, TypeError):
                        tool_args = {}
                        parse_err = "malformed tool arguments"
                tc_id = tc.get("id", f"call_{uuid.uuid4().hex[:8]}")

                await _emit(emit, {
                    "type": "nate_cli_chat_status",
                    "status": "tool_executing",
                    "detail": tool_name,
                })

                t_start = time.monotonic()

                if parse_err and tool_name != "spawn_subagent":
                    result = {
                        "status": "error",
                        "error": (
                            f"{parse_err}. Re-call {tool_name} with valid JSON arguments."
                        ),
                        "error_code": "malformed_tool_args",
                        "retry": True,
                    }
                    t_elapsed = int((time.monotonic() - t_start) * 1000)
                    return tc, result, t_elapsed, tc_id

                if tool_name == "spawn_subagent":
                    # Q1 — workers cannot nest; Q2 — Queen budgets
                    if is_subagent or not allow_subagents:
                        result = {
                            "status": "error",
                            "error": "Nested spawn_subagent is not allowed (worker ants cannot spawn).",
                        }
                    else:
                        async with subagent_budget_lock:
                            if subagents_spawned >= _CLI_MAX_SUBAGENTS_PER_RUN:
                                result = {
                                    "status": "error",
                                    "error": (
                                        f"Subagent run budget exhausted "
                                        f"({_CLI_MAX_SUBAGENTS_PER_RUN}/run)."
                                    ),
                                    "error_code": "subagent_budget",
                                }
                                t_elapsed = int((time.monotonic() - t_start) * 1000)
                                return tc, result, t_elapsed, tc_id
                            if subagents_this_turn >= _CLI_MAX_SUBAGENTS_PER_TURN:
                                result = {
                                    "status": "error",
                                    "error": (
                                        f"Subagent turn budget exhausted "
                                        f"({_CLI_MAX_SUBAGENTS_PER_TURN}/turn)."
                                    ),
                                    "error_code": "subagent_budget",
                                }
                                t_elapsed = int((time.monotonic() - t_start) * 1000)
                                return tc, result, t_elapsed, tc_id
                            subagents_spawned += 1
                            subagents_this_turn += 1
                        result = await _run_spawn_subagent(
                            task=str(tool_args.get("task") or ""),
                            profile=str(tool_args.get("tool_profile") or "explore"),
                            parent_mode=mode,
                            cli_type=cli_type,
                            plan_id=plan_id,
                            admin_username=admin_username,
                            user_role=user_role,
                            db_pool=db_pool,
                            parent_tools=tools,
                            emit=emit,
                            provider_override=str(tool_args.get("provider") or ""),
                            parent_session_key=sess_key,
                            parent_files=files_touched + list(parent_files or []),
                        )
                        prov = (result.get("provider") if isinstance(result, dict) else None) or "?"
                        subagents_by_provider[prov] = subagents_by_provider.get(prov, 0) + 1
                    t_elapsed = int((time.monotonic() - t_start) * 1000)
                    return tc, result, t_elapsed, tc_id

                write_path = (
                    tool_args.get("path")
                    or tool_args.get("file_path")
                    or ""
                )
                lock = await _path_lock(write_path) if tool_name in _WRITE_TOOLS and write_path else None

                async def _execute_and_verify() -> Dict[str, Any]:
                    redis_paths: List[str] = []
                    # QUANTUM-CRYSTAL-ARCH — unify asyncio + Redis SETNX path locks
                    if tool_name in _WRITE_TOOLS and write_path:
                        try:
                            from app.websocket.cli_task_bus import (
                                claim_paths,
                                release_paths,
                                task_bus_enabled,
                            )

                            if task_bus_enabled():
                                redis_paths = [write_path]
                                lock_res = await asyncio.to_thread(
                                    claim_paths, redis_paths, redis_lock_owner,
                                )
                                if not lock_res.get("ok"):
                                    return {
                                        "status": "error",
                                        "error": "path_lock_conflict",
                                        "error_code": "path_lock_conflict",
                                        "blocked": lock_res.get("blocked") or redis_paths,
                                    }
                        except Exception as _pl_err:
                            logger.debug("redis path lock skipped: %s", _pl_err)
                            redis_paths = []
                    try:
                        res = await execute_tool(
                            tool_name, tool_args,
                            cli_type=cli_type,
                            user_role=user_role,
                            mode=mode,
                            db_pool=db_pool,
                            plan_id=plan_id,
                            admin_username=admin_username,
                            send_to_extension=send_to_extension,
                            session_key=sess_key,
                            tool_call_log=tool_call_log,
                            force_sandbox=force_sandbox,
                        )
                    except Exception as te:
                        res = {"status": "error", "error": str(te)}
                    finally:
                        if redis_paths:
                            try:
                                from app.websocket.cli_task_bus import release_paths

                                await asyncio.to_thread(
                                    release_paths, redis_paths, redis_lock_owner,
                                )
                            except Exception:
                                pass
                    # Gap 7 — worker writes auto-enqueue bus review
                    if (
                        force_sandbox
                        and tool_name in _WRITE_TOOLS
                        and isinstance(res, dict)
                        and res.get("status") == "ok"
                    ):
                        try:
                            from app.websocket.cli_task_bus import (
                                enqueue_review,
                                task_bus_enabled,
                            )

                            if task_bus_enabled():
                                rel = (
                                    res.get("_sandbox_rel")
                                    or tool_args.get("path")
                                    or write_path
                                    or ""
                                )
                                if rel:
                                    review = await asyncio.to_thread(
                                        enqueue_review,
                                        origin="cloud" if cli_type == "cloud" else "mac",
                                        files=[str(rel)],
                                        plan_id=str(plan_id or ""),
                                        notes="auto review after worker-ant sandbox write",
                                    )
                                    res = dict(res)
                                    res["task_bus_review"] = review
                        except Exception as _wr_enq:
                            logger.debug("worker write enqueue_review skipped: %s", _wr_enq)

                    if (
                        tool_name not in _WRITE_TOOLS
                        or not isinstance(res, dict)
                        or res.get("status") != "ok"
                        or mode not in ("ln_fab", "debug")
                    ):
                        return res

                    lint_path = (
                        res.get("path")
                        or tool_args.get("path")
                        or tool_args.get("file_path")
                        or ""
                    )
                    if not lint_path:
                        return res

                    try:
                        lint = await execute_tool(
                            "read_lints",
                            {"paths": [lint_path]},
                            cli_type=cli_type,
                            user_role=user_role,
                            mode=mode,
                            db_pool=db_pool,
                            plan_id=plan_id,
                            admin_username=admin_username,
                        )
                        if isinstance(lint, dict) and lint.get("status") == "ok":
                            diags = lint.get("diagnostics") or lint.get("result") or []
                            res = dict(res)
                            res["auto_lint"] = diags
                            if diags:
                                res["result"] = (
                                    str(res.get("result") or res.get("content") or "ok")
                                    + f"\n\n[AUTO-LINT on {lint_path}]: {json.dumps(diags, default=str)[:3000]}"
                                )
                            elif isinstance(diags, list) and len(diags) == 0:
                                res = await _maybe_auto_pytest(
                                    res, lint_path, cli_type, user_role, mode,
                                    db_pool, plan_id, admin_username,
                                )
                    except Exception as le:
                        logger.debug("auto-lint skipped: %s", le)
                    return res

                if lock is not None:
                    async with lock:
                        result = await _execute_and_verify()
                else:
                    result = await _execute_and_verify()

                t_elapsed = int((time.monotonic() - t_start) * 1000)
                return tc, result, t_elapsed, tc_id

            gathered = await asyncio.gather(
                *[_run_one(tc) for tc in response_tool_calls],
                return_exceptions=False,
            )

            # Do NOT clear pending_failed_paths here — a later read-only tool
            # must not erase a prior auto_pytest failure (retry-until-green).
            # Clear only the path that just passed.
            for tc, result, t_elapsed, tc_id in gathered:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "unknown")
                try:
                    tool_args = json.loads(fn.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    tool_args = {}

                status = result.get("status", "ok") if isinstance(result, dict) else "ok"
                result_text = _truncate_tool_result(_format_tool_result(result), trunc_limit)
                preview = result_text[:500] + ("..." if len(result_text) > 500 else "")

                if isinstance(result, dict):
                    ap = result.get("auto_pytest")
                    path_key = ""
                    if isinstance(ap, dict):
                        path_key = (
                            ap.get("target")
                            or ap.get("source")
                            or result.get("path")
                            or ""
                        )
                    if _pytest_failed(result):
                        pending_failed_paths.add(path_key or f"unknown:{tool_name}")
                    elif (
                        isinstance(ap, dict)
                        and ap.get("status") == "ok"
                        and int(ap.get("exit_code") or 0) == 0
                        and path_key
                    ):
                        pending_failed_paths.discard(path_key)

                await _emit(emit, {
                    "type": "nate_cli_chat_tool",
                    "tool_name": tool_name,
                    "tool_input": tool_args,
                    "tool_output_preview": preview,
                    "status": status,
                    "duration_ms": t_elapsed,
                    "turn": turn,
                })

                # Keep truncated evidence for post-response citation audit
                _ev = ""
                if isinstance(result, dict):
                    _ev = str(
                        result.get("content")
                        or result.get("result")
                        or result.get("output")
                        or ""
                    )
                else:
                    _ev = str(result or "")
                tool_call_log.append({
                    "name": tool_name,
                    "args": {k: v for k, v in tool_args.items() if not str(k).startswith("_")},
                    "status": status,
                    "duration_ms": t_elapsed,
                    "evidence_excerpt": (_ev or result_text or "")[:6000],
                })
                # QUANTUM-CRYSTAL-ARCH — auto-assert typed facts from tool results
                try:
                    from app.websocket.cli_symbol_store import auto_assert_from_tool

                    auto_assert_from_tool(sess_key, tool_name, tool_args, result)
                except Exception:
                    pass

                if tool_name in ("write_file", "str_replace", "delete_file"):
                    path = (
                        (result.get("_sandbox_rel") if isinstance(result, dict) else None)
                        or tool_args.get("path")
                        or tool_args.get("file_path")
                        or ""
                    )
                    action = "write" if tool_name != "delete_file" else "delete"
                    if path:
                        files_touched.append({"path": path, "action": action})

                conversation.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_text,
                })

            await _emit(emit, {
                "type": "nate_cli_chat_status",
                "status": "thinking",
                "detail": "Processing tool results...",
            })
            if await _cancelled():
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                done = {
                    "type": "nate_cli_chat_done",
                    "status": "cancelled",
                    "plan_id": plan_id,
                    "session_id": session_id,
                    "mode": mode,
                    "cli": cli_type,
                    "provider": provider_used,
                    "files": files_touched,
                    "tool_calls": tool_call_log,
                    "turn_count": turn,
                    "elapsed_ms": elapsed_ms,
                    "response_text": "",
                    "autonomy": {
                        "fix_attempts": fix_attempts,
                        "max_fix_attempts": _CLI_MAX_FIX_ATTEMPTS,
                        "max_turns": max_turns,
                        "subagents_spawned": subagents_spawned,
                        "subagents_by_provider": dict(subagents_by_provider),
                        "is_subagent": is_subagent,
                        "cancelled": True,
                    },
                }
                await _emit(emit, done)
                return done
            continue

        # Final text — retry-until-green if tests still failing and budget remains
        if (
            pending_failed_paths
            and fix_attempts < _CLI_MAX_FIX_ATTEMPTS
            and mode in ("ln_fab", "debug")
            and not is_subagent
        ):
            fix_attempts += 1
            failed_list = ", ".join(sorted(pending_failed_paths)[:8])
            conversation.append({"role": "assistant", "content": response_text or ""})
            conversation.append({
                "role": "user",
                "content": (
                    f"[AUTONOMY BUDGET] Auto-pytest still failing on: {failed_list} "
                    f"(fix attempt {fix_attempts}/{_CLI_MAX_FIX_ATTEMPTS}). "
                    "Read the failure output in prior tool results, fix the code, "
                    "and continue until tests pass or the budget is exhausted. "
                    "Do not conclude yet."
                ),
            })
            await _emit(emit, {
                "type": "nate_cli_chat_status",
                "status": "thinking",
                "detail": f"Retry-until-green {fix_attempts}/{_CLI_MAX_FIX_ATTEMPTS}",
            })
            continue

        final_text = response_text or ""
        grounding_meta: Dict[str, Any] = {"ok": True, "violation_count": 0, "violations": []}
        if not is_subagent:
            try:
                from app.websocket.cli_grounding import apply_grounding_to_done
                final_text, grounding_meta = apply_grounding_to_done(
                    final_text, tool_call_log, user_message, session_key=sess_key,
                )
            except Exception as ge:
                logger.debug("CLI grounding validate skipped: %s", ge)
            # QUANTUM-CRYSTAL-ARCH — enforce symbolic_verify via one regen turn
            if (
                grounding_meta.get("needs_regen")
                and grounding_regen < _CLI_MAX_GROUNDING_REGEN
                and mode in ("ln_fab", "debug", "ask")
            ):
                grounding_regen += 1
                viol_txt = "; ".join(
                    str(v.get("detail") or v.get("type") or v)
                    for v in (grounding_meta.get("violations") or [])[:6]
                )
                conversation.append({"role": "assistant", "content": final_text or ""})
                conversation.append({
                    "role": "user",
                    "content": (
                        f"[GROUNDING REGEN {grounding_regen}/{_CLI_MAX_GROUNDING_REGEN}] "
                        f"Server symbolic/grounding check failed: {viol_txt}. "
                        "Call self_capabilities and/or symbolic_verify, correct contradictions, "
                        "and reply again without false capability claims."
                    ),
                })
                await _emit(emit, {
                    "type": "nate_cli_chat_status",
                    "status": "thinking",
                    "detail": f"Grounding regen {grounding_regen}/{_CLI_MAX_GROUNDING_REGEN}",
                })
                continue
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if not is_subagent:
            _persist_session(sk, conversation, user_message, final_text)
        done_msg: Dict[str, Any] = {
            "type": "nate_cli_chat_done",
            "status": "ok",
            "plan_id": plan_id,
            "session_id": session_id,
            "mode": mode,
            "cli": cli_type,
            "provider": provider_used,
            "files": files_touched,
            "tool_calls": tool_call_log,
            "turn_count": turn,
            "elapsed_ms": elapsed_ms,
            "response_text": final_text[:12000],
            "grounding": grounding_meta,
            "autonomy": {
                "fix_attempts": fix_attempts,
                "max_fix_attempts": _CLI_MAX_FIX_ATTEMPTS,
                "max_turns": max_turns,
                "subagents_spawned": subagents_spawned,
                "subagents_by_provider": dict(subagents_by_provider),
                "is_subagent": is_subagent,
            },
        }
        if cli_type == "cloud" and mode == "ln_fab" and files_touched:
            try:
                from app.websocket.cli_tools import _sandbox_diff_sync
                diff = await asyncio.to_thread(_sandbox_diff_sync, plan_id, 20)
                done_msg["sandbox"] = {
                    "plan_id": plan_id,
                    "files": (diff or {}).get("files") or [],
                    "preview": str((diff or {}).get("result") or "")[:4000],
                }
            except Exception as se:
                logger.debug("sandbox summary skipped: %s", se)
        await _emit(emit, done_msg)
        return done_msg

    grounding_meta = {"ok": True, "violation_count": 0, "violations": []}
    if not is_subagent:
        try:
            from app.websocket.cli_grounding import apply_grounding_to_done
            final_text, grounding_meta = apply_grounding_to_done(
                final_text, tool_call_log, user_message, session_key=sess_key,
            )
        except Exception as ge:
            logger.debug("CLI grounding validate skipped: %s", ge)
        _persist_session(sk, conversation, user_message, final_text)
    done_msg = {
        "type": "nate_cli_chat_done",
        "status": "ok",
        "plan_id": plan_id,
        "session_id": session_id,
        "mode": mode,
        "cli": cli_type,
        "provider": provider_used,
        "files": files_touched,
        "tool_calls": tool_call_log,
        "turn_count": turn,
        "elapsed_ms": int((time.monotonic() - t0) * 1000),
        "response_text": final_text[:12000],
        "grounding": grounding_meta,
        "warning": f"Reached max tool turns ({max_turns})",
        "autonomy": {
            "fix_attempts": fix_attempts,
            "max_fix_attempts": _CLI_MAX_FIX_ATTEMPTS,
            "max_turns": max_turns,
            "subagents_spawned": subagents_spawned,
            "subagents_by_provider": dict(subagents_by_provider),
            "budget_exhausted": True,
            "is_subagent": is_subagent,
        },
    }
    await _emit(emit, done_msg)
    return done_msg


async def _run_spawn_subagent(
    *,
    task: str,
    profile: str,
    parent_mode: str,
    cli_type: str,
    plan_id: str,
    admin_username: str,
    user_role: str,
    db_pool,
    parent_tools: List[Dict[str, Any]],
    emit,
    provider_override: str = "",
    parent_session_key: str = "",
    parent_files: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Scoped worker-ant loop — Queen (parent) reviews output.
    Gaps 1–8 + Q1–Q4: provider tiering, escalate, cite audit, structured contract,
    brief injection, sandbox writes, attribution. Nesting forbidden (allow_subagents=False).
    """
    from app.websocket.cli_subagent_hive import (
        build_worker_brief,
        child_needs_escalation,
        resolve_subagent_provider,
        structure_subagent_result,
        tag_summary_for_queen,
        worker_must_sandbox,
    )

    if not task.strip():
        return {"status": "error", "error": "spawn_subagent requires a non-empty task"}
    if profile not in _SUBAGENT_PROFILES:
        profile = "explore"
    child_mode = parent_mode if profile != "explore" else ("ask" if parent_mode in ("ask", "plan") else parent_mode)
    if profile == "explore" and parent_mode in ("ln_fab", "debug"):
        child_mode = "ask"
    if profile == "test_fix":
        child_mode = "ln_fab" if parent_mode in ("ln_fab", "debug") else parent_mode

    provider = resolve_subagent_provider(profile, provider_override)
    force_sb = worker_must_sandbox(provider, profile)
    # Gap 7: write workers always run cloud+ln_fab surface for sandbox remap
    child_cli = "cloud" if force_sb else cli_type
    if force_sb and child_mode not in ("ln_fab", "debug"):
        child_mode = "ln_fab"

    child_tools = _filter_tools_by_profile(parent_tools, profile)
    brief = build_worker_brief(
        task,
        profile=profile,
        plan_id=plan_id,
        session_key=parent_session_key,
        parent_files=parent_files,
    )
    events: List[Dict[str, Any]] = []

    async def child_emit(msg: Dict[str, Any]) -> None:
        events.append({"type": msg.get("type"), "detail": msg.get("detail") or msg.get("tool_name")})
        wrapped = dict(msg)
        wrapped["subagent"] = True
        wrapped["subagent_profile"] = profile
        wrapped["subagent_provider"] = provider
        await _emit(emit, wrapped)

    async def _run_child(prov: str) -> Dict[str, Any]:
        return await run_agentic_loop(
            user_message=brief,
            mode=child_mode,
            cli_type=child_cli,
            plan_id=plan_id,
            session_id=f"sub-{uuid.uuid4().hex[:8]}",
            admin_username=admin_username,
            user_role=user_role,
            db_pool=db_pool,
            emit=child_emit,
            max_turns_override=_CLI_MAX_SUBAGENT_TURNS,
            allow_subagents=False,  # Q1 — no nested spawn
            is_subagent=True,
            tools_override=child_tools,
            llm_provider=prov,
            force_sandbox=force_sb or (prov == "workers_ai" and profile in ("test_fix", "full")),
            parent_files=parent_files,
            parent_session_key=parent_session_key,
        )

    result = await _run_child(provider)
    escalated = False
    # Gap 2 / Q4 — one Grok escalation if Workers AI flails
    if provider == "workers_ai" and child_needs_escalation(result):
        await _emit(emit, {
            "type": "nate_cli_chat_status",
            "status": "thinking",
            "detail": f"Worker escalate → grok ({profile})",
        })
        result = await _run_child("grok")
        escalated = True
        provider = "grok"

    summary = (result.get("response_text") or "")[:4000]
    tool_log = result.get("tool_calls") or []
    # Gap 3 — Queen citation audit on child output
    cite_meta: Dict[str, Any] = {"ok": True, "violations": []}
    try:
        from app.websocket.cli_grounding import audit_verified_citations

        cite_meta = audit_verified_citations(summary, tool_log)
        summary = tag_summary_for_queen(summary, cite_meta)
        result = dict(result)
        result["response_text"] = summary
    except Exception as _cite_err:
        logger.debug("subagent cite audit skipped: %s", _cite_err)

    return structure_subagent_result(
        profile=profile,
        provider=provider,
        escalated=escalated,
        result=result,
        events=events,
        cite_meta=cite_meta,
    )


async def handle_nate_cli_chat(
    websocket,
    data: Dict[str, Any],
    current_profile: Dict[str, Any],
    db_pool=None,
):
    """WebSocket entry — delegates to shared run_agentic_loop."""
    mode = data.get("mode", "ask")
    cli_type = data.get("cli", "cloud")
    user_message = (data.get("message") or "").strip()
    session_id = (data.get("session_id") or data.get("context", {}).get("session_id") or "").strip()
    plan_id = (
        data.get("plan_id")
        or (data.get("context") or {}).get("plan_id")
        or str(uuid.uuid4())[:12]
    )
    admin_username = current_profile.get("username", "unknown")
    user_role = current_profile.get("role", "ADMIN")

    async def emit(msg: Dict[str, Any]) -> None:
        await _send(websocket, msg)

    await run_agentic_loop(
        user_message=user_message,
        mode=mode,
        cli_type=cli_type,
        plan_id=plan_id,
        session_id=session_id or None,
        admin_username=admin_username,
        user_role=user_role,
        db_pool=db_pool,
        emit=emit,
        allow_subagents=True,
        is_subagent=False,
    )


def _persist_session(
    sk: str,
    conversation: List[Dict[str, Any]],
    user_message: str,
    assistant_text: str,
) -> None:
    """Keep a sliding window of user/assistant turns; LRU-evict; mirror to Redis."""
    if sk in _SESSION_HISTORY:
        _SESSION_HISTORY.move_to_end(sk)
    hist = _SESSION_HISTORY.setdefault(sk, [])
    hist.append({"role": "user", "content": user_message})
    if assistant_text:
        hist.append({"role": "assistant", "content": assistant_text[:8000]})
    if len(hist) > _SESSION_HISTORY_MAX:
        _SESSION_HISTORY[sk] = hist[-_SESSION_HISTORY_MAX:]
        hist = _SESSION_HISTORY[sk]
    while len(_SESSION_HISTORY) > _SESSION_HISTORY_KEYS_MAX:
        _SESSION_HISTORY.popitem(last=False)
    _save_session_to_redis(sk, hist)


async def _maybe_auto_pytest(
    result: Dict[str, Any],
    lint_path: str,
    cli_type: str,
    user_role: str,
    mode: str,
    db_pool,
    plan_id: Optional[str],
    admin_username: str,
) -> Dict[str, Any]:
    """Sol 3: after lint-clean write, run targeted pytest if a test file exists."""
    if os.getenv("CLI_AUTO_PYTEST", "1") not in ("1", "true", "TRUE", "yes"):
        return result
    try:
        from app.websocket.cli_tools import execute_tool, infer_test_path_for_source
    except ImportError:
        return result
    test_target = infer_test_path_for_source(lint_path)
    if not test_target:
        return result
    cmd = f"python3 -m pytest {test_target} -q --tb=line -x"
    try:
        test_res = await execute_tool(
            "shell",
            {"command": cmd, "block_until_ms": 90000, "description": f"auto-pytest {test_target}"},
            cli_type=cli_type,
            user_role=user_role,
            mode=mode,
            db_pool=db_pool,
            plan_id=plan_id,
            admin_username=admin_username,
        )
    except Exception as te:
        logger.debug("auto-pytest skipped: %s", te)
        return result
    result = dict(result)
    result["auto_pytest"] = {
        "target": test_target,
        "source": lint_path,
        "status": (test_res or {}).get("status"),
        "exit_code": (test_res or {}).get("exit_code"),
    }
    out = str((test_res or {}).get("result") or "")
    err = str((test_res or {}).get("stderr") or "")
    combined = (out + ("\n" + err if err else ""))[:4000]
    if (test_res or {}).get("status") != "ok" or (test_res or {}).get("exit_code", 0) != 0:
        result["result"] = (
            str(result.get("result") or result.get("content") or "ok")
            + f"\n\n[AUTO-PYTEST FAILED on {test_target}]:\n{combined}"
        )
    else:
        result["result"] = (
            str(result.get("result") or result.get("content") or "ok")
            + f"\n\n[AUTO-PYTEST PASSED on {test_target}]"
        )
    return result


def _azure_chat_url_and_headers() -> Tuple[str, Dict[str, str]]:
    endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip().rstrip("/")
    key = os.getenv("AZURE_API_KEY") or ""
    deploy = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT") or "gpt-4o"
    if not endpoint or not key:
        raise RuntimeError("Azure fallback not configured (AZURE_OPENAI_ENDPOINT / AZURE_API_KEY)")
    if not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"
    api_ver = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")
    url = f"{endpoint}/openai/deployments/{deploy}/chat/completions?api-version={api_ver}"
    return url, {"api-key": key, "Content-Type": "application/json"}


def _token_limit_fields(prov: str, model: str, max_tokens: int) -> Dict[str, Any]:
    """Sol 2: Azure gpt-4o needs max_tokens; gpt-5/o-series use max_completion_tokens."""
    m = (model or "").lower()
    if prov == "azure":
        if any(x in m for x in ("gpt-5", "o1", "o3", "o4", "reasoning")):
            return {"max_completion_tokens": max_tokens}
        return {"max_tokens": max_tokens}
    return {"max_completion_tokens": max_tokens}


async def _stream_with_tools(
    emit,
    conversation: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    turn: int,
    provider: str,
    max_tokens: int = 4096,
    mode: str = "ask",
    temperature: Optional[float] = None,
    force_provider: Optional[str] = None,
) -> tuple:
    """
    Mode-aware provider routing + Azure param adaptation.
    Returns (accumulated_text, tool_calls_list, provider_name).
    `emit` is an async callback (WebSocket or Agents API event sink).
    force_provider: workers_ai | grok | azure — used by worker-ant subagents.
    """
    import aiohttp

    _ensure_grok_config()

    openai_tools = []
    for t_def in tools:
        if t_def.get("type") == "web_search" and "function" not in t_def:
            continue  # legacy bare type — never send
        if "function" in t_def:
            openai_tools.append(t_def)
        elif "name" in t_def:
            openai_tools.append({"type": "function", "function": t_def})

    messages_for_api = _convert_conversation(conversation)
    # Sol 5: lower temp for capability/speculative grounding; default 0.3
    stream_temp = 0.3 if temperature is None else float(temperature)

    async def _do_stream(url: str, headers: Dict[str, str], model: str, prov: str) -> tuple:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages_for_api,
            "stream": True,
        }
        # Reasoning-class Azure models often reject temperature
        if not (prov == "azure" and any(x in (model or "").lower() for x in ("o1", "o3", "o4"))):
            payload["temperature"] = stream_temp
        payload.update(_token_limit_fields(prov, model, max_tokens))
        if openai_tools:
            payload["tools"] = openai_tools
            payload["tool_choice"] = "auto"

        accumulated_text = ""
        tool_calls_accum: Dict[int, Dict[str, Any]] = {}

        timeout = aiohttp.ClientTimeout(total=300, sock_read=180)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"{prov} {resp.status}: {body[:400]}")

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

                    content = delta.get("content") or ""
                    if content:
                        accumulated_text += content
                        await _emit(emit, {
                            "type": "nate_cli_chat_chunk",
                            "delta": content,
                            "provider": prov,
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
        return accumulated_text, tool_calls_list, prov

    grok_headers = {
        "api-key": _GROK_KEY,
        "Content-Type": "application/json",
    }
    grok_url = _GROK_URL
    grok_model = _GROK_MODEL or "grok"
    # Sol 1 / Phase A0: LN-FAB/DEBUG → grok-4.5 (or Azure primary); ASK/PLAN → fast Grok
    prefer_azure_primary = False
    if mode in _REASONING_MODES:
        if _GROK_REASONING_MODEL:
            grok_model = _GROK_REASONING_MODEL
            # Optional separate xAI/Foundry endpoint for code model (does not clobber clinical)
            code_url = (os.getenv("NATE_CLI_CODE_URL") or "").strip()
            code_key = (
                os.getenv("NATE_CLI_CODE_KEY")
                or os.getenv("XAI_API_KEY")
                or ""
            ).strip()
            if code_url and code_key:
                grok_url = code_url
                grok_headers = {
                    "Authorization": f"Bearer {code_key}",
                    "Content-Type": "application/json",
                }
                # xAI chat completions accept api-key-style too; keep Bearer primary
            elif code_key and not code_url:
                grok_headers = {
                    "Authorization": f"Bearer {code_key}",
                    "api-key": code_key,
                    "Content-Type": "application/json",
                }
        else:
            prefer_azure_primary = os.getenv("CLI_REASONING_PREFER_AZURE", "1") in (
                "1", "true", "TRUE", "yes",
            )
    logger.info(
        "CLI stream mode=%s model=%s prefer_azure=%s",
        mode, grok_model, prefer_azure_primary,
    )

    async def _try_azure() -> tuple:
        azure_url, azure_headers = _azure_chat_url_and_headers()
        deploy = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT") or "gpt-4o"
        return await _do_stream(azure_url, azure_headers, deploy, "azure")

    async def _try_workers_ai() -> tuple:
        # QUANTUM-CRYSTAL-ARCH — Gap 1: Workers AI worker-ant stream (+ non-stream fallback)
        w_url = os.getenv("WORKERS_AI_URL", "").strip()
        w_tok = (
            os.getenv("WORKERS_AI_TOKEN", "").strip()
            or os.getenv("WORKERS_AI_API_TOKEN", "").strip()
        )
        w_model = os.getenv(
            "WORKERS_AI_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        )
        if not w_url or not w_tok:
            raise RuntimeError("WORKERS_AI_URL/TOKEN not configured")
        headers = {
            "Authorization": f"Bearer {w_tok}",
            "Content-Type": "application/json",
        }
        try:
            return await _do_stream(w_url, headers, w_model, "workers_ai")
        except Exception as stream_err:
            logger.warning("Workers AI stream failed, non-stream fallback: %s", stream_err)
            payload: Dict[str, Any] = {
                "model": w_model,
                "messages": messages_for_api,
                "temperature": stream_temp,
                "max_tokens": max_tokens,
            }
            if openai_tools:
                payload["tools"] = openai_tools
                payload["tool_choice"] = "auto"
            timeout = aiohttp.ClientTimeout(total=180)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(w_url, json=payload, headers=headers) as resp:
                    body = await resp.json(content_type=None)
                    if resp.status != 200:
                        raise RuntimeError(
                            f"workers_ai {resp.status}: {str(body)[:400]}"
                        )
                    msg = ((body.get("choices") or [{}])[0].get("message")) or {}
                    text = msg.get("content") or ""
                    raw_tcs = msg.get("tool_calls") or []
                    if text:
                        await _emit(emit, {
                            "type": "nate_cli_chat_chunk",
                            "delta": text,
                            "provider": "workers_ai",
                            "turn": turn,
                        })
                    return text, raw_tcs, "workers_ai"

    # Gap 1 — forced provider for worker ants (escalate path uses force_provider=grok)
    if force_provider == "workers_ai":
        try:
            return await _try_workers_ai()
        except Exception as w_err:
            logger.warning("Workers AI failed, falling back to Grok: %s", w_err)
            return await _do_stream(grok_url, grok_headers, grok_model, "grok")
    if force_provider == "azure":
        return await _try_azure()
    if force_provider == "grok":
        return await _do_stream(grok_url, grok_headers, grok_model, "grok")

    if prefer_azure_primary:
        try:
            return await _try_azure()
        except Exception as azure_err:
            logger.warning("Azure primary (reasoning mode) failed, trying Grok: %s", azure_err)
            try:
                return await _do_stream(grok_url, grok_headers, grok_model, "grok")
            except Exception as grok_err:
                raise RuntimeError(
                    f"Azure primary failed ({azure_err}); Grok fallback failed ({grok_err})"
                ) from grok_err

    try:
        return await _do_stream(grok_url, grok_headers, grok_model, "grok")
    except Exception as grok_err:
        logger.warning("Grok stream failed, trying Azure fallback: %s", grok_err)
        try:
            return await _try_azure()
        except Exception as azure_err:
            raise RuntimeError(f"Grok failed ({grok_err}); Azure fallback failed ({azure_err})") from azure_err


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
        # QUANTUM-CRYSTAL-ARCH — surface truncation so models do not treat samples as exhaustive
        warning = result.get("warning")
        prefix = ""
        if warning:
            prefix = f"[DISCOVERY WARNING] {warning}\n"
        elif result.get("truncated"):
            prefix = (
                "[DISCOVERY WARNING] Results truncated — not exhaustive; "
                "narrow path/glob before concluding absence.\n"
            )
        output = result.get("output") or result.get("content") or result.get("result", "")
        if isinstance(output, str):
            return prefix + output if prefix else output
        body = json.dumps(result, indent=2, default=str)
        return prefix + body if prefix else body
    return str(result)


async def _send(websocket, msg: Dict[str, Any]):
    """Send a JSON message, swallowing connection errors."""
    try:
        await websocket.send(json.dumps(msg, default=str))
    except Exception:
        pass
