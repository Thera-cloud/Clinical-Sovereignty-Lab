"""
CEO Dual-COO API — Nathan morning inbox, patent approve, clinical apply.

# QUANTUM-CRYSTAL-ARCH — CEO inbox surface
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.api_server import require_admin

router = APIRouter(prefix="/api/ceo", tags=["ceo-dual-coo"])


class AckBody(BaseModel):
    item_id: str = ""
    ack_all: bool = False


class PatentApproveBody(BaseModel):
    ids: List[int] = Field(default_factory=list)


class ClinicalApplyBody(BaseModel):
    shadow_ids: List[int] = Field(default_factory=list)


@router.get("/health")
async def ceo_health():
    return {"status": "ok", "service": "ceo_dual_coo"}


@router.get("/inbox")
async def ceo_inbox(
    limit: int = 50,
    _: Dict[str, Any] = Depends(require_admin),
):
    from app.websocket.cli_dual_coo import ceo_inbox_summary, peek_ceo_inbox

    items = peek_ceo_inbox(max(1, min(limit, 100)))
    summary = ceo_inbox_summary()
    return {"status": "ok", "summary": summary, "items": items}


@router.post("/inbox/ack")
async def ceo_inbox_ack(
    body: AckBody,
    _: Dict[str, Any] = Depends(require_admin),
):
    from app.websocket.cli_dual_coo import ack_ceo_inbox

    return ack_ceo_inbox(item_id=body.item_id, ack_all=body.ack_all)


@router.get("/patent-tags/pending")
async def patent_pending(
    request: Request,
    _: Dict[str, Any] = Depends(require_admin),
):
    from app.services.patent_claim_guardian import list_pending_for_ceo

    db = getattr(request.app.state, "db_pool", None)
    rows = await list_pending_for_ceo(db, limit=100)
    return {"status": "ok", "pending": rows, "count": len(rows)}


@router.post("/patent-tags/approve")
async def patent_approve(
    body: PatentApproveBody,
    request: Request,
    user: Dict[str, Any] = Depends(require_admin),
):
    from app.services.patent_claim_guardian import ceo_approve_tags

    db = getattr(request.app.state, "db_pool", None)
    who = str(user.get("username") or user.get("name") or "DrNevedal1")
    return await ceo_approve_tags(db, body.ids, reviewed_by=who)


@router.get("/clinical-shadows")
async def clinical_shadows(
    request: Request,
    _: Dict[str, Any] = Depends(require_admin),
):
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        return {"status": "ok", "rows": []}
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, crystal_id, domain, current_confidence, proposed_delta,
                   sample_size, reasoning, computed_at
            FROM crystal_confidence_shadow
            WHERE computed_at > NOW() - INTERVAL '14 days'
              AND LOWER(COALESCE(domain, '')) IN ('clinical', 'defense')
              AND ABS(proposed_delta) > 0.0001
            ORDER BY ABS(proposed_delta) DESC
            LIMIT 50
            """
        )
    return {"status": "ok", "rows": [dict(r) for r in rows]}


@router.post("/clinical-apply")
async def clinical_apply(
    body: ClinicalApplyBody,
    request: Request,
    user: Dict[str, Any] = Depends(require_admin),
):
    """CEO-RED only — apply clinical/defense shadow deltas with forensic log."""
    from app.services.crystal_outcome_apply import ceo_apply_clinical_shadows

    db = getattr(request.app.state, "db_pool", None)
    who = str(user.get("username") or user.get("name") or "DrNevedal1")
    result = await ceo_apply_clinical_shadows(
        db, body.shadow_ids, approved_by=who,
    )
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error") or "apply_failed")
    return result


@router.get("/insight-briefs")
async def insight_briefs(
    request: Request,
    status: str = "queued",
    _: Dict[str, Any] = Depends(require_admin),
):
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        return {"status": "ok", "briefs": []}
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, client_user_id, source, title, body, risk_class,
                   status, created_at
            FROM coach_insight_briefs
            WHERE ($1 = 'all' OR status = $1)
            ORDER BY created_at DESC
            LIMIT 50
            """,
            status,
        )
    return {"status": "ok", "briefs": [dict(r) for r in rows]}


@router.get("/loop-status")
async def loop_status(
    request: Request,
    _: Dict[str, Any] = Depends(require_admin),
):
    from app.websocket.cli_dual_coo import (
        ceo_inbox_summary,
        cloud_sole_failover_active,
        peer_queen_alive,
    )

    closer = getattr(request.app.state, "dual_coo_loop_closer", None)
    return {
        "status": "ok",
        "inbox": ceo_inbox_summary(),
        "failover_cloud_sole": cloud_sole_failover_active(),
        "peer_mac": peer_queen_alive("cloud"),
        "closer": {
            "present": closer is not None,
            "cycles": getattr(closer, "_cycles", 0) if closer else 0,
            "stats": getattr(closer, "_stats", {}) if closer else {},
        },
    }
