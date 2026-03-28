"""
Cycle Detection Engine REST API.

8 endpoints for multi-domain behavioral cycle detection, prediction,
convergence risk analysis, and manual observation recording.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

try:
    from app.services.api_server import get_current_user, require_coach
except ImportError:
    async def require_coach():
        return {"role": "ADMIN"}
    async def get_current_user():
        return {"role": "ADMIN"}

router = APIRouter(prefix="/api/predictive/cycles", tags=["cycles"], dependencies=[Depends(require_coach)])


class ObservationRequest(BaseModel):
    user_id: str
    domain: str
    value: float
    metadata: dict = {}


@router.get("/health")
async def cycle_health(request: Request):
    engine = getattr(request.app.state, "cycle_detection_engine", None)
    return {
        "status": "ok",
        "cycle_engine": engine is not None,
        "domains_configured": 12 if engine else 0,
        "domains": list(getattr(__import__("app.services.cycle_detection_engine",
            fromlist=["CYCLE_DOMAINS"]), "CYCLE_DOMAINS", {}).keys()) if engine else [],
    }


@router.get("/detect/{user_id}")
async def detect_all_cycles(user_id: str, request: Request):
    engine = getattr(request.app.state, "cycle_detection_engine", None)
    if not engine:
        raise HTTPException(503, "Cycle detection engine not initialized")
    return await engine.detect_cycles(user_id)


@router.get("/detect/{user_id}/{domain}")
async def detect_domain_cycles(user_id: str, domain: str, request: Request):
    engine = getattr(request.app.state, "cycle_detection_engine", None)
    if not engine:
        raise HTTPException(503, "Cycle detection engine not initialized")
    return await engine.detect_cycles(user_id, domain=domain)


@router.get("/predict/{user_id}")
async def predict_events(user_id: str, request: Request, horizon_days: int = 30):
    engine = getattr(request.app.state, "cycle_detection_engine", None)
    if not engine:
        raise HTTPException(503, "Cycle detection engine not initialized")
    return await engine.predict_next_events(user_id, horizon_days)


@router.get("/convergence/{user_id}")
async def convergence_risk(user_id: str, request: Request, horizon_days: int = 14):
    engine = getattr(request.app.state, "cycle_detection_engine", None)
    if not engine:
        raise HTTPException(503, "Cycle detection engine not initialized")
    return await engine.get_convergence_risk(user_id, horizon_days)


@router.get("/family/{family_id}")
async def family_cycles(family_id: str, request: Request):
    engine = getattr(request.app.state, "cycle_detection_engine", None)
    if not engine:
        raise HTTPException(503, "Cycle detection engine not initialized")
    return await engine.get_family_cycles(family_id)


@router.get("/group/{group_id}")
async def group_cycles(group_id: str, request: Request):
    engine = getattr(request.app.state, "cycle_detection_engine", None)
    if not engine:
        raise HTTPException(503, "Cycle detection engine not initialized")
    return await engine.get_group_cycles(group_id)


@router.post("/observe")
async def record_observation(body: ObservationRequest, request: Request):
    engine = getattr(request.app.state, "cycle_detection_engine", None)
    if not engine:
        raise HTTPException(503, "Cycle detection engine not initialized")
    return await engine.record_observation(body.user_id, body.domain, body.value, body.metadata)
