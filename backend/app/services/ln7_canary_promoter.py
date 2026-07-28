"""LN7 canary promote / rollback under statistical gate.

Policy auto-promote only when ENABLE_LN7_AUTO_PROMOTE=true AND CI beats incumbent.
CEO gate remains default when auto-promote is off.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_canary_promoter")


def auto_promote_enabled() -> bool:
    return os.getenv("ENABLE_LN7_AUTO_PROMOTE", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def canary_pct() -> float:
    try:
        return max(1.0, min(50.0, float(os.getenv("LN7_CANARY_TRAFFIC_PCT", "5"))))
    except ValueError:
        return 5.0


async def start_canary(db_pool, revision_id: str, *, incumbent_id: str = "LN7-baseline") -> bool:
    if not db_pool or not revision_id:
        return False
    try:
        from app.services.ln7_revision import set_shadow
        await set_shadow(db_pool, revision_id)
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ln7_canary_state
                    (revision_id, traffic_pct, status, incumbent_id, notes)
                VALUES ($1, $2, 'active', $3, 'continuous_gated')
                ON CONFLICT (revision_id) DO UPDATE SET
                    status = 'active',
                    traffic_pct = EXCLUDED.traffic_pct,
                    started_at = NOW(),
                    incumbent_id = EXCLUDED.incumbent_id
                """,
                revision_id,
                canary_pct(),
                incumbent_id,
            )
        return True
    except Exception as exc:
        logger.warning("ln7_canary start: %s", exc)
        return False


async def _passes_for_revision(db_pool, revision_id: str, *, limit: int = 50) -> List[bool]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT passed FROM ln7_coding_outcomes
            WHERE revision_id = $1 AND generator = 'ln7'
              AND (metrics_json->>'pack') IS NOT NULL
            ORDER BY created_at DESC LIMIT $2
            """,
            revision_id,
            limit,
        )
    return [bool(r["passed"]) for r in rows]


async def evaluate_canary(db_pool, revision_id: str) -> Dict[str, Any]:
    """Run statistical gate vs incumbent; promote or leave in shadow / rollback."""
    from app.services.ln7_bakeoff_engine import statistical_gate

    if not db_pool:
        return {"ok": False, "error": "no_db"}
    try:
        async with db_pool.acquire() as conn:
            canary = await conn.fetchrow(
                "SELECT * FROM ln7_canary_state WHERE revision_id = $1 AND status = 'active'",
                revision_id,
            )
            inc_id = (canary or {}).get("incumbent_id") if canary else None
            if not inc_id:
                inc_id = await conn.fetchval(
                    "SELECT revision_id FROM ln7_revisions WHERE active = TRUE LIMIT 1"
                ) or "LN7-baseline"
        cand = await _passes_for_revision(db_pool, revision_id)
        inc = await _passes_for_revision(db_pool, str(inc_id))
        gate = statistical_gate(cand, inc, min_tasks=3)
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ln7_canary_state
                SET pass_rate_json = $2::jsonb, last_check_at = NOW()
                WHERE revision_id = $1
                """,
                revision_id,
                __import__("json").dumps(gate),
            )
        if not gate.get("ok"):
            # Regression: rollback canary status (serving stays on incumbent)
            if len(cand) >= 3 and float((gate.get("candidate_ci") or {}).get("mean") or 0) < float(
                gate.get("incumbent_point") or 0
            ) - 0.15:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE ln7_canary_state SET status = 'rolled_back', notes = $2
                        WHERE revision_id = $1
                        """,
                        revision_id,
                        gate.get("reason") or "regression",
                    )
                    await conn.execute(
                        "UPDATE ln7_revisions SET status = 'rolled_back' WHERE revision_id = $1 AND active = FALSE",
                        revision_id,
                    )
                return {"ok": False, "action": "rolled_back", "gate": gate}
            return {"ok": False, "action": "hold_shadow", "gate": gate}

        if not auto_promote_enabled():
            return {
                "ok": True,
                "action": "await_ceo",
                "gate": gate,
                "hint": "ENABLE_LN7_AUTO_PROMOTE=true to flip serving under policy",
            }

        from app.services.ln7_revision import activate_revision
        act = await activate_revision(
            db_pool,
            revision_id,
            promoted_by="policy_auto",
            ceo_decision_id="ln7_continuous_gate",
        )
        if act.get("ok"):
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE ln7_canary_state SET status = 'promoted' WHERE revision_id = $1",
                    revision_id,
                )
            return {"ok": True, "action": "promoted", "gate": gate, "activate": act}
        return {"ok": False, "action": "activate_failed", "gate": gate, "activate": act}
    except Exception as exc:
        logger.warning("ln7_canary evaluate: %s", exc)
        return {"ok": False, "error": str(exc)[:300]}
