"""
L5 self-adapt — hypotheses scored inside the sandbox only.

Never calls draft_rule / promote_rule / ln_rule_store writes.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from .gates import (
    adapt_enabled,
    can_write_live_rules,
    is_soft_observe_class,
    refuse_hard_class,
)

logger = logging.getLogger("l5_sandbox.adaptor")

_ADAPT_EVENTS = frozenset({"shadow_fire", "fire", "draft_sandbox", "promote", "rollback"})


def _hypothesis_key(gate_class: str) -> str:
    return f"l5.soft_gate.{gate_class}.followup_suppress"


async def maybe_adapt_from_event(
    db_pool: Any,
    *,
    event: str,
    gate_class: str,
    rule_key: str = "",
    version: int = 0,
    detail: str = "",
) -> Optional[int]:
    """Upsert/score a sandbox hypothesis from an observed L4 event."""
    if not adapt_enabled() or not db_pool:
        return None
    # Hardened: cannot escape to live rules
    if can_write_live_rules():
        logger.error("L5 HARD GATE VIOLATION: can_write_live_rules True — abort")
        return None
    if refuse_hard_class(gate_class) or not is_soft_observe_class(gate_class):
        return None
    if event not in _ADAPT_EVENTS:
        return None

    hkey = _hypothesis_key(gate_class)
    delta = _score_delta(event)
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, version, score, sample_n, status
                FROM l5_observe_hypothesis
                WHERE hypothesis_key = $1
                  AND status IN ('observe', 'adapt_shadow')
                ORDER BY version DESC
                LIMIT 1
                """,
                hkey,
            )
            if row is None:
                cond = {
                    "gate_class": gate_class,
                    "fired_new": False,
                    "source": "l5_observe",
                }
                act = {"type": "suppress_soft_followup", "live": False}
                rid = await conn.fetchval(
                    """
                    INSERT INTO l5_observe_hypothesis
                        (hypothesis_key, version, status, condition_json,
                         action_json, parent_rule_key, score, sample_n,
                         created_by, notes)
                    VALUES (
                        $1, 1, 'observe', $2::jsonb, $3::jsonb, $4,
                        GREATEST(0.0, LEAST(1.0, 0.50 + $5::real)),
                        1, 'l5_adaptor', $6
                    )
                    RETURNING id
                    """,
                    hkey,
                    json.dumps(cond),
                    json.dumps(act),
                    (rule_key or "")[:200],
                    float(delta),
                    f"seed from L4 event={event}"[:500],
                )
                await conn.execute(
                    """
                    INSERT INTO l5_observe_audit
                        (hypothesis_key, version, action, detail)
                    VALUES ($1, 1, 'observe', $2)
                    """,
                    hkey,
                    f"event={event} v={version} {detail}"[:500],
                )
                return int(rid) if rid is not None else None

            new_score = max(0.0, min(1.0, float(row["score"]) + delta))
            new_n = int(row["sample_n"] or 0) + 1
            # Promote within sandbox only: observe → adapt_shadow after enough signals
            new_status = str(row["status"] or "observe")
            if new_status == "observe" and new_n >= 3:
                new_status = "adapt_shadow"
            await conn.execute(
                """
                UPDATE l5_observe_hypothesis
                SET score = $2::real,
                    sample_n = $3,
                    status = $4,
                    parent_rule_key = CASE
                        WHEN $5 <> '' THEN $5 ELSE parent_rule_key END,
                    updated_at = NOW(),
                    notes = $6
                WHERE id = $1
                """,
                int(row["id"]),
                new_score,
                new_n,
                new_status,
                (rule_key or "")[:200],
                f"adapt event={event} score={new_score:.3f} n={new_n}"[:500],
            )
            await conn.execute(
                """
                INSERT INTO l5_observe_audit
                    (hypothesis_key, version, action, detail)
                VALUES ($1, $2, 'adapt', $3)
                """,
                hkey,
                int(row["version"]),
                f"event={event} score={new_score:.3f} status={new_status}"[:500],
            )
            return int(row["id"])
    except Exception as e:
        logger.warning("maybe_adapt_from_event: %s", e)
        return None


def _score_delta(event: str) -> float:
    """Sandbox-only score nudges from observed L4 lifecycle."""
    return {
        "draft_sandbox": 0.02,
        "shadow_fire": 0.03,
        "fire": 0.04,
        "promote": 0.05,
        "rollback": -0.08,
    }.get(event, 0.0)


async def propose_live_promotion(*_a: Any, **_k: Any) -> Dict[str, Any]:
    """Explicit refuse API — L5 must never promote into live rule store."""
    return {
        "allowed": False,
        "reason": "L5_HARD_GATE: can_write_live_rules is permanently False",
        "can_write_live_rules": can_write_live_rules(),
    }
