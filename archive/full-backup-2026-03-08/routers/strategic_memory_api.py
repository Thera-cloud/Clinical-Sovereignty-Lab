"""
SOVEREIGN SWARM — Strategic Memory API Router
REST endpoints for all 6 layers of the Strategic Memory Service:
  L1 Standing Orders   L2 Insight Log      L3 Strategy Proposals
  L4 Coherence Briefings  L5 Foresight Alerts  L6 Swarm Oversight
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.api_server import require_admin
from app.services.strategic_memory import StrategicMemoryService
from app.services.exceptions import (
    ProposalNotFoundException,
    StrategyException,
)


router = APIRouter(
    prefix="/api/strategic-memory",
    tags=["Strategic Memory"],
    dependencies=[Depends(require_admin)],
)


@router.get("/status")
async def strategic_memory_status():
    """Lightweight health-check for architecture diagrams."""
    return {"status": "active", "service": "strategic_memory"}


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class StandingOrderCreate(BaseModel):
    """Body for creating a standing order."""

    title: str = Field(..., min_length=1)
    directive: str = Field(..., min_length=1)
    origin: str = "big_nate_direct"
    domain_tags: List[str] = Field(default_factory=list)
    priority: int = Field(default=5, ge=1, le=10)


class StandingOrderUpdate(BaseModel):
    """Body for updating a standing order."""

    title: Optional[str] = None
    directive: Optional[str] = None
    domain_tags: Optional[List[str]] = None
    priority: Optional[int] = Field(None, ge=1, le=10)
    active: Optional[bool] = None


class InsightCreate(BaseModel):
    """Body for logging a new insight."""

    title: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    domain: str = "operational"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list)
    source_fibre_id: Optional[UUID] = None
    source_type: str = "system"


class StrategyProposalCreate(BaseModel):
    """Body for creating a strategy proposal."""

    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    action_type: str = Field(..., min_length=1)
    proposed_by: str = "sovereign_mind"
    risk: str = Field(default="medium")
    execution_payload: Optional[Dict[str, Any]] = None
    auto_execute_hours: Optional[int] = Field(None, ge=1)


class ProposalStatusUpdate(BaseModel):
    """Body for updating proposal status."""

    status: str = Field(..., pattern="^(approved|rejected)$")
    approved_by: Optional[str] = None
    rejection_reason: Optional[str] = None


# =============================================================================
# HELPERS
# =============================================================================


def _get_service(request: Request) -> StrategicMemoryService:
    """Get StrategicMemoryService instance from app state."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")
    return StrategicMemoryService(db_pool)


def _serialize_row(row: Dict) -> Dict:
    """Convert UUIDs and other non-JSON-serializable values in a row to strings."""
    result = {}
    for k, v in row.items():
        if isinstance(v, UUID):
            result[k] = str(v)
        elif isinstance(v, list) and v and isinstance(v[0], UUID):
            result[k] = [str(x) for x in v]
        else:
            result[k] = v
    return result


# =============================================================================
# LAYER 1 — STANDING ORDERS
# =============================================================================


@router.get("/standing-orders")
async def list_standing_orders(request: Request) -> List[Dict]:
    """
    List all active standing orders (L1).
    Orders are returned by priority descending, then creation time ascending.
    """
    svc = _get_service(request)
    try:
        orders = await svc.get_active_standing_orders()
        return [_serialize_row(o) for o in orders]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/standing-orders")
async def create_standing_order(request: Request, body: StandingOrderCreate) -> Dict:
    """
    Create a new standing order (L1).
    """
    svc = _get_service(request)
    try:
        order = await svc.create_standing_order(
            title=body.title,
            directive=body.directive,
            origin=body.origin,
            domain_tags=body.domain_tags,
            priority=body.priority,
        )
        return _serialize_row(order)
    except StrategyException as e:
        raise HTTPException(status_code=400, detail=str(e.message))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/standing-orders/{order_id}")
async def update_standing_order(
    request: Request, order_id: UUID, body: StandingOrderUpdate
) -> Dict:
    """
    Update an existing standing order (L1).
    Only provided fields are updated.
    """
    svc = _get_service(request)
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    try:
        order = await svc.update_standing_order(order_id, **updates)
        return _serialize_row(order)
    except ProposalNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e.message))
    except StrategyException as e:
        raise HTTPException(status_code=400, detail=str(e.message))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/standing-orders/{order_id}")
async def deactivate_standing_order(request: Request, order_id: UUID) -> Dict:
    """
    Deactivate a standing order (L1).
    Sets active=false; order remains in storage for audit.
    """
    svc = _get_service(request)
    try:
        order = await svc.update_standing_order(order_id, active=False)
        return {"deactivated": True, "order": _serialize_row(order)}
    except ProposalNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e.message))
    except StrategyException as e:
        raise HTTPException(status_code=400, detail=str(e.message))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# LAYER 2 — INSIGHT LOG
# =============================================================================


@router.get("/insights")
async def list_insights(
    request: Request,
    domain: Optional[str] = None,
    hours: int = 24,
) -> List[Dict]:
    """
    List recent insights (L2).
    Optionally filter by domain. Default time window is 24 hours.
    """
    svc = _get_service(request)
    try:
        insights = await svc.get_recent_insights(domain=domain, hours=hours)
        return [_serialize_row(i) for i in insights]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/insights")
async def log_insight(request: Request, body: InsightCreate) -> Dict:
    """
    Log a new insight (L2).
    """
    svc = _get_service(request)
    try:
        insight = await svc.log_insight(
            title=body.title,
            body=body.body,
            domain=body.domain,
            confidence=body.confidence,
            tags=body.tags,
            source_fibre_id=body.source_fibre_id,
            source_type=body.source_type,
        )
        return _serialize_row(insight)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# LAYER 3 — STRATEGY PROPOSALS
# =============================================================================


@router.get("/proposals")
async def list_proposals(request: Request) -> List[Dict]:
    """
    List pending strategy proposals (L3).
    Returns proposals in 'proposed' or 'pending_approval' status.
    """
    svc = _get_service(request)
    try:
        proposals = await svc.get_pending_proposals()
        return [_serialize_row(p) for p in proposals]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/proposals")
async def create_proposal(request: Request, body: StrategyProposalCreate) -> Dict:
    """
    Create a new strategy proposal (L3).
    Low-risk proposals may auto-execute after the specified hours.
    """
    svc = _get_service(request)
    try:
        proposal = await svc.create_proposal(
            title=body.title,
            description=body.description,
            action_type=body.action_type,
            proposed_by=body.proposed_by,
            risk=body.risk,
            execution_payload=body.execution_payload,
            auto_execute_hours=body.auto_execute_hours,
        )
        return _serialize_row(proposal)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/proposals/{proposal_id}/status")
async def update_proposal_status(
    request: Request, proposal_id: UUID, body: ProposalStatusUpdate
) -> Dict:
    """
    Update proposal status (L3): approved or rejected.
    For approval, provide approved_by. For rejection, provide rejection_reason.
    """
    svc = _get_service(request)
    try:
        if body.status == "approved":
            proposal = await svc.approve_proposal(
                proposal_id, approved_by=body.approved_by or "big_nate"
            )
        else:
            proposal = await svc.reject_proposal(
                proposal_id, reason=body.rejection_reason or ""
            )
        return _serialize_row(proposal)
    except ProposalNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e.message))
    except StrategyException as e:
        raise HTTPException(status_code=400, detail=str(e.message))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# LAYER 4 — COHERENCE BRIEFINGS
# =============================================================================


@router.get("/briefings/latest")
async def get_latest_briefing(request: Request) -> Optional[Dict]:
    """
    Get the latest coherence briefing (L4).
    Returns null if no briefing has been generated yet.
    """
    svc = _get_service(request)
    try:
        briefing = await svc.get_latest_coherence_briefing()
        return _serialize_row(briefing) if briefing else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# LAYER 5 — FORESIGHT ALERTS
# =============================================================================


@router.get("/alerts")
async def list_alerts(request: Request) -> List[Dict]:
    """
    List active foresight alerts (L5).
    Returns unresolved alerts ordered by confidence and creation time.
    """
    svc = _get_service(request)
    try:
        alerts = await svc.get_active_foresight_alerts()
        return [_serialize_row(a) for a in alerts]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# LAYER 6 — SWARM OVERSIGHT
# =============================================================================


@router.get("/oversight")
async def get_oversight_log(request: Request, limit: int = 50) -> List[Dict]:
    """
    Get swarm oversight log (L6).
    Recent events from fibre inventory, mesh health, and lifecycle.
    """
    svc = _get_service(request)
    try:
        entries = await svc.get_swarm_oversight_log(limit=limit)
        return [_serialize_row(e) for e in entries]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
