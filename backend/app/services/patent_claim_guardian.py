"""
Patent claim↔code guardian — worker ants propose; CEO (YELLOW) approves.

# QUANTUM-CRYSTAL-ARCH — Dual-COO patent perimeter
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("patent_claim_guardian")


async def propose_claim_tag(
    db_pool,
    *,
    family_id: str,
    claim_ref: str,
    code_path: str,
    function_name: str = "",
    claim_text: str = "",
    proposed_by: str = "worker_ant",
) -> Dict[str, Any]:
    if not db_pool:
        return {"status": "error", "error": "no_db"}
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO patent_claim_map
                    (family_id, claim_ref, claim_text, code_path, function_name,
                     status, proposed_by, risk_class)
                VALUES ($1, $2, $3, $4, $5, 'proposed', $6, 'YELLOW')
                ON CONFLICT (family_id, claim_ref, code_path, function_name)
                DO UPDATE SET claim_text = COALESCE(EXCLUDED.claim_text, patent_claim_map.claim_text),
                              proposed_by = EXCLUDED.proposed_by
                RETURNING id, status
                """,
                family_id[:120],
                claim_ref[:120],
                (claim_text or "")[:4000],
                (code_path or "")[:500],
                (function_name or "")[:200],
                proposed_by[:80],
            )
        try:
            from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

            enqueue_ceo(
                risk=RISK_YELLOW,
                title=f"Patent tag propose: {family_id}/{claim_ref}",
                detail=f"{code_path}::{function_name}",
                origin="cloud",
                payload={"family_id": family_id, "claim_ref": claim_ref},
            )
        except Exception:
            pass
        return {"status": "ok", "id": row["id"] if row else None, "risk": "YELLOW"}
    except Exception as e:
        logger.warning("propose_claim_tag: %s", e)
        return {"status": "error", "error": str(e)[:300]}


async def list_pending_for_ceo(db_pool, limit: int = 50) -> List[Dict[str, Any]]:
    if not db_pool:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, family_id, claim_ref, code_path, function_name,
                       status, proposed_by, created_at
                FROM patent_claim_map
                WHERE status = 'proposed'
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
            )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("list_pending_for_ceo: %s", e)
        return []


async def ceo_approve_tags(
    db_pool, ids: List[int], *, reviewed_by: str = "DrNevedal1"
) -> Dict[str, Any]:
    if not db_pool or not ids:
        return {"status": "error", "error": "missing_args"}
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE patent_claim_map
                SET status = 'approved', reviewed_at = NOW(), reviewed_by = $2
                WHERE id = ANY($1::bigint[]) AND status = 'proposed'
                """,
                ids,
                reviewed_by,
            )
            n = await conn.fetchval(
                """
                SELECT COUNT(*) FROM patent_claim_map
                WHERE id = ANY($1::bigint[]) AND status = 'approved'
                """,
                ids,
            )
        return {"status": "ok", "approved": int(n or 0)}
    except Exception as e:
        return {"status": "error", "error": str(e)[:300]}
