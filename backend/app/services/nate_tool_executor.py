"""
QUANTUM-CRYSTAL-ARCH: Nate tool propose/confirm executor (Agentic Phase 2).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger("nate.tool_executor")

_PENDING_TTL_SECONDS = 600
_YES_RE = re.compile(
    r"\b(yes|yeah|yep|sure|go ahead|do it|please do|ok(?:ay)?|sounds good)\b",
    re.I,
)
_NO_RE = re.compile(
    r"\b(no|nope|never\s?mind|nevermind|cancel|don't|do not|stop)\b",
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


async def _book_session_executor(
    db_pool: Any, hw_id: str, params: Dict[str, Any]
) -> Dict[str, Any]:
    from app.services.session_booking_service import book_session

    return await book_session(
        db_pool,
        client_hw_id=hw_id,
        coach_id=params.get("coach_id"),
        slot_start=params.get("slot_start"),
        session_type=params.get("session_type", "individual"),
        notes=params.get("notes", ""),
    )


async def _set_reminder_executor(
    db_pool: Any, hw_id: str, params: Dict[str, Any]
) -> Dict[str, Any]:
    """Stub — full delivery via nate_nudges + proactive_touch_policy in Phase 2 wiring."""
    reminder_text = (params.get("text") or params.get("message") or "").strip()
    scheduled_at = params.get("scheduled_at")
    if not reminder_text or not scheduled_at:
        return {"success": False, "error": "missing_reminder_fields"}
    return {
        "success": True,
        "status": "scheduled_stub",
        "user_id": hw_id,
        "text": reminder_text[:500],
        "scheduled_at": scheduled_at,
    }


async def _queue_resource_executor(
    db_pool: Any, hw_id: str, params: Dict[str, Any]
) -> Dict[str, Any]:
    resource = (params.get("resource_id") or params.get("topic") or "").strip()
    if not resource:
        return {"success": False, "error": "missing_resource"}
    return {
        "success": True,
        "status": "queued_stub",
        "user_id": hw_id,
        "resource": resource[:200],
    }


NATE_TOOLS: Dict[str, Dict[str, Any]] = {
    "book_session": {
        "description": "Book a coaching session after explicit user confirmation",
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
        val = await redis_client.get(key)
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
        await redis_client.setex(key, _PENDING_TTL_SECONDS, payload)
        return True
    except Exception as e:
        logger.warning("tool_executor: redis setex failed: %s", e)
        return False


async def _redis_delete(redis_client: Any, key: str) -> None:
    if not redis_client:
        return
    try:
        await redis_client.delete(key)
    except Exception:
        pass


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
    Otherwise returns dict with action taken and tool result.
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
            "confirmed": False,
            "tool_name": pending.get("tool_name"),
            "message": "Okay — I won't do that.",
        }

    tool_name = pending.get("tool_name")
    spec = NATE_TOOLS.get(tool_name or "")
    if not spec:
        return {"confirmed": True, "error": "unknown_tool"}

    executor: Callable[..., Awaitable[Dict[str, Any]]] = spec["executor_fn"]
    try:
        result = await executor(db_pool, hw_id, pending.get("params") or {})
    except Exception as e:
        logger.warning("tool_executor: %s failed: %s", tool_name, e)
        result = {"success": False, "error": str(e)[:200]}

    return {
        "confirmed": True,
        "tool_name": tool_name,
        "result": result,
    }
