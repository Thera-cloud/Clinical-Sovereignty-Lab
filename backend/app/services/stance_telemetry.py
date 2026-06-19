"""
LITTLE NATE — Stance Telemetry Sink

Records stance routing (`stance_decisions`) and guard-hit events
(`stance_guard_events`) for the Stance Loop Auditor and operator review.
"""

import json
import logging
from typing import Any, List, Optional

logger = logging.getLogger("nate.stance_telemetry")


async def log_stance_decision(
    db_pool,
    uid,
    turn_index,
    intent,
    move,
    end_on_question,
    stripped_menu: bool = False,
    stripped_opener: bool = False,
) -> None:
    """Write one stance decision row to ``stance_decisions``."""
    if db_pool is None:
        logger.warning(
            "stance_telemetry: db_pool is None — dropping stance decision "
            "(uid=%s, turn=%s, intent=%s, move=%s)",
            uid, turn_index, intent, move,
        )
        return

    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO stance_decisions
                    (uid, turn_index, intent, move, end_on_question,
                     stripped_menu, stripped_opener, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                """,
                uid,
                turn_index,
                intent,
                move,
                bool(end_on_question),
                bool(stripped_menu),
                bool(stripped_opener),
            )
    except Exception as e:
        logger.warning(
            "stance_telemetry: failed to log stance decision "
            "(uid=%s, turn=%s): %s",
            uid, turn_index, e,
        )


async def log_stance_guard_events(
    db_pool,
    uid: str,
    turn_index: int,
    session_id: str,
    hits: List[dict],
) -> None:
    """Append one row per guard mutation in ``stance_guard_events``."""
    if db_pool is None or not hits:
        return
    try:
        async with db_pool.acquire() as conn:
            for hit in hits:
                signals = hit.get("user_signals") or {}
                await conn.execute(
                    """
                    INSERT INTO stance_guard_events
                        (uid, turn_index, session_id, guard_id, event_kind,
                         trigger, chars_before, chars_after, pct_stripped,
                         fallback_used, user_signals, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, NOW())
                    """,
                    uid,
                    turn_index,
                    session_id or "",
                    hit.get("guard_id", "unknown"),
                    hit.get("event_kind", "mutation"),
                    hit.get("trigger") or "",
                    int(hit.get("chars_before") or 0),
                    int(hit.get("chars_after") or 0),
                    float(hit.get("pct_stripped") or 0.0),
                    bool(hit.get("fallback_used")),
                    json.dumps(signals),
                )
    except Exception as e:
        logger.warning(
            "stance_telemetry: failed to log guard events (uid=%s, turn=%s): %s",
            uid, turn_index, e,
        )


async def log_stance_guard_bait_gap(
    db_pool,
    uid: str,
    turn_index: int,
    session_id: str,
    guard_id: str,
    user_signals: dict,
) -> None:
    """Record verdict-bait (or similar) with no matching guard mutation — soft-leak signal."""
    if db_pool is None:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO stance_guard_events
                    (uid, turn_index, session_id, guard_id, event_kind,
                     trigger, chars_before, chars_after, pct_stripped,
                     fallback_used, user_signals, created_at)
                VALUES ($1, $2, $3, $4, 'bait_no_hit', $5, 0, 0, 0, false, $6::jsonb, NOW())
                """,
                uid,
                turn_index,
                session_id or "",
                guard_id,
                "verdict_bait_no_guard_mutation",
                json.dumps(user_signals or {}),
            )
    except Exception as e:
        logger.warning(
            "stance_telemetry: failed to log bait gap (uid=%s, turn=%s): %s",
            uid, turn_index, e,
        )
