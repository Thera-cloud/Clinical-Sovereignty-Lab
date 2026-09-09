"""View Brief overlay: PostgreSQL conversation_history + prior session summaries.

Coach Command View Brief historically read vault ``memory.json`` only.
This module merges ``conversation_history`` (keyed by ``users.username``,
with hardware_id as a fallback for legacy rows) and prior coaching-session
summaries. Payment identifiers never enter the brief.

# QUANTUM-CRYSTAL-ARCH — S7 View Brief overlay
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("nate.presession_brief_overlay")

PAYMENT_SECRET_KEYS = frozenset(
    {
        "stripe_payment_intent_id",
        "stripe_payment_intent",
        "payment_intent_id",
        "payment_intent",
        "client_secret",
        "stripe_client_secret",
    }
)


def overlay_enabled() -> bool:
    return os.getenv("ENABLE_BRIEF_PG_OVERLAY", "true").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def strip_payment_secrets(obj: Any) -> Any:
    """Drop Stripe payment-intent fields from any nested brief payload."""
    if isinstance(obj, dict):
        return {
            k: strip_payment_secrets(v)
            for k, v in obj.items()
            if k not in PAYMENT_SECRET_KEYS
        }
    if isinstance(obj, list):
        return [strip_payment_secrets(v) for v in obj]
    return obj


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        return default


def _iso_ts(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def sanitize_conversation_entry(raw: Any) -> Optional[Dict[str, Any]]:
    """Map vault or PG row to ConversationLogView shape. No payment keys."""
    if not isinstance(raw, dict):
        return None
    user = (raw.get("user") or raw.get("user_text") or raw.get("preview") or "").strip()
    ai = (raw.get("ai") or raw.get("ai_text") or "").strip()
    if not user and not ai:
        return None
    ts = raw.get("timestamp") or raw.get("created_at") or ""
    sid = raw.get("session_id") or ""
    return {
        "timestamp": _iso_ts(ts) if not isinstance(ts, str) else ts,
        "session_id": str(sid) if sid else "",
        "user": user,
        "ai": ai,
        "word_count_user": int(raw.get("word_count_user") or 0),
        "word_count_ai": int(raw.get("word_count_ai") or 0),
    }


def _dedupe_key(entry: Dict[str, Any]) -> str:
    ts = (entry.get("timestamp") or "")[:19]
    user = (entry.get("user") or "")[:80]
    return f"{ts}|{user}"


def merge_conversation_turns(
    vault_entries: Iterable[Any],
    pg_entries: Iterable[Dict[str, Any]],
    *,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """PG is source of truth; vault fills gaps. Newest-last, capped at ``limit``."""
    merged: List[Dict[str, Any]] = []
    seen = set()
    for src in (pg_entries, vault_entries):
        for raw in src:
            entry = sanitize_conversation_entry(raw) if isinstance(raw, dict) else None
            if not entry:
                continue
            key = _dedupe_key(entry)
            if key in seen:
                continue
            seen.add(key)
            merged.append(entry)
    merged.sort(key=lambda e: (e.get("timestamp") or "", e.get("session_id") or ""))
    if len(merged) > limit:
        merged = merged[-limit:]
    return merged


def rebuild_conversation_topics(turns: List[Dict[str, Any]], n: int = 3) -> List[Dict[str, Any]]:
    topics: List[Dict[str, Any]] = []
    for m in turns[-n:]:
        u = (m.get("user") or "").strip()
        a = (m.get("ai") or "").strip()
        snippet = u if len(u) >= 12 else (u or a)[:240]
        if not snippet.strip():
            continue
        clipped = snippet[:400]
        if len(snippet) > 400:
            clipped += "..."
        topics.append({
            "timestamp": m.get("timestamp") or "",
            "topic_summary": clipped,
        })
    return topics


def session_summary_from_row(row: Any) -> Optional[Dict[str, Any]]:
    nate = (_row_get(row, "nate_summary") or "").strip()
    notes = (_row_get(row, "session_notes") or "").strip()
    zoom = (_row_get(row, "zoom_summary") or "").strip()
    summary = nate or zoom or notes
    if not summary:
        return None
    occurred = _row_get(row, "occurred_at")
    return {
        "session_id": str(_row_get(row, "session_id") or ""),
        "occurred_at": _iso_ts(occurred),
        "summary": summary[:800],
        "source": "nate_summary" if nate else ("zoom" if zoom else "session_notes"),
    }


async def _history_user_ids(
    db_pool: Any,
    client_id: str,
    client_profile: Optional[Dict[str, Any]],
) -> List[str]:
    """conversation_history.user_id is username; include hardware_id for legacy rows."""
    ids: List[str] = []
    profile = client_profile or {}
    username = (profile.get("username") or "").strip()
    hardware_id = (profile.get("hardware_id") or client_id or "").strip()
    try:
        from app.services._identity_resolver import resolve_username

        resolved = await resolve_username(db_pool, (client_id or "").strip())
        if resolved:
            ids.append(resolved.strip())
    except Exception as e:
        logger.warning("presession overlay: resolve_username failed: %s", e)
    for candidate in (username, hardware_id, (client_id or "").strip()):
        if candidate and candidate not in ids:
            ids.append(candidate)
    return ids


async def overlay_presession_brief(
    db_pool: Any,
    client_id: str,
    client_profile: Optional[Dict[str, Any]],
    brief: Dict[str, Any],
    *,
    limit: int = 25,
) -> Dict[str, Any]:
    """Merge PG conversation + session summaries onto an existing View Brief dict."""
    out = dict(brief or {})
    vault = list(out.get("recent_conversations") or [])
    if not overlay_enabled() or not db_pool:
        out["recent_conversations"] = merge_conversation_turns(vault, [], limit=limit)
        return strip_payment_secrets(out)
    pg_turns: List[Dict[str, Any]] = []
    summaries: List[Dict[str, Any]] = []
    try:
        user_ids = await _history_user_ids(db_pool, client_id, client_profile)
        hardware_id = ((client_profile or {}).get("hardware_id") or client_id or "").strip()
        async with db_pool.acquire() as conn:
            if user_ids:
                rows = await conn.fetch(
                    """
                    SELECT session_id, user_text, ai_text,
                           word_count_user, word_count_ai, created_at
                      FROM conversation_history
                     WHERE user_id = ANY($1::text[])
                       AND (
                           LENGTH(COALESCE(user_text, '')) > 0
                           OR LENGTH(COALESCE(ai_text, '')) > 0
                       )
                     ORDER BY created_at DESC
                     LIMIT $2
                    """,
                    user_ids,
                    max(limit, 40),
                )
                for row in reversed(list(rows or [])):
                    pg_turns.append({
                        "timestamp": _iso_ts(_row_get(row, "created_at")),
                        "session_id": _row_get(row, "session_id") or "",
                        "user": (_row_get(row, "user_text") or "").strip(),
                        "ai": (_row_get(row, "ai_text") or "").strip(),
                        "word_count_user": int(_row_get(row, "word_count_user") or 0),
                        "word_count_ai": int(_row_get(row, "word_count_ai") or 0),
                    })
            hw_ids = [i for i in (hardware_id, (client_id or "").strip()) if i]
            if hw_ids:
                sum_rows = await conn.fetch(
                    """
                    SELECT session_id,
                           COALESCE(actual_end, scheduled_at, scheduled_start) AS occurred_at,
                           LEFT(COALESCE(nate_summary, ''), 800) AS nate_summary,
                           LEFT(COALESCE(session_notes, ''), 400) AS session_notes,
                           LEFT(COALESCE(session_data->>'zoom_ai_summary_text', ''), 800)
                               AS zoom_summary
                      FROM coaching_sessions
                     WHERE client_id = ANY($1::text[])
                       AND (
                           COALESCE(nate_summary, '') <> ''
                           OR COALESCE(session_notes, '') <> ''
                           OR COALESCE(session_data->>'zoom_ai_summary_text', '') <> ''
                       )
                     ORDER BY COALESCE(actual_end, scheduled_at, scheduled_start)
                              DESC NULLS LAST
                     LIMIT 8
                    """,
                    hw_ids,
                )
                for row in sum_rows or []:
                    parsed = session_summary_from_row(row)
                    if parsed:
                        summaries.append(parsed)
    except Exception as e:
        logger.warning("presession overlay: PG merge failed: %s", e)

    merged = merge_conversation_turns(vault, pg_turns, limit=limit)
    out["recent_conversations"] = merged
    if merged:
        out["recent_conversation_topics"] = rebuild_conversation_topics(merged)
    if summaries:
        out["prior_session_summaries"] = summaries
    return strip_payment_secrets(out)
