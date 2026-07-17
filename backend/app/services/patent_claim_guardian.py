"""
Patent claim↔code guardian — worker ants propose; CEO (YELLOW) for Foundation maps.

Heuristic crystal_patent_field tags auto-approve GREEN (digest only, no CEO email).

# QUANTUM-CRYSTAL-ARCH — Dual-COO patent perimeter
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("patent_claim_guardian")

# QUANTUM-CRYSTAL-ARCH — heuristic sweep tags; not Foundation claim maps
CRYSTAL_PATENT_FAMILY = "crystal_patent_field"


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
    is_crystal_heuristic = (family_id or "") == CRYSTAL_PATENT_FAMILY
    initial_status = "approved" if is_crystal_heuristic else "proposed"
    risk_class = "GREEN" if is_crystal_heuristic else "YELLOW"
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO patent_claim_map
                    (family_id, claim_ref, claim_text, code_path, function_name,
                     status, proposed_by, risk_class, reviewed_at, reviewed_by)
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8,
                    CASE WHEN $6 = 'approved' THEN NOW() ELSE NULL END,
                    CASE WHEN $6 = 'approved' THEN 'auto_green' ELSE NULL END
                )
                ON CONFLICT (family_id, claim_ref, code_path, function_name)
                DO UPDATE SET
                    claim_text = COALESCE(EXCLUDED.claim_text, patent_claim_map.claim_text),
                    proposed_by = EXCLUDED.proposed_by,
                    risk_class = CASE
                        WHEN patent_claim_map.family_id = 'crystal_patent_field'
                        THEN 'GREEN'
                        ELSE patent_claim_map.risk_class
                    END,
                    status = CASE
                        WHEN patent_claim_map.family_id = 'crystal_patent_field'
                             AND patent_claim_map.status = 'proposed'
                        THEN 'approved'
                        ELSE patent_claim_map.status
                    END,
                    reviewed_at = CASE
                        WHEN patent_claim_map.family_id = 'crystal_patent_field'
                             AND patent_claim_map.status = 'proposed'
                        THEN NOW()
                        ELSE patent_claim_map.reviewed_at
                    END,
                    reviewed_by = CASE
                        WHEN patent_claim_map.family_id = 'crystal_patent_field'
                             AND patent_claim_map.status = 'proposed'
                        THEN 'auto_green'
                        ELSE patent_claim_map.reviewed_by
                    END
                RETURNING id, status, family_id
                """,
                family_id[:120],
                claim_ref[:120],
                (claim_text or "")[:4000],
                (code_path or "")[:500],
                (function_name or "")[:200],
                initial_status,
                proposed_by[:80],
                risk_class,
            )
        status = (row["status"] if row else "") or ""
        # QUANTUM-CRYSTAL-ARCH — no CEO email for heuristic / already-approved tags
        if is_crystal_heuristic or status == "approved":
            return {
                "status": "ok",
                "id": row["id"] if row else None,
                "risk": "GREEN",
                "ceo_notified": False,
            }
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
        return {
            "status": "ok",
            "id": row["id"] if row else None,
            "risk": "YELLOW",
            "ceo_notified": True,
        }
    except Exception as e:
        logger.warning("propose_claim_tag: %s", e)
        return {"status": "error", "error": str(e)[:300]}


async def list_pending_for_ceo(db_pool, limit: int = 50) -> List[Dict[str, Any]]:
    """Foundation claim maps only — exclude heuristic crystal_patent_field."""
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
                  AND family_id != $2
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
                CRYSTAL_PATENT_FAMILY,
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


async def sweep_patent_crystals(db_pool, *, limit: int = 25) -> int:
    """Propose claim↔code tags from high-confidence patent-domain crystals."""
    if not db_pool:
        return 0
    proposed = 0
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, LEFT(crystal_text, 400) AS snippet, confidence
                FROM nate_intelligence_crystals
                WHERE LOWER(COALESCE(domain, '')) = 'patent'
                  AND superseded_by IS NULL
                  AND confidence >= 0.55
                ORDER BY confidence DESC, created_at DESC
                LIMIT $1
                """,
                limit,
            )
        for row in rows:
            snippet = (row["snippet"] or "").strip()
            if len(snippet) < 20:
                continue
            # Heuristic code path from crystal text
            code_path = "patent/QUANTUM_EMOTIONAL_COHERENCE_PATENT.md"
            for marker, path in (
                ("odpe", "backend/app/services/odpe_engine.py"),
                ("crystal", "backend/app/websocket/crystal_recall_bridge.py"),
                ("nevedal", "backend/app/services/nevedal_engine.py"),
                ("voice", "backend/app/services/twilio_grok_xtts_pipeline.py"),
                ("liminal", "backend/app/services/language_drift_monitor.py"),
            ):
                if marker in snippet.lower():
                    code_path = path
                    break
            r = await propose_claim_tag(
                db_pool,
                family_id="crystal_patent_field",
                claim_ref=f"crystal_{row['id']}",
                code_path=code_path,
                function_name="crystal_text",
                claim_text=snippet[:2000],
                proposed_by="patent_crystal_sweep",
            )
            if r.get("status") == "ok":
                proposed += 1
    except Exception as e:
        logger.warning("sweep_patent_crystals: %s", e)
    return proposed
