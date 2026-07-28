"""
CEO Dual-COO API — Nathan morning inbox, patent approve, clinical apply.

# QUANTUM-CRYSTAL-ARCH — CEO inbox surface
"""

from __future__ import annotations

import os
import secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.api_server import require_admin

router = APIRouter(prefix="/api/ceo", tags=["ceo-dual-coo"])


class QueenBeatBody(BaseModel):
    role: str = "mac"
    meta: Optional[Dict[str, Any]] = None


class AckBody(BaseModel):
    item_id: str = ""
    ack_all: bool = False


class DecideBody(BaseModel):
    """CEO dashboard decisions — same verbs as email/SMS (ACK/APPROVE/REJECT/HOLD)."""
    decision: str = "ACK"
    item_id: str = ""
    decide_all: bool = False


class PatentApproveBody(BaseModel):
    ids: List[int] = Field(default_factory=list)


class ClinicalApplyBody(BaseModel):
    shadow_ids: List[int] = Field(default_factory=list)


class PatentArchiveBody(BaseModel):
    reason: str = ""


class PatentInquireBody(BaseModel):
    body: str = ""
    author: str = "ceo"
    parent_id: Optional[int] = None


class PatentDecideBody(BaseModel):
    decision: str = ""
    note: str = ""
    dimension_tags: List[str] = Field(default_factory=list)


class PatentPromoteBody(BaseModel):
    library_id: int = 0


@router.get("/health")
async def ceo_health():
    return {"status": "ok", "service": "ceo_dual_coo"}


@router.post("/queen-beat")
async def ceo_queen_beat(request: Request, body: Optional[QueenBeatBody] = None):
    """Mac Queen heartbeat when Mac cannot reach VPC Redis (residential Twin).

    Auth: Bearer MAC_AGENT_TOKEN (same secret as MAC_AGENT_URL probes).
    Writes Redis coo_beat so cloud_sole failover sees a live Mac peer.
    """
    expected = (os.getenv("MAC_AGENT_TOKEN") or "").strip()
    auth = request.headers.get("Authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not expected or not token or not secrets.compare_digest(token, expected):
        raise HTTPException(401, "unauthorized")
    payload = body or QueenBeatBody()
    role = (payload.role or "mac").strip().lower()
    if role not in ("mac", "cloud"):
        raise HTTPException(400, "role must be mac or cloud")
    from app.websocket.cli_dual_coo import beat_queen

    meta = dict(payload.meta or {})
    meta.setdefault("via", "mac_http_beat")
    ok = beat_queen(role, meta=meta)
    return {"status": "ok" if ok else "redis_fail", "beat": bool(ok), "role": role}


@router.get("/inbox")
async def ceo_inbox(
    limit: int = 50,
    _: Dict[str, Any] = Depends(require_admin),
):
    from app.services.ceo_inbox_notify import enrich_ceo_inbox_item
    from app.websocket.cli_dual_coo import ceo_inbox_summary, peek_ceo_inbox

    items = [
        enrich_ceo_inbox_item(it)
        for it in peek_ceo_inbox(max(1, min(limit, 100)))
    ]
    summary = ceo_inbox_summary()
    return {"status": "ok", "summary": summary, "items": items}


@router.post("/inbox/ack")
async def ceo_inbox_ack(
    body: AckBody,
    _: Dict[str, Any] = Depends(require_admin),
):
    """Legacy dismiss — prefer POST /inbox/decide with decision=ACK."""
    from app.websocket.cli_dual_coo import ack_ceo_inbox

    return ack_ceo_inbox(item_id=body.item_id, ack_all=body.ack_all)


@router.post("/inbox/decide")
async def ceo_inbox_decide(
    body: DecideBody,
    request: Request,
    user: Dict[str, Any] = Depends(require_admin),
):
    """Apply ACK / APPROVE / REJECT / HOLD to one inbox item or all pending.

    Matches email button semantics: updates strategy_proposals when present,
    clears Redis CEO inbox, and runs APPROVE apply side-effects.
    # QUANTUM-CRYSTAL-ARCH
    """
    from app.services.ceo_inbox_notify import decide_ceo_inbox_items

    decision = (body.decision or "").strip().upper()
    if decision not in ("ACK", "APPROVE", "REJECT", "HOLD"):
        raise HTTPException(
            400,
            "decision must be ACK, APPROVE, REJECT, or HOLD",
        )
    if not body.decide_all and not (body.item_id or "").strip():
        raise HTTPException(400, "item_id required unless decide_all=true")

    db = getattr(request.app.state, "db_pool", None)
    who = str(user.get("username") or user.get("name") or "DrNevedal1")
    result = await decide_ceo_inbox_items(
        db_pool=db,
        decision=decision,
        item_id=(body.item_id or "").strip(),
        decide_all=bool(body.decide_all),
        approver=who,
    )
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error") or "decide_failed")
    return result


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


# --- Patent idea library / review (QUANTUM-CRYSTAL-ARCH) ---


def _lib_engine(request: Request):
    from app.services.patent_idea_library_engine import PatentIdeaLibraryEngine

    db = getattr(request.app.state, "db_pool", None)
    return PatentIdeaLibraryEngine(db)


def _refl_engine(request: Request):
    from app.services.patent_reflection_engine import PatentReflectionEngine

    db = getattr(request.app.state, "db_pool", None)
    lib = _lib_engine(request)
    return PatentReflectionEngine(db, library_engine=lib)


@router.get("/patent-library")
async def patent_library_list(
    request: Request,
    status: str = "",
    category: str = "",
    topic: str = "",
    sort: str = "rank",
    include_archived: bool = False,
    grouped: bool = False,
    _: Dict[str, Any] = Depends(require_admin),
):
    eng = _lib_engine(request)
    rows = await eng.list_library(
        status=status or None,
        category=category or None,
        topic=topic or None,
        sort=sort or "rank",
        include_archived=include_archived or (status == "archived"),
    )
    out: Dict[str, Any] = {
        "status": "ok",
        "ideas": rows,
        "count": len(rows),
        "study_cap_remaining": await eng.study_cap_remaining(),
    }
    if grouped:
        out["grouped"] = eng.group_by_category(rows)
    return out


@router.get("/patent-library/weights")
async def patent_library_weights(
    request: Request,
    _: Dict[str, Any] = Depends(require_admin),
):
    eng = _lib_engine(request)
    weights = await eng.get_weights()
    history: List[Dict[str, Any]] = []
    db = getattr(request.app.state, "db_pool", None)
    if db:
        async with db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, weights_before, weights_after, reflection_id, decision, created_at
                FROM patent_rank_weight_history
                ORDER BY created_at DESC LIMIT 10
                """
            )
        for r in rows:
            d = dict(r)
            if hasattr(d.get("created_at"), "isoformat"):
                d["created_at"] = d["created_at"].isoformat()
            history.append(d)
    return {"status": "ok", "weights": weights, "history": history}


@router.post("/patent-library/{library_id}/renew")
async def patent_library_renew(
    library_id: int,
    request: Request,
    _: Dict[str, Any] = Depends(require_admin),
):
    eng = _lib_engine(request)
    return await eng.rescore_idea(library_id, reason="manual")


@router.post("/patent-library/{library_id}/archive")
async def patent_library_archive(
    library_id: int,
    body: PatentArchiveBody,
    request: Request,
    user: Dict[str, Any] = Depends(require_admin),
):
    eng = _lib_engine(request)
    who = str(user.get("username") or "DrNevedal1")
    return await eng.archive_idea(library_id, reason=body.reason, by=who)


@router.post("/patent-library/{library_id}/unarchive")
async def patent_library_unarchive(
    library_id: int,
    request: Request,
    _: Dict[str, Any] = Depends(require_admin),
):
    eng = _lib_engine(request)
    return await eng.unarchive_idea(library_id)


@router.post("/patent-library/promote")
async def patent_library_promote(
    body: PatentPromoteBody,
    request: Request,
    _: Dict[str, Any] = Depends(require_admin),
):
    """Manual promote override — still creates a reflection for review."""
    if not body.library_id:
        raise HTTPException(400, "library_id required")
    refl = _refl_engine(request)
    return await refl.promote_from_library(body.library_id, promote_reason="manual")


@router.get("/patent-reflections")
async def patent_reflections_list(
    request: Request,
    status: str = "",
    _: Dict[str, Any] = Depends(require_admin),
):
    refl = _refl_engine(request)
    rows = await refl.list_reflections(status=status or None)
    return {"status": "ok", "reflections": rows, "count": len(rows)}


@router.get("/patent-reflections/{reflection_id}")
async def patent_reflection_get(
    reflection_id: int,
    request: Request,
    _: Dict[str, Any] = Depends(require_admin),
):
    refl = _refl_engine(request)
    row = await refl.get_reflection(reflection_id)
    if not row:
        raise HTTPException(404, "not found")
    return {"status": "ok", "reflection": row}


@router.post("/patent-reflections/{reflection_id}/inquire")
async def patent_reflection_inquire(
    reflection_id: int,
    body: PatentInquireBody,
    request: Request,
    _: Dict[str, Any] = Depends(require_admin),
):
    if not (body.body or "").strip():
        raise HTTPException(400, "body required")
    author = (body.author or "ceo").strip().lower()
    if author not in ("ceo", "dual_coo", "queen_mac", "queen_cloud"):
        author = "ceo"
    refl = _refl_engine(request)
    result = await refl.add_inquiry(
        reflection_id,
        author=author,
        body=body.body,
        parent_id=body.parent_id,
    )
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error") or "inquire_failed")
    return result


@router.post("/patent-reflections/{reflection_id}/ready")
async def patent_reflection_ready(
    reflection_id: int,
    request: Request,
    _: Dict[str, Any] = Depends(require_admin),
):
    refl = _refl_engine(request)
    result = await refl.mark_ready(reflection_id)
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error") or "ready_failed")
    return result


@router.post("/patent-reflections/{reflection_id}/decide")
async def patent_reflection_decide(
    reflection_id: int,
    body: PatentDecideBody,
    request: Request,
    user: Dict[str, Any] = Depends(require_admin),
):
    decision = (body.decision or "").strip().upper()
    if decision not in ("REJECT", "HOLD", "APPROVE_CLI", "APPROVE_IDE"):
        raise HTTPException(
            400,
            "decision must be REJECT, HOLD, APPROVE_CLI, or APPROVE_IDE",
        )
    who = str(user.get("username") or user.get("name") or "DrNevedal1")
    refl = _refl_engine(request)
    result = await refl.decide(
        reflection_id,
        decision=decision,
        reviewed_by=who,
        dimension_tags=body.dimension_tags,
        note=body.note,
    )
    if result.get("status") == "error":
        code = 400
        raise HTTPException(code, result.get("error") or result.get("detail") or "decide_failed")
    return result

