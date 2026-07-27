"""Hybrid voice resume — movie/drop + main chat + PAUSED redial.

SOVEREIGN-VOICE — Nate should weigh all three threads after a drop.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

HYBRID_MARKER = "[HYBRID_RESUME]"
PAUSE_REDIS_PREFIX = "nate:voice_hybrid_pause:"
PAUSE_TTL_S = int(os.getenv("VOICE_HYBRID_PAUSE_TTL_S", "300"))


async def seed_hybrid_resume(
    db_pool,
    username: str,
    *,
    dropped_voice_summary: str,
    last_chat_summary: str,
    session_id: str = "hybrid_resume",
) -> bool:
    """Write a conversation_history row Nate will load on next grounded prompt."""
    if not db_pool or not username:
        return False
    user_text = (
        f"{HYBRID_MARKER} Our phone call dropped. On the next call or chat, "
        "please consider all three continuity threads below."
    )
    ai_text = (
        "HYBRID CONTINUITY — weigh all three, let the caller choose:\n"
        f"1) DROPPED VOICE CALL: {dropped_voice_summary.strip()}\n"
        f"2) LAST MAIN CHAT: {last_chat_summary.strip()}\n"
        "3) PAUSED REDIAL: If they return within ~5 minutes, greet as a brief resume "
        "(acknowledge the drop once), then offer to continue the voice thread OR the "
        "main chat thread — do not force either.\n"
        "Keep replies short on phone. Prefer one gentle question about which thread "
        "they want to pick up."
    )
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO conversation_history
                    (user_id, session_id, user_text, ai_text, context_type, created_at)
                VALUES ($1, $2, $3, $4, 'voice', NOW())
                """,
                username,
                session_id[:120],
                user_text[:4000],
                ai_text[:4000],
            )
        print(f"[VOICE-HYBRID] seeded resume for {username}")
        return True
    except Exception as e:
        logger.warning("seed_hybrid_resume failed: %s", e)
        return False


async def build_hybrid_resume_block(db_pool, username: str) -> str:
    """Prompt block from the latest HYBRID_RESUME row (48h)."""
    if not db_pool or not username:
        return ""
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT user_text, ai_text, created_at
                FROM conversation_history
                WHERE user_id = $1
                  AND user_text LIKE $2
                  AND created_at > NOW() - INTERVAL '48 hours'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                username,
                f"{HYBRID_MARKER}%",
            )
        if not row:
            return ""
        return (
            "=== HYBRID RESUME (DROPPED CALL + MAIN CHAT + PAUSED REDIAL) ===\n"
            "Consider ALL three threads. Let the caller choose which to continue.\n"
            f"{(row['ai_text'] or '')[:2500]}\n"
            "=== END HYBRID RESUME ===\n\n"
        )
    except Exception as e:
        logger.warning("build_hybrid_resume_block failed: %s", e)
        return ""


async def arm_hybrid_pause(
    redis_client,
    phone_digits: str,
    username: str,
    call_sid: str = "",
    note: str = "",
) -> bool:
    """5-minute redial map: phone → username (works without voice_accounts)."""
    if not redis_client or not phone_digits or not username:
        return False
    key = f"{PAUSE_REDIS_PREFIX}{phone_digits}"
    payload = json.dumps(
        {
            "username": username,
            "call_sid": call_sid or "",
            "note": (note or "")[:500],
        }
    )
    try:
        await redis_client.setex(key, PAUSE_TTL_S, payload)
        print(f"[VOICE-HYBRID] pause armed phone=…{phone_digits[-4:]} user={username} ttl={PAUSE_TTL_S}s")
        return True
    except Exception as e:
        logger.warning("arm_hybrid_pause failed: %s", e)
        return False


async def peek_hybrid_pause(redis_client, phone_digits: str) -> Optional[Dict[str, Any]]:
    if not redis_client or not phone_digits:
        return None
    key = f"{PAUSE_REDIS_PREFIX}{phone_digits}"
    try:
        raw = await redis_client.get(key)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("username"):
            return data
    except Exception as e:
        logger.warning("peek_hybrid_pause failed: %s", e)
    return None


async def finalize_hybrid_on_call_end(
    db_pool,
    *,
    username: str,
    call_sid: str,
    ctx: Dict[str, Any],
    user_turns: list,
    assistant_turns: list,
) -> None:
    """Seed hybrid history, arm 5min phone→user pause, clear call_context."""
    from app.services.api_server import _get_auth_redis
    from app.services.voice_phone import phone_digits_only

    asst = " | ".join((t.get("text") or "")[:120] for t in (assistant_turns or [])[-4:]) or (
        "Live voice call ended abruptly."
    )
    usr = " | ".join((t.get("text") or "")[:120] for t in (user_turns or [])[-4:]) or (
        "Caller audio present; transcript may be partial."
    )
    await seed_hybrid_resume(
        db_pool,
        username,
        dropped_voice_summary=f"{usr} → Nate: {asst}",
        last_chat_summary=(
            "Also weigh the caller's most recent main-app chat in PRIOR SESSION MEMORY "
            "(relationship / life themes) — offer either thread."
        ),
        session_id=call_sid or "hybrid_resume",
    )
    phone = phone_digits_only(
        (ctx or {}).get("to_number")
        or (ctx or {}).get("from_number")
        or (ctx or {}).get("caller")
        or (ctx or {}).get("phone")
        or ""
    )
    redis = await _get_auth_redis()
    if redis and phone:
        await arm_hybrid_pause(
            redis, phone, username, call_sid=call_sid or "", note=asst[:200]
        )
    if redis and call_sid:
        try:
            await redis.delete(f"nate:call_context:{call_sid}")
        except Exception:
            pass
