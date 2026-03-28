"""
F-Code API — ICD-10-CM F-code suggestions, assignments, and history.

Little Nate suggests codes at milestone windows; coaches assign the final codes.
"""

import json
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.services.api_server import get_current_user, require_coach

logger = logging.getLogger("nate.fcode_api")

router = APIRouter(
    prefix="/api/fcodes",
    tags=["fcodes"],
    dependencies=[Depends(require_coach)],
)


class FCodeAssignment(BaseModel):
    code: str
    description: str
    milestone_window: str = "30d"
    notes: Optional[str] = None


class FCodeAssignRequest(BaseModel):
    fcodes: List[FCodeAssignment]


@router.get("/health")
async def fcode_health():
    return {"status": "ok", "service": "fcode_engine"}


@router.get("/suggestions/{client_id}")
async def get_suggestions(client_id: str, window: str = "30d", request: Request = None, user: Dict = Depends(require_coach)):
    """Get Little Nate's F-code suggestions for a client at a milestone window."""
    engine = getattr(request.app.state, "fcode_engine", None)
    if not engine:
        raise HTTPException(503, "F-Code engine unavailable")

    suggestions = await engine.get_suggestions(client_id, window)
    return {"client_id": client_id, "window": window, "suggestions": suggestions}


@router.post("/assign/{client_id}")
async def assign_fcodes(client_id: str, req: FCodeAssignRequest, request: Request = None, user: Dict = Depends(require_coach)):
    """Coach assigns F-codes (up to 4) to a client."""
    engine = getattr(request.app.state, "fcode_engine", None)
    if not engine:
        raise HTTPException(503, "F-Code engine unavailable")

    coach_id = user.get("hardware_id", user.get("username", ""))
    fcodes = [fc.dict() for fc in req.fcodes]
    assigned = await engine.assign_fcodes(client_id, coach_id, fcodes)
    return {"client_id": client_id, "assigned": assigned, "count": len(assigned)}


@router.get("/history/{client_id}")
async def get_history(client_id: str, request: Request = None, user: Dict = Depends(require_coach)):
    """Full history of assigned + suggested codes for a client."""
    engine = getattr(request.app.state, "fcode_engine", None)
    if not engine:
        raise HTTPException(503, "F-Code engine unavailable")

    history = await engine.get_history(client_id)
    return {"client_id": client_id, **history}


@router.get("/compare/{client_id}")
async def compare_fcodes(client_id: str, request: Request = None, user: Dict = Depends(require_coach)):
    """Side-by-side: coach-assigned vs Nate-suggested over time."""
    engine = getattr(request.app.state, "fcode_engine", None)
    if not engine:
        raise HTTPException(503, "F-Code engine unavailable")

    comparison = await engine.get_compare(client_id)
    return {"client_id": client_id, **comparison}


@router.get("/family/{family_id}")
async def family_correlations(family_id: str, request: Request = None, user: Dict = Depends(require_coach)):
    """Transgenerational F-code correlations across a family."""
    engine = getattr(request.app.state, "fcode_engine", None)
    if not engine:
        raise HTTPException(503, "F-Code engine unavailable")

    correlations = await engine.get_family_correlations(family_id)
    return {"family_id": family_id, "correlations": correlations}


@router.get("/reference")
async def fcode_reference(request: Request = None, user: Dict = Depends(require_coach)):
    """List available ICD-10-CM F-codes from reference table."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        return {"codes": [], "count": 0}

    async with db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT code, description, category, common_symptoms FROM fcode_reference ORDER BY code"
        )

    codes = [
        {
            "code": r["code"],
            "description": r["description"],
            "category": r["category"],
            "symptoms": r["common_symptoms"] or [],
        }
        for r in rows
    ]
    return {"codes": codes, "count": len(codes)}
