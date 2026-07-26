"""
L5 observer — append-only ingest of L4 events. Read-only w.r.t. live rule path.
"""

from __future__ import annotations

import logging
from typing import Any

from .gates import (
    adapt_enabled,
    observe_enabled,
    refuse_hard_class,
)

logger = logging.getLogger("l5_sandbox.observer")


async def ingest_l4_event(
    db_pool: Any,
    *,
    event: str,
    detail: str = "",
    gate_class: str = "",
    rule_key: str = "",
    version: int = 0,
) -> None:
    """Record an L4 signal. Optionally trigger sandbox-only self-adapt."""
    if not observe_enabled() or not db_pool or not event:
        return
    # Soft-only: hard/unknown classes are logged as gate_refuse, not adapted
    if gate_class and refuse_hard_class(gate_class):
        await _audit_gate_refuse(db_pool, gate_class, event, detail)
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO l5_observe_event
                    (event, gate_class, rule_key, version, detail)
                VALUES ($1, $2, $3, $4, $5)
                """,
                str(event)[:80],
                (gate_class or "")[:80],
                (rule_key or "")[:200],
                int(version or 0),
                (detail or "")[:500],
            )
    except Exception as e:
        logger.warning("l5_observe_event insert skip: %s", e)
        return

    if adapt_enabled() and gate_class:
        try:
            from .adaptor import maybe_adapt_from_event

            await maybe_adapt_from_event(
                db_pool,
                event=event,
                gate_class=gate_class,
                rule_key=rule_key,
                version=version,
                detail=detail,
            )
        except Exception as e:
            logger.warning("l5 adapt skip: %s", e)


async def _audit_gate_refuse(
    db_pool: Any,
    gate_class: str,
    event: str,
    detail: str,
) -> None:
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO l5_observe_audit
                    (hypothesis_key, version, action, detail)
                VALUES ($1, 0, 'gate_refuse', $2)
                """,
                f"refuse:{gate_class}"[:200],
                f"event={event} class={gate_class} {detail}"[:500],
            )
    except Exception as e:
        logger.debug("l5 gate_refuse audit skip: %s", e)


async def recent_events(
    db_pool: Any,
    *,
    limit: int = 50,
    gate_class: str = "",
) -> list:
    """Read-only helper for L5 development / tests."""
    if not observe_enabled() or not db_pool:
        return []
    lim = max(1, min(int(limit), 200))
    try:
        async with db_pool.acquire() as conn:
            if gate_class:
                rows = await conn.fetch(
                    """
                    SELECT event, gate_class, rule_key, version, detail, recorded_at
                    FROM l5_observe_event
                    WHERE gate_class = $1
                    ORDER BY recorded_at DESC
                    LIMIT $2
                    """,
                    gate_class,
                    lim,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT event, gate_class, rule_key, version, detail, recorded_at
                    FROM l5_observe_event
                    ORDER BY recorded_at DESC
                    LIMIT $1
                    """,
                    lim,
                )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug("recent_events: %s", e)
        return []
