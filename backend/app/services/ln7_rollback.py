"""Shared LN7 serving rollback — one function, multiple sensors.

Quality / latency / error monitors all call rollback_serving_revision.
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("ln7_rollback")


async def rollback_serving_revision(
    db_pool,
    revision_id: str,
    *,
    reason: str,
    trigger: str = "ops",
    promoted_by: str = "system_rollback",
) -> Dict[str, Any]:
    """Deactivate candidate, restore incumbent/predecessor, suppress 30d, notify."""
    if not db_pool:
        return {"ok": False, "error": "no_db"}
    rid = (revision_id or "").strip()
    if not rid:
        return {"ok": False, "error": "revision_id_required"}

    predecessor: Optional[str] = None
    try:
        async with db_pool.acquire() as conn:
            canary = await conn.fetchrow(
                "SELECT incumbent_id FROM ln7_canary_state WHERE revision_id = $1",
                rid,
            )
            if canary and canary.get("incumbent_id"):
                predecessor = str(canary["incumbent_id"]).strip()
            if not predecessor:
                predecessor = await conn.fetchval(
                    """
                    SELECT revision_id FROM ln7_revisions
                    WHERE revision_id <> $1
                      AND status IN ('active', 'rolled_back')
                      AND COALESCE(NULLIF(TRIM(harness_config_json->>'tier'), ''), 'deep') = (
                          SELECT COALESCE(NULLIF(TRIM(harness_config_json->>'tier'), ''), 'deep')
                          FROM ln7_revisions WHERE revision_id = $1
                      )
                    ORDER BY
                      CASE WHEN active THEN 0 ELSE 1 END,
                      created_at DESC NULLS LAST
                    LIMIT 1
                    """,
                    rid,
                )
            await conn.execute(
                """
                UPDATE ln7_revisions
                SET active = FALSE, status = 'rolled_back'
                WHERE revision_id = $1
                """,
                rid,
            )
            await conn.execute(
                """
                UPDATE ln7_canary_state
                SET status = 'rolled_back',
                    notes = $2,
                    last_check_at = NOW()
                WHERE revision_id = $1
                """,
                rid,
                f"{trigger}:{reason}"[:500],
            )
            try:
                await conn.execute(
                    """
                    INSERT INTO skyeye_activity (type, content, platform)
                    VALUES ('ln7_rollback', $1, 'ln7')
                    """,
                    f"rollback {rid} → {predecessor} trigger={trigger} reason={reason}"[:2000],
                )
            except Exception:
                pass
    except Exception as e:
        logger.warning("rollback deactivate failed: %s", e)
        return {"ok": False, "error": str(e)[:200]}

    try:
        from app.services.ln7_suppress import suppress_pattern

        await suppress_pattern(
            db_pool,
            f"revision:{rid}",
            reason=f"rollback:{trigger}:{reason}"[:240],
            days=30,
        )
    except Exception as e:
        logger.warning("suppress after rollback: %s", e)

    activate_out: Dict[str, Any] = {}
    if predecessor:
        try:
            from app.services.ln7_revision import activate_revision

            activate_out = await activate_revision(
                db_pool,
                predecessor,
                promoted_by=promoted_by,
            )
        except Exception as e:
            activate_out = {"ok": False, "error": str(e)[:200]}

    try:
        from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

        enqueue_ceo(
            risk=RISK_YELLOW,
            title=f"LN7 rollback: {rid}",
            detail=f"trigger={trigger} reason={reason} predecessor={predecessor}",
            origin="ln7_rollback",
            dedup_ttl_s=3600,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "rolled_back": rid,
        "predecessor": predecessor,
        "trigger": trigger,
        "reason": reason,
        "activate": activate_out,
    }
