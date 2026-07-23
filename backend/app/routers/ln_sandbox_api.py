"""LN Sandbox DOJO admin API — status, corpus, promotion gate, manual cycle."""
from __future__ import annotations

import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.services.api_server import require_admin

logger = logging.getLogger("sovereign.ln_sandbox_api")

router = APIRouter(prefix="/api/ln-sandbox", tags=["ln-sandbox"])


class PromoteRequest(BaseModel):
    corpus_id: str
    requested_by: Optional[str] = "admin"


class DecideRequest(BaseModel):
    corpus_id: str
    approve: bool
    notes: str = ""


class RunCycleRequest(BaseModel):
    tracks: Optional[list] = Field(
        default=None,
        description="Subset: clinical_strategy, engineering, client_prep",
    )


@router.get("/health")
async def health():
    return {"status": "ok", "service": "ln_sandbox"}


@router.get("/status")
async def status(request: Request, admin: Dict = Depends(require_admin)):
    eng = getattr(request.app.state, "ln_sandbox_engine", None)
    from app.services.ln_sandbox_context import get_sandbox_stats

    stats = await get_sandbox_stats(getattr(request.app.state, "db_pool", None))
    return {
        "status": "ok",
        "engine": eng.get_status() if eng and hasattr(eng, "get_status") else None,
        "stats": stats,
    }


@router.get("/corpus")
async def list_corpus(
    request: Request,
    status_filter: str = Query("draft", alias="status"),
    track: Optional[str] = None,
    limit: int = Query(40, ge=1, le=200),
    admin: Dict = Depends(require_admin),
):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "db unavailable")
    clauses = ["status = $1"]
    args: list = [status_filter]
    if track:
        clauses.append(f"track = ${len(args) + 1}")
        args.append(track)
    args.append(limit)
    sql = f"""
        SELECT id::text, track, kind, title, LEFT(body, 400) AS body_preview,
               score, confidence, scope, target_user_id, status, created_at
        FROM ln_sandbox_practice_corpus
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC
        LIMIT ${len(args)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return {
        "status": "ok",
        "items": [dict(r) for r in rows],
    }


@router.get("/candidates/{username}")
async def candidates(
    username: str,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    from app.services.ln_sandbox_context import get_sandbox_candidates_for_user

    pool = getattr(request.app.state, "db_pool", None)
    text = await get_sandbox_candidates_for_user(pool, username)
    return {"status": "ok", "username": username, "context": text or ""}


@router.post("/promote/enqueue")
async def promote_enqueue(
    body: PromoteRequest,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    from app.services.ln_sandbox_promotion import enqueue_promotion

    pool = getattr(request.app.state, "db_pool", None)
    who = body.requested_by or admin.get("username") or "admin"
    result = await enqueue_promotion(pool, body.corpus_id, requested_by=who)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "enqueue_failed")
    return result


@router.post("/promote/decide")
async def promote_decide(
    body: DecideRequest,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    from app.services.ln_sandbox_promotion import decide_promotion

    pool = getattr(request.app.state, "db_pool", None)
    who = admin.get("username") or "admin"
    result = await decide_promotion(
        pool,
        body.corpus_id,
        approve=body.approve,
        decided_by=who,
        notes=body.notes,
        app_state=request.app.state,
    )
    if not result.get("ok"):
        code = 422 if result.get("error") == "validator_blocked" else 400
        raise HTTPException(code, detail=result)
    return result


@router.post("/run-cycle")
async def run_cycle(
    body: RunCycleRequest,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    eng = getattr(request.app.state, "ln_sandbox_engine", None)
    if not eng:
        raise HTTPException(503, "ln_sandbox_engine not loaded")
    result = await eng.run_cycle(force_tracks=body.tracks)
    return {"status": "ok", "result": result}
