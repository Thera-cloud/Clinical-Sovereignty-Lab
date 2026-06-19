"""
LITTLE NATE — Stance Telemetry Sink

Records one row per stance decision emitted by the LN stance resolver so the
Stance Loop Auditor can detect witness-loop regressions (e.g. Nate repeatedly
closing POSITION-intent turns with a framing menu or a question instead of
holding a stance).

This module is the telemetry SINK only. The call-site wiring (where the bridge
emits a stance decision) is intentionally deferred to a later agent — see
`stance_loop_auditor.py` for the consumer side.

Design rules:
  - If db_pool is None, no-op safely (warn, never raise).
  - All DB work is wrapped in try/except with logger.warning on failure
    (background-agent-error-visibility: never silently swallow).
"""

import logging

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
    """Write one stance decision row to ``stance_decisions``.

    Fire-and-forget telemetry: failures are logged at WARNING and never raised,
    so a telemetry hiccup can never break the live therapeutic turn.
    """
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
