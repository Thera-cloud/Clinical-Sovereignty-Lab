"""
Trust Enforcer API — Baseline governance and enforcement endpoints.
Admin-only endpoints for viewing trust status, managing baseline proposals,
and triggering enforcement cycles.
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.services.api_server import require_admin

logger = logging.getLogger("nate.trust_enforcer_api")

router = APIRouter(
    prefix="/api/trust-enforcer",
    tags=["trust-enforcer"],
    dependencies=[Depends(require_admin)],
)


class ProposalRequest(BaseModel):
    parameter_key: str
    proposed_value: dict
    reason: str
    proposed_by: str = "system"


class ApprovalRequest(BaseModel):
    reviewed_by: str = "DrNevedal1"


def _get_pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(500, "Database pool unavailable")
    return pool


@router.get("/status")
async def get_trust_status(request: Request):
    """Current aggregate trust score across all auditors."""
    pool = _get_pool(request)
    import re
    score_re = re.compile(r"(\d+)/(\d+)\s+TRUSTED")
    activity_types = [
        "skyeye_tab_audit_sent", "command_tab_audit_sent",
        "eye_tab_audit_sent", "login_audit_sent",
        "client_app_audit_sent", "coach_dojo_audit_sent",
        "billing_audit_sent", "defense_audit_sent",
        "ai_pipeline_audit_sent", "ws_flow_audit_sent",
        "tier_gating_audit_sent", "nevedal_lab_audit_sent",
        "hardware_security_audit_sent", "system_integrity_audit_sent",
    ]
    auditors = {}
    total_trusted, total_tests = 0, 0
    async with pool.acquire() as conn:
        for atype in activity_types:
            row = await conn.fetchrow(
                "SELECT content, created_at FROM skyeye_activity "
                "WHERE type = $1 ORDER BY created_at DESC LIMIT 1", atype
            )
            if row:
                m = score_re.search(row["content"])
                if m:
                    t, tot = int(m.group(1)), int(m.group(2))
                    total_trusted += t
                    total_tests += tot
                    auditors[atype] = {"trusted": t, "total": tot,
                                       "pct": int(t / tot * 100) if tot else 0,
                                       "timestamp": row["created_at"].isoformat()}
                else:
                    auditors[atype] = None
            else:
                auditors[atype] = None

    pct = int((total_trusted / total_tests * 100) if total_tests else 0)
    return {
        "overall_pct": pct,
        "total_trusted": total_trusted,
        "total_tests": total_tests,
        "level": "GREEN" if pct == 100 else ("RED" if pct < 80 else "YELLOW"),
        "auditors": auditors,
    }


@router.get("/baseline")
async def get_baseline(request: Request):
    """View current trust baseline parameters."""
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT parameter_key, parameter_value, description, "
            "approved_by, approved_at FROM trust_baseline ORDER BY parameter_key"
        )
    return {"baseline": [
        {
            "key": r["parameter_key"],
            "value": r["parameter_value"],
            "description": r["description"],
            "approved_by": r["approved_by"],
            "approved_at": r["approved_at"].isoformat() if r["approved_at"] else None,
        }
        for r in rows
    ]}


@router.post("/propose-change")
async def propose_change(req: ProposalRequest, request: Request):
    """Submit a baseline parameter change proposal."""
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        current = await conn.fetchrow(
            "SELECT parameter_value FROM trust_baseline WHERE parameter_key = $1",
            req.parameter_key
        )
        current_val = current["parameter_value"] if current else None

        row = await conn.fetchrow("""
            INSERT INTO trust_baseline_proposals
            (parameter_key, current_value, proposed_value, reason, proposed_by)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, created_at
        """, req.parameter_key,
             json.dumps(current_val) if current_val else None,
             json.dumps(req.proposed_value),
             req.reason, req.proposed_by)

    logger.info("Trust baseline proposal #%d submitted for %s by %s",
                row["id"], req.parameter_key, req.proposed_by)
    return {"proposal_id": row["id"], "status": "PENDING",
            "created_at": row["created_at"].isoformat()}


@router.get("/proposals")
async def list_proposals(request: Request, status: str = "PENDING"):
    """List baseline change proposals."""
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, parameter_key, current_value, proposed_value, "
            "reason, proposed_by, status, reviewed_by, reviewed_at, created_at "
            "FROM trust_baseline_proposals WHERE status = $1 "
            "ORDER BY created_at DESC LIMIT 50", status
        )
    return {"proposals": [dict(r) for r in rows]}


@router.post("/approve/{proposal_id}")
async def approve_proposal(proposal_id: int, req: ApprovalRequest, request: Request):
    """Approve a baseline change proposal (admin-only)."""
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        proposal = await conn.fetchrow(
            "SELECT * FROM trust_baseline_proposals WHERE id = $1", proposal_id
        )
        if not proposal:
            raise HTTPException(404, "Proposal not found")
        if proposal["status"] != "PENDING":
            raise HTTPException(400, f"Proposal is already {proposal['status']}")

        now = datetime.now(timezone.utc)
        await conn.execute(
            "UPDATE trust_baseline_proposals SET status = 'APPROVED', "
            "reviewed_by = $1, reviewed_at = $2 WHERE id = $3",
            req.reviewed_by, now, proposal_id
        )

        proposed = (
            json.loads(proposal["proposed_value"])
            if isinstance(proposal["proposed_value"], str)
            else proposal["proposed_value"]
        )
        await conn.execute("""
            INSERT INTO trust_baseline (parameter_key, parameter_value, approved_by, approved_at, updated_at)
            VALUES ($1, $2, $3, $4, $4)
            ON CONFLICT (parameter_key) DO UPDATE
            SET parameter_value = $2, approved_by = $3, approved_at = $4, updated_at = $4
        """, proposal["parameter_key"], json.dumps(proposed), req.reviewed_by, now)

    logger.info("Trust baseline proposal #%d APPROVED by %s", proposal_id, req.reviewed_by)
    return {"proposal_id": proposal_id, "status": "APPROVED",
            "reviewed_by": req.reviewed_by}


@router.post("/reject/{proposal_id}")
async def reject_proposal(proposal_id: int, req: ApprovalRequest, request: Request):
    """Reject a baseline change proposal (admin-only)."""
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        proposal = await conn.fetchrow(
            "SELECT status FROM trust_baseline_proposals WHERE id = $1", proposal_id
        )
        if not proposal:
            raise HTTPException(404, "Proposal not found")
        if proposal["status"] != "PENDING":
            raise HTTPException(400, f"Proposal is already {proposal['status']}")

        now = datetime.now(timezone.utc)
        await conn.execute(
            "UPDATE trust_baseline_proposals SET status = 'REJECTED', "
            "reviewed_by = $1, reviewed_at = $2 WHERE id = $3",
            req.reviewed_by, now, proposal_id
        )

    logger.info("Trust baseline proposal #%d REJECTED by %s", proposal_id, req.reviewed_by)
    return {"proposal_id": proposal_id, "status": "REJECTED"}


@router.post("/trigger")
async def trigger_enforcement(request: Request):
    """Manually trigger an enforcement cycle (admin-only)."""
    enforcer = getattr(request.app.state, "trust_enforcer", None)
    if not enforcer:
        raise HTTPException(503, "Trust Enforcer not initialized")
    await enforcer.trigger()
    return {"status": "triggered", "timestamp": datetime.now(timezone.utc).isoformat()}
