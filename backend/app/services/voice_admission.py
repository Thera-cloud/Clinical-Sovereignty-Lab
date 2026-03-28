"""
Inbound call admission: crisis bypass, capacity, entitlement hooks.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("nate.voice_admission")

CRISIS_THRESHOLD = float(os.getenv("VOICE_CRISIS_SCORE_THRESHOLD", "0.7"))


@dataclass
class AdmissionDecision:
    lane: str  # immediate | callback_promise
    crisis: bool
    preempt: bool
    reason: str


async def quick_crisis_check(
    pool,
    profile_data: Dict[str, Any],
    username: str,
    user_uuid: Optional[str] = None,
) -> float:
    """
    Heuristic 0..1 from profile flags and latest Nevedal C_emo if available.
    """
    score = 0.0
    if not isinstance(profile_data, dict):
        return score
    # Explicit crisis / safety flags in profile (if present)
    flags = (
        profile_data.get("crisis_flag"),
        profile_data.get("voice_crisis"),
        profile_data.get("safety_escalation"),
    )
    for f in flags:
        if f in (True, "true", "1", 1):
            score = max(score, 0.85)
    # Last known C_emo from profile (written by bridge/metrics)
    try:
        c_emo = profile_data.get("c_emo")
        if c_emo is not None:
            v = float(c_emo)
            if v > 0.75:
                score = max(score, min(1.0, v))
    except (TypeError, ValueError):
        pass
    # Nevedal metrics row (optional) — user_id is UUID FK
    if pool and user_uuid and score < CRISIS_THRESHOLD:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT c_emo FROM nevedal_metrics
                    WHERE user_id = $1::uuid
                    ORDER BY recorded_at DESC NULLS LAST
                    LIMIT 1
                    """,
                    user_uuid,
                )
            if row and row["c_emo"] is not None:
                v = float(row["c_emo"])
                if v > 0.75:
                    score = max(score, min(1.0, v))
        except Exception:
            pass
    return score


async def decide_inbound_admission(
    pool,
    *,
    crisis_score: float,
    active_sessions: int,
    entitled: bool,
    xtts_limit: int,
) -> AdmissionDecision:
    """
    Phase 1 rules:
    - crisis -> immediate, preempt=True (slot acquired with crisis bypass)
    - not entitled -> callback_promise (handled by caller as Polly message, not queue)
    - active < limit -> immediate
    - else -> callback_promise (Phase 3 adds therapeutic hold)
    """
    crisis = crisis_score > CRISIS_THRESHOLD
    if crisis:
        return AdmissionDecision("immediate", True, True, "crisis_bypass")
    if not entitled:
        return AdmissionDecision("callback_promise", False, False, "not_entitled")
    if active_sessions < xtts_limit:
        return AdmissionDecision("immediate", False, False, "capacity_ok")
    return AdmissionDecision("callback_promise", False, False, "at_capacity")


async def pre_warm_voice_session(
    pool,
    *,
    username: str,
    user_uuid: str,
    call_sid: str,
) -> None:
    """Best-effort: stash a short context blob for the media stream (non-blocking helper)."""
    try:
        from app.services.api_server import _get_auth_redis
        redis = await _get_auth_redis()
        if not redis:
            return
        snippet = {"username": username, "user_uuid": user_uuid, "call_sid": call_sid}
        if pool:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile_data->>'name' AS name FROM users WHERE id = $1::uuid",
                    user_uuid,
                )
                if row:
                    snippet["name"] = row["name"]
        await redis.setex(
            f"nate:voice_prewarm:{call_sid}",
            600,
            json.dumps(snippet),
        )
    except Exception as e:
        logger.debug("pre_warm_voice_session skipped: %s", e)


async def enqueue_simple_callback(
    pool,
    *,
    user_uuid: str,
    reason: str,
    priority: int = 2,
) -> None:
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO callback_queue
                    (user_uuid, priority, reason, status, scheduled_for)
                VALUES ($1::uuid, $2, $3, 'pending', NOW() + INTERVAL '5 minutes')
                """,
                user_uuid,
                priority,
                reason[:500],
            )
    except Exception as e:
        logger.warning("enqueue_simple_callback: %s", e)
