"""
QUANTUM-CRYSTAL-ARCH: Nate tool propose/confirm executor (Agentic Phase 2).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger("nate.tool_executor")

_PENDING_TTL_SECONDS = 600
# QUANTUM-CRYSTAL-ARCH: confirm only clear yes — not "I'm not sure" / soft story "ok"
_YES_RE = re.compile(
    r"^(yes|yeah|yep|yup|go ahead|do it|please do)[.!]?\s*$"
    r"|\b(yes|yeah|yep)[,!]?\s+(please|do it|go ahead|confirm|book|schedule)\b"
    r"|\b(sure|ok(?:ay)?)[,!]?\s+(do it|go ahead|please|confirm|book|schedule)\b"
    r"|\bsounds good[,!]?\s*(do it|go ahead|please)?\s*$",
    re.I,
)
_NO_RE = re.compile(
    r"\b(no|nope|never\s?mind|nevermind|cancel|don't|do not|stop)\b",
    re.I,
)

# Coach-referent only — never match clinical "schedule an appointment with …"
_COACH_BOOK_RE = re.compile(
    r"\b(?:book|schedule|set up)\b.{0,40}\b(?:with|my)\s+coach\b"
    r"|\b(?:book|schedule|set up)\b.{0,40}\b(?:session|coaching)\b.{0,24}\bcoach\b",
    re.I,
)
_BOOK_REDIRECT_TEXT = (
    "I can't book or approve sessions — your coach does that. "
    "Open Schedule and pick a time from your coach's published availability."
)
_REMIND_RE = re.compile(
    r"\bremind me\b(?:\s+to\b|\s+about\b)?\s+(.+)",
    re.I,
)
_SET_REMINDER_RE = re.compile(
    r"\b(?:set|create)\b.{0,20}\breminder\b(?:\s+(?:to|for|about)\b)?\s*(.+)?",
    re.I,
)
_RESOURCE_RE = re.compile(
    r"\b(?:send|queue|share)\b.{0,30}\b(?:resource|article|reading|worksheet)\b"
    r"(?:\s+(?:on|about|for)\b)?\s*(.+)?",
    re.I,
)
_ISO_DT_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?(?:Z|[+-]\d{2}:?\d{2})?)\b"
)
_RELATIVE_DAY_RE = re.compile(
    r"\b(tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.I,
)

# In-memory fallback when Redis unavailable
_memory_pending: Dict[str, Dict[str, Any]] = {}


def tool_executor_enabled() -> bool:
    return os.getenv("ENABLE_NATE_TOOL_EXECUTOR", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


async def _resolve_user_uuid(db_pool: Any, hw_id: str) -> Optional[Any]:
    if not db_pool or not hw_id:
        return None
    try:
        async with db_pool.acquire() as conn:
            return await conn.fetchval(
                """
                SELECT id FROM users
                WHERE hardware_id = $1 OR username = $1
                LIMIT 1
                """,
                hw_id,
            )
    except Exception as e:
        logger.warning("tool_executor: resolve user uuid failed: %s", e)
        return None


async def _book_session_executor(
    db_pool: Any, hw_id: str, params: Dict[str, Any]
) -> Dict[str, Any]:
    """Never persist. Coach decides; clients request via availability UI."""
    del db_pool, hw_id, params
    return {
        "success": False,
        "error": "coach_decision_required",
        "message": _BOOK_REDIRECT_TEXT,
    }


async def _set_reminder_executor(
    db_pool: Any, hw_id: str, params: Dict[str, Any]
) -> Dict[str, Any]:
    """Persist reminder to nate_nudges (content column; user_id = users.id UUID)."""
    reminder_text = (params.get("text") or params.get("message") or "").strip()
    scheduled_at = params.get("scheduled_at")
    if not reminder_text or not scheduled_at:
        return {"success": False, "error": "missing_reminder_fields"}
    if not db_pool:
        return {"success": False, "error": "database_unavailable"}
    try:
        sched_dt = datetime.fromisoformat(str(scheduled_at).replace("Z", "+00:00"))
    except Exception:
        return {"success": False, "error": "invalid_scheduled_at"}

    user_uuid = await _resolve_user_uuid(db_pool, hw_id)
    if not user_uuid:
        return {"success": False, "error": "user_not_found"}
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO nate_nudges
                    (user_id, nudge_type, title, content, status, scheduled_at, metadata)
                VALUES ($1, 'tool_reminder', 'Reminder from Nate', $2, 'pending', $3,
                        jsonb_build_object('source', 'nate_tool_executor', 'hw_id', $4::text))
                RETURNING id
                """,
                user_uuid,
                reminder_text[:2000],
                sched_dt,
                hw_id,
            )
        return {
            "success": True,
            "status": "scheduled",
            "nudge_id": str(row["id"]) if row else None,
            "user_id": hw_id,
            "text": reminder_text[:500],
            "scheduled_at": sched_dt.isoformat(),
        }
    except Exception as e:
        logger.warning("tool_executor: set_reminder insert failed: %s", e)
        return {"success": False, "error": "reminder_persist_failed", "detail": str(e)[:200]}


async def _queue_resource_executor(
    db_pool: Any, hw_id: str, params: Dict[str, Any]
) -> Dict[str, Any]:
    resource = (params.get("resource_id") or params.get("topic") or "").strip()
    if not resource:
        return {"success": False, "error": "missing_resource"}
    if not db_pool:
        return {"success": False, "error": "database_unavailable"}
    user_uuid = await _resolve_user_uuid(db_pool, hw_id)
    if not user_uuid:
        return {"success": False, "error": "user_not_found"}
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO nate_nudges
                    (user_id, nudge_type, title, content, status, scheduled_at, metadata)
                VALUES ($1, 'queued_resource', 'Resource from Nate', $2, 'pending', NOW(),
                        jsonb_build_object('source', 'nate_tool_executor',
                                          'resource', $3::text, 'hw_id', $4::text))
                RETURNING id
                """,
                user_uuid,
                f"Queued resource: {resource[:500]}",
                resource[:200],
                hw_id,
            )
        return {
            "success": True,
            "status": "queued",
            "nudge_id": str(row["id"]) if row else None,
            "user_id": hw_id,
            "resource": resource[:200],
        }
    except Exception as e:
        logger.warning("tool_executor: queue_resource insert failed: %s", e)
        return {"success": False, "error": "resource_persist_failed", "detail": str(e)[:200]}


NATE_TOOLS: Dict[str, Dict[str, Any]] = {
    "book_session": {
        "description": "Disabled — clients request via Schedule; coach approves",
        "param_schema": {
            "slot_start": "ISO8601 datetime",
            "coach_id": "optional coach hardware id",
            "session_type": "individual|family|group",
            "notes": "optional string",
        },
        "executor_fn": _book_session_executor,
    },
    "set_reminder": {
        "description": "Schedule an in-app reminder via nate_nudges",
        "param_schema": {
            "text": "reminder message",
            "scheduled_at": "ISO8601 datetime",
        },
        "executor_fn": _set_reminder_executor,
    },
    "queue_resource": {
        "description": "Queue a psychoeducation resource for the client",
        "param_schema": {"resource_id": "string or topic"},
        "executor_fn": _queue_resource_executor,
    },
}


def _pending_key(hw_id: str) -> str:
    return f"nate:tool_pending:{hw_id}"


async def _redis_get(redis_client: Any, key: str) -> Optional[str]:
    if not redis_client:
        return None
    try:
        import asyncio

        get_fn = redis_client.get
        if asyncio.iscoroutinefunction(get_fn):
            val = await get_fn(key)
        else:
            val = await asyncio.to_thread(get_fn, key)
        if val is None:
            return None
        return val.decode() if isinstance(val, bytes) else str(val)
    except Exception as e:
        logger.warning("tool_executor: redis get failed: %s", e)
        return None


async def _redis_setex(redis_client: Any, key: str, payload: str) -> bool:
    if not redis_client:
        return False
    try:
        import asyncio

        setex_fn = redis_client.setex
        if asyncio.iscoroutinefunction(setex_fn):
            await setex_fn(key, _PENDING_TTL_SECONDS, payload)
        else:
            await asyncio.to_thread(setex_fn, key, _PENDING_TTL_SECONDS, payload)
        return True
    except Exception as e:
        logger.warning("tool_executor: redis setex failed: %s", e)
        return False


async def _redis_delete(redis_client: Any, key: str) -> None:
    if not redis_client:
        return
    try:
        import asyncio

        del_fn = redis_client.delete
        if asyncio.iscoroutinefunction(del_fn):
            await del_fn(key)
        else:
            await asyncio.to_thread(del_fn, key)
    except Exception:
        pass


def _default_slot_start(user_text: str) -> str:
    """ISO slot: explicit ISO in text, else tomorrow 10:00 UTC."""
    m = _ISO_DT_RE.search(user_text or "")
    if m:
        raw = m.group(1).replace(" ", "T")
        try:
            datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return raw if "T" in raw or " " in m.group(1) else f"{raw}T10:00:00+00:00"
        except Exception:
            pass
    base = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    if re.search(r"\btoday\b", user_text or "", re.I):
        return base.isoformat()
    return (base + timedelta(days=1)).isoformat()


def detect_tool_intent(user_text: str) -> Optional[Dict[str, Any]]:
    """
    Heuristic propose detector. Returns tool_name, params, confirmation prompt.
    Does not store pending — caller must call propose_tool_action.
    """
    text = (user_text or "").strip()
    if not text or len(text) < 8:
        return None

    m = _REMIND_RE.search(text) or _SET_REMINDER_RE.search(text)
    if m:
        body = (m.group(1) or text).strip()[:500]
        if len(body) < 3:
            body = text[:500]
        when = _default_slot_start(text)
        return {
            "tool_name": "set_reminder",
            "params": {"text": body, "scheduled_at": when},
            "prompt": (
                f'I can set a reminder for "{body[:120]}" around {when}. '
                "Say yes to save it, or no to cancel."
            ),
        }

    m = _RESOURCE_RE.search(text)
    if m:
        topic = (m.group(1) or "general").strip()[:200] or "general"
        return {
            "tool_name": "queue_resource",
            "params": {"topic": topic},
            "prompt": (
                f'I can queue a resource about "{topic}" for you. '
                "Say yes to queue it, or no to cancel."
            ),
        }

    return None


async def propose_tool_action(
    hw_id: str,
    conversation_id: str,
    tool_name: str,
    params: Dict[str, Any],
    *,
    redis_client: Any = None,
) -> Dict[str, Any]:
    if not tool_executor_enabled():
        return {"proposed": False, "reason": "disabled"}
    if tool_name == "book_session":
        return {"proposed": False, "reason": "coach_decision_required"}
    if tool_name not in NATE_TOOLS:
        return {"proposed": False, "reason": "unknown_tool"}

    pending = {
        "tool_name": tool_name,
        "params": params or {},
        "conversation_id": conversation_id or "",
        "created_at": time.time(),
    }
    payload = json.dumps(pending)
    key = _pending_key(hw_id)
    stored = await _redis_setex(redis_client, key, payload)
    if not stored:
        _memory_pending[hw_id] = pending
    return {"proposed": True, "tool_name": tool_name, "awaiting_confirmation": True}


async def maybe_propose_from_utterance(
    hw_id: str,
    user_text: str,
    *,
    conversation_id: str = "",
    redis_client: Any = None,
) -> Optional[Dict[str, Any]]:
    """Detect intent, store pending, return handled response for bridge."""
    if not tool_executor_enabled():
        return None
    # Don't overwrite an existing pending action
    existing = await _load_pending(hw_id, redis_client)
    if existing:
        return None
    if _COACH_BOOK_RE.search(user_text or ""):
        return {
            "handled": True,
            "proposed": False,
            "tool_name": "book_session",
            "text": _BOOK_REDIRECT_TEXT,
        }
    intent = detect_tool_intent(user_text)
    if not intent:
        return None
    result = await propose_tool_action(
        hw_id,
        conversation_id,
        intent["tool_name"],
        intent.get("params") or {},
        redis_client=redis_client,
    )
    if not result.get("proposed"):
        return None
    return {
        "handled": True,
        "proposed": True,
        "tool_name": intent["tool_name"],
        "text": intent.get("prompt") or "Should I go ahead with that?",
    }


def _classify_confirmation(user_text: str) -> Optional[bool]:
    text = (user_text or "").strip()
    if not text:
        return None
    if _NO_RE.search(text):
        return False
    if _YES_RE.search(text):
        return True
    return None


async def _load_pending(hw_id: str, redis_client: Any) -> Optional[Dict[str, Any]]:
    key = _pending_key(hw_id)
    raw = await _redis_get(redis_client, key)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    pending = _memory_pending.get(hw_id)
    if pending:
        age = time.time() - float(pending.get("created_at") or 0)
        if age > _PENDING_TTL_SECONDS:
            _memory_pending.pop(hw_id, None)
            return None
    return pending


async def _clear_pending(hw_id: str, redis_client: Any) -> None:
    await _redis_delete(redis_client, _pending_key(hw_id))
    _memory_pending.pop(hw_id, None)


async def check_and_execute_confirmation(
    hw_id: str,
    user_text: str,
    *,
    db_pool: Any = None,
    redis_client: Any = None,
) -> Optional[Dict[str, Any]]:
    """
    Returns None if no pending action or ambiguous confirmation.
    On yes/no: clears pending and returns handled=True for bridge WS.
    """
    if not tool_executor_enabled():
        return None

    pending = await _load_pending(hw_id, redis_client)
    if not pending:
        return None

    decision = _classify_confirmation(user_text)
    if decision is None:
        return None

    await _clear_pending(hw_id, redis_client)

    if not decision:
        return {
            "handled": True,
            "confirmed": False,
            "tool_name": pending.get("tool_name"),
            "text": "Okay — I won't do that.",
            "message": "Okay — I won't do that.",
        }

    tool_name = pending.get("tool_name")
    spec = NATE_TOOLS.get(tool_name or "")
    if not spec:
        return {
            "handled": True,
            "confirmed": True,
            "error": "unknown_tool",
            "text": "I lost track of that action. Please ask again.",
        }

    executor: Callable[..., Awaitable[Dict[str, Any]]] = spec["executor_fn"]
    try:
        result = await executor(db_pool, hw_id, pending.get("params") or {})
    except Exception as e:
        logger.warning("tool_executor: %s failed: %s", tool_name, e)
        result = {"success": False, "error": str(e)[:200]}

    ok = bool(result.get("success"))
    if ok:
        if tool_name == "set_reminder":
            text = "Reminder saved."
        elif tool_name == "queue_resource":
            text = "Resource queued for you."
        else:
            text = "Done."
    elif result.get("error") == "coach_decision_required":
        text = result.get("message") or _BOOK_REDIRECT_TEXT
    else:
        err = result.get("error") or "failed"
        text = f"I couldn't complete that ({err})."

    return {
        "handled": True,
        "confirmed": True,
        "tool_name": tool_name,
        "result": result,
        "text": text,
        "message": text,
    }
