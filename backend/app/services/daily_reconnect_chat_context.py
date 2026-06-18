"""
Daily Reconnect → main-chat memory bridge — QUANTUM-CRYSTAL-ARCH

Two paths, one principle: the ritual DB (daily_reconnect_turn) is the source of
truth. Locked rows are quoted verbatim in the live read-through block. The ingest
path writes a *derived copy* into conversation_history + crystals so the ritual is
discoverable through the same memory pipeline main chat already uses. The derived
copy is for search only — it never replaces the locked rows in crisis/coach paths.

Flags (both default OFF; dark-launch safe):
  ENABLE_RECONNECT_CHAT_MEMORY  — read-through block in main chat system prompt
  ENABLE_RECONNECT_MEMORY_INGEST — derived-copy ingest on session close
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("daily_reconnect_chat")

ENABLE_RECONNECT_CHAT_MEMORY: bool = os.getenv(
    "ENABLE_RECONNECT_CHAT_MEMORY", "false"
).lower() in ("true", "1", "yes")

ENABLE_RECONNECT_MEMORY_INGEST: bool = os.getenv(
    "ENABLE_RECONNECT_MEMORY_INGEST", "false"
).lower() in ("true", "1", "yes")

RECONNECT_CONTEXT_SESSION_LIMIT: int = int(
    os.getenv("RECONNECT_CONTEXT_SESSION_LIMIT", "3")
)
RECONNECT_CONTEXT_TURN_MIN_LEN: int = 12

# Closed/terminal states whose locked rows are safe to surface as benign memory.
# CRISIS_BYPASS is intentionally excluded everywhere — crisis content stays in the
# locked ritual rows for crisis/coach grounding, never the derived chat copy.
_CLOSED_STATES = ("WRAP_UP", "CLOSED", "ENTER_FS")
_INGEST_STATES = ("CLOSED", "ENTER_FS")


async def _member_display_names(db_pool, family_id: str) -> Dict[str, str]:
    """username -> display name for every member of the family."""
    out: Dict[str, str] = {}
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT username,
                       COALESCE(NULLIF(trim(name), ''),
                                NULLIF(trim(profile_data->>'name'), ''),
                                username) AS display_name
                FROM users
                WHERE trim(COALESCE(family_id::text, profile_data->>'family_id', '')) = $1
                """,
                family_id,
            )
        for r in rows:
            out[r["username"]] = r["display_name"]
    except Exception as e:  # noqa: BLE001
        logger.warning("reconnect member names lookup failed: %s", e)
    return out


# ── Read-through: locked rows quoted verbatim ─────────────────────────────────

async def build_reconnect_chat_context(
    db_pool,
    identifier: str,
    user_message: str = "",
    *,
    session_limit: int = RECONNECT_CONTEXT_SESSION_LIMIT,
) -> str:
    """Prompt block for 1:1 chat built from LOCKED ritual rows (source of truth).

    Returns "" when the flag is off, the user has no family, or no closed
    sessions exist. Reads directly from daily_reconnect_turn — no summarization.
    """
    if not ENABLE_RECONNECT_CHAT_MEMORY or not db_pool or not identifier:
        return ""

    try:
        from app.services.family_system_field import resolve_family_id
    except Exception:  # noqa: BLE001
        return ""

    family_id, canonical_username = await resolve_family_id(db_pool, identifier)
    if not family_id or not canonical_username:
        return ""

    try:
        async with db_pool.acquire() as conn:
            sessions = await conn.fetch(
                """
                SELECT id, state, total_reconnects, created_at, closed_at
                FROM daily_reconnect_session
                WHERE family_id = $1
                  AND closed_at IS NOT NULL
                  AND state = ANY($2::text[])
                ORDER BY closed_at DESC
                LIMIT $3
                """,
                family_id, list(_CLOSED_STATES), session_limit,
            )
            if not sessions:
                return ""

            turns_by_session: Dict[str, List[Dict]] = {}
            for s in sessions:
                rows = await conn.fetch(
                    """
                    SELECT user_id, prompt_kind, content, created_at
                    FROM daily_reconnect_turn
                    WHERE session_id = $1::uuid
                      AND char_length(content) >= $2
                    ORDER BY created_at ASC
                    """,
                    s["id"], RECONNECT_CONTEXT_TURN_MIN_LEN,
                )
                turns_by_session[str(s["id"])] = [dict(r) for r in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning("reconnect chat context query failed: %s", e)
        return ""

    names = await _member_display_names(db_pool, family_id)
    names.setdefault(canonical_username, canonical_username)

    parts: List[str] = [
        "DAILY RECONNECT HISTORY (locked couple-ritual answers — quote verbatim; never invent):",
        "These are the user's and their partner's own words from the Daily Reconnect ritual.",
        "Reference only what appears below. If they ask about a reconnect answer not listed, say you don't have it.",
    ]
    rendered = 0
    for s in sessions:
        sid = str(s["id"])
        turns = turns_by_session.get(sid) or []
        if not turns:
            continue
        date_str = s["created_at"].strftime("%Y-%m-%d") if s.get("created_at") else "?"
        parts.append(
            f"\n--- Session {date_str} (state={s.get('state')}, reconnect #{s.get('total_reconnects', 0)}) ---"
        )
        for t in turns:
            who = names.get(t.get("user_id"), t.get("user_id") or "Member")
            kind = t.get("prompt_kind") or "reflection"
            content = (t.get("content") or "").strip()
            parts.append(f"[{kind}] {who}: \"{content}\"")
        rendered += 1

    if rendered == 0:
        return ""
    return "\n".join(parts)


# ── Write-through: derived copy for search (NOT a source of truth) ────────────

async def ingest_closed_session_for_memory(
    db_pool,
    session_id: str,
    *,
    cortex: Any = None,
) -> int:
    """Copy a closed session's locked turns into conversation_history + crystals.

    Idempotent (guarded by a daily_reconnect_event 'memory_ingested' marker).
    Skips CRISIS_BYPASS. Returns the number of turns ingested (0 if skipped).
    """
    if not ENABLE_RECONNECT_MEMORY_INGEST or not db_pool or not session_id:
        return 0

    try:
        async with db_pool.acquire() as conn:
            sess = await conn.fetchrow(
                """
                SELECT id, family_id, state
                FROM daily_reconnect_session
                WHERE id = $1::uuid
                """,
                session_id,
            )
            if not sess or sess["state"] not in _INGEST_STATES:
                return 0

            already = await conn.fetchval(
                """
                SELECT 1 FROM daily_reconnect_event
                WHERE session_id = $1::uuid AND event_type = 'memory_ingested'
                LIMIT 1
                """,
                session_id,
            )
            if already:
                return 0

            turns = await conn.fetch(
                """
                SELECT user_id, prompt_kind, content
                FROM daily_reconnect_turn
                WHERE session_id = $1::uuid
                  AND char_length(content) >= $2
                ORDER BY created_at ASC
                """,
                session_id, RECONNECT_CONTEXT_TURN_MIN_LEN,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("reconnect ingest load failed: %s", e)
        return 0

    if not turns:
        return 0

    family_id = sess["family_id"]
    names = await _member_display_names(db_pool, family_id)

    try:
        from app.websocket.crystal_recall_bridge import crystallize_from_conversation as _crystal_forge
    except Exception:  # noqa: BLE001
        _crystal_forge = None

    ch_session_id = f"reconnect:{session_id}"
    ingested = 0
    for t in turns:
        author = t.get("user_id")
        if not author:
            continue
        kind = t.get("prompt_kind") or "reflection"
        content = (t.get("content") or "").strip()
        if not content:
            continue
        user_text = f"[Daily Reconnect · {kind}] {content}"
        # conversation_history derived copy (FTS + pg_history surface it for the author)
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO conversation_history "
                    "(user_id, user_text, ai_text, session_id, metadata, created_at) "
                    "VALUES ($1, $2, $3, $4, $5::jsonb, NOW()) "
                    "ON CONFLICT DO NOTHING",
                    author, user_text[:4000], "", ch_session_id,
                    json.dumps({"source": "daily_reconnect", "prompt_kind": kind}),
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("reconnect conversation_history insert failed: %s", e)

        # crystal derived copy (author-scoped; semantic + recall surface it)
        if _crystal_forge is not None:
            try:
                await _crystal_forge(
                    db_pool, author, content, "",
                    user_name=names.get(author, author),
                    domain="clinical", min_score=3,
                    origin_surface="daily_reconnect",
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("reconnect crystallize failed: %s", e)
        ingested += 1

    # memory.json short-term copy via cortex, if available (author-keyed)
    if cortex is not None:
        try:
            mem = getattr(cortex, "mem", None)
            memorize = getattr(mem, "memorize", None) if mem else None
            if callable(memorize):
                for t in turns:
                    author = t.get("user_id")
                    content = (t.get("content") or "").strip()
                    if author and content:
                        memorize(author, f"[Daily Reconnect] {content}", "")
        except Exception as e:  # noqa: BLE001
            logger.warning("reconnect memory.json copy failed: %s", e)

    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO daily_reconnect_event (session_id, family_id, event_type, detail)
                VALUES ($1::uuid, $2, 'memory_ingested', $3::jsonb)
                """,
                session_id, family_id, json.dumps({"turns": ingested}),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("reconnect ingest marker insert failed: %s", e)

    logger.info("reconnect memory ingested: session=%s turns=%s", session_id, ingested)
    return ingested
