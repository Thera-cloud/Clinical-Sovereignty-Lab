"""
QUANTUM-CRYSTAL-ARCH: Clinical technique directory REST API.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.services.api_server import get_current_user, require_coach
from app.services.clinical_technique_directory import (
    build_directory_context,
    clinical_directory_enabled,
    enrich_from_web,
    get_plan_template,
    get_technique,
    is_care_plan_request,
    load_directory,
    match_plan_template,
    maybe_create_suggested_care_plan,
    plan_template_to_step_definitions,
    search_modalities,
    search_techniques,
)

logger = logging.getLogger("nate.clinical_directory_api")

router = APIRouter(
    prefix="/api/clinical-directory",
    tags=["clinical-directory"],
)


def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    return pool


@router.get("/health")
async def health(request: Request) -> Dict[str, Any]:
    from app.services.clinical_technique_directory import (
        promoted_technique_count,
        refresh_promoted_techniques,
    )

    data = load_directory() if clinical_directory_enabled() else {}
    grown = 0
    if clinical_directory_enabled():
        pool = getattr(request.app.state, "db_pool", None)
        if pool:
            grown = await refresh_promoted_techniques(pool)
        else:
            grown = promoted_technique_count()
    seed_tech = len(data.get("techniques") or [])
    return {
        "status": "ok",
        "enabled": clinical_directory_enabled(),
        "modalities": len(data.get("modalities") or []),
        "techniques": seed_tech + grown,
        "techniques_seed": seed_tech,
        "techniques_grown": grown,
        "plan_templates": len(data.get("plan_templates") or []),
    }


@router.get("/modalities")
async def list_modalities(
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    if not clinical_directory_enabled():
        raise HTTPException(404, "Clinical technique directory disabled")
    return list(load_directory().get("modalities") or [])


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, max_length=300),
    limit: int = Query(8, ge=1, le=20),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    if not clinical_directory_enabled():
        raise HTTPException(404, "Clinical technique directory disabled")
    return {
        "query": q,
        "modalities": search_modalities(q, limit=min(5, limit)),
        "techniques": search_techniques(q, limit=limit),
        "matched_plan": match_plan_template(q),
    }


@router.get("/techniques/{technique_id}")
async def technique_detail(
    technique_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    if not clinical_directory_enabled():
        raise HTTPException(404, "Clinical technique directory disabled")
    t = get_technique(technique_id)
    if not t:
        raise HTTPException(404, "Technique not found")
    return t


@router.get("/plans")
async def list_plans(
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    if not clinical_directory_enabled():
        raise HTTPException(404, "Clinical technique directory disabled")
    return list(load_directory().get("plan_templates") or [])


@router.get("/plans/{plan_id}")
async def plan_detail(
    plan_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    if not clinical_directory_enabled():
        raise HTTPException(404, "Clinical technique directory disabled")
    p = get_plan_template(plan_id)
    if not p:
        raise HTTPException(404, "Plan template not found")
    return {**p, "step_definitions": plan_template_to_step_definitions(p)}


class CarePlanRequest(BaseModel):
    message: str = Field(..., min_length=3, max_length=2000)
    persist: bool = Field(
        True, description="Create nate_suggest plan when ENABLE_THERAPEUTIC_PLANS=true"
    )


@router.post("/care-plan/suggest")
async def suggest_care_plan(
    body: CarePlanRequest,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    if not clinical_directory_enabled():
        raise HTTPException(404, "Clinical technique directory disabled")
    uid = (
        user.get("hardware_id")
        or user.get("username")
        or user.get("user_id")
        or ""
    )
    plan = match_plan_template(body.message)
    ctx = build_directory_context(body.message)
    persisted = None
    if body.persist and uid:
        persisted = await maybe_create_suggested_care_plan(
            _pool(request), user_id=uid, user_text=body.message
        )
    return {
        "is_care_plan_request": is_care_plan_request(body.message),
        "matched_plan": plan,
        "context_preview": ctx[:4000],
        "persisted": persisted,
    }


class EnrichRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=400)


@router.post("/enrich")
async def enrich(
    body: EnrichRequest,
    request: Request,
    user: Dict[str, Any] = Depends(require_coach),
) -> Dict[str, Any]:
    if not clinical_directory_enabled():
        raise HTTPException(404, "Clinical technique directory disabled")
    proxy = getattr(request.app.state, "search_proxy", None)
    if proxy is None:
        raise HTTPException(503, "Search proxy not initialized on app.state")
    uid = user.get("username") or user.get("hardware_id") or "coach"
    block = await enrich_from_web(
        body.query,
        search_proxy=proxy,
        user_id=str(uid),
        db_pool=_pool(request),
    )
    return {"ok": bool(block), "enrichment": block[:5000]}
