"""
SOVEREIGN SWARM — Approval Protocol REST API
REST endpoints for managing strategy proposals: list pending, approve, reject, hold, modify.
Phase 1D — integrates with ApprovalProtocolService.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.services.api_server import require_admin

router = APIRouter(prefix="/api/approval", tags=["Approval Protocol"], dependencies=[Depends(require_admin)])


# ─── Request Models ──────────────────────────────────────────────────────────

class RejectRequest(BaseModel):
    """Optional reason when rejecting a proposal."""
    reason: str = ""


class ModifyRequest(BaseModel):
    """Reason/modifications when requesting changes to a proposal."""
    reason: str


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_db_pool(request: Request):
    """Get database pool from app state."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")
    return pool


def _get_approval_service(request: Request):
    """Get ApprovalProtocolService instance."""
    pool = _get_db_pool(request)
    from app.services.approval_protocol import ApprovalProtocolService
    return ApprovalProtocolService(pool)


def _serialize_proposal(row) -> Dict[str, Any]:
    """Convert asyncpg row to JSON-serializable dict."""
    d = dict(row)
    result: Dict[str, Any] = {}
    for k, v in d.items():
        if v is None:
            result[k] = None
        elif isinstance(v, UUID):
            result[k] = str(v)
        elif hasattr(v, "isoformat") and callable(getattr(v, "isoformat")):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/pending")
async def list_pending_proposals(request: Request):
    """
    List strategy proposals awaiting approval.
    Includes status in ('proposed', 'pending_approval').
    """
    pool = _get_db_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM strategy_proposals
            WHERE status IN ('proposed', 'pending_approval')
            ORDER BY created_at DESC
        """)
    return {
        "proposals": [_serialize_proposal(r) for r in rows],
        "total": len(rows),
    }


@router.post("/{proposal_id}/approve")
async def approve_proposal(request: Request, proposal_id: UUID):
    """Approve a strategy proposal."""
    svc = _get_approval_service(request)
    raw_message = "APPROVE"
    result = await svc.handle_inbound_reply(
        raw_message=raw_message,
        channel="api",
        proposal_id=proposal_id,
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{proposal_id}/reject")
async def reject_proposal(request: Request, proposal_id: UUID, body: Optional[RejectRequest] = None):
    """Reject a strategy proposal with optional reason."""
    svc = _get_approval_service(request)
    reason = body.reason if body else ""
    raw_message = f"REJECT: {reason}" if reason else "REJECT"
    result = await svc.handle_inbound_reply(
        raw_message=raw_message,
        channel="api",
        proposal_id=proposal_id,
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{proposal_id}/hold")
async def hold_proposal(request: Request, proposal_id: UUID):
    """Put a strategy proposal on hold."""
    svc = _get_approval_service(request)
    result = await svc.handle_inbound_reply(
        raw_message="HOLD",
        channel="api",
        proposal_id=proposal_id,
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{proposal_id}/modify")
async def modify_proposal(request: Request, proposal_id: UUID, body: ModifyRequest):
    """Request modifications to a strategy proposal with reason."""
    svc = _get_approval_service(request)
    raw_message = f"MODIFY: {body.reason}"
    result = await svc.handle_inbound_reply(
        raw_message=raw_message,
        channel="api",
        proposal_id=proposal_id,
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/history")
async def list_proposal_history(
    request: Request,
    status: Optional[str] = Query(None, description="Filter by status (proposed, pending_approval, approved, rejected, auto_executed)"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """
    List all strategy proposals with optional status filter.
    """
    pool = _get_db_pool(request)
    if status:
        query = """
            SELECT * FROM strategy_proposals
            WHERE status = $1
            ORDER BY created_at DESC
            LIMIT $2
        """
        params: List[Any] = [status, limit]
    else:
        query = """
            SELECT * FROM strategy_proposals
            ORDER BY created_at DESC
            LIMIT $1
        """
        params = [limit]

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    return {
        "proposals": [_serialize_proposal(r) for r in rows],
        "total": len(rows),
    }
