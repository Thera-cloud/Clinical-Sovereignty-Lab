"""
Nightly Audit API — Admin endpoints for audit status, rerun, override, and history.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from typing import Optional, List
import logging

from app.services.api_server import require_admin

logger = logging.getLogger("nightly_audit_api")

router = APIRouter(prefix="/api/admin/nightly-audit", tags=["nightly-audit"])


class GateOverrideBody(BaseModel):
    value: str = "CLEARED"
    reason: str = ""


@router.get("/status")
async def get_audit_status(request: Request, _admin=Depends(require_admin)):
    runner = getattr(request.app.state, "nightly_audit_runner", None)
    if not runner:
        return {"status": "not_configured", "gate": "UNKNOWN"}
    gate = await runner.get_gate_status()
    last = runner.get_last_result()
    return {
        "status": "ok",
        "gate": gate,
        "last_result": {
            "overall": last.get("overall") if last else None,
            "run_date": last.get("run_date") if last else None,
            "tests": last.get("tests", 0) if last else 0,
            "passed": last.get("passed", 0) if last else 0,
            "failed": last.get("failed", 0) if last else 0,
        } if last else None,
        "health": runner.health(),
    }


@router.post("/rerun")
async def rerun_audit(request: Request, phases: Optional[str] = Query(None),
                      _admin=Depends(require_admin)):
    runner = getattr(request.app.state, "nightly_audit_runner", None)
    if not runner:
        raise HTTPException(400, "Nightly audit runner not configured")

    phase_list = None
    if phases:
        try:
            phase_list = [int(p.strip()) for p in phases.split(",")]
        except ValueError:
            raise HTTPException(422, "phases must be comma-separated integers (1-5)")

    result = await runner.run_full_audit(phases=phase_list)
    return {"status": "ok", "result": result}


@router.post("/override-gate")
async def override_gate(body: GateOverrideBody, request: Request,
                        _admin=Depends(require_admin)):
    runner = getattr(request.app.state, "nightly_audit_runner", None)
    if not runner:
        raise HTTPException(400, "Nightly audit runner not configured")

    if body.value not in ("CLEARED", "BLOCKED"):
        raise HTTPException(422, "value must be CLEARED or BLOCKED")

    await runner.override_gate(body.value)
    logger.info("Platform gate manually set to %s by admin (reason: %s)", body.value, body.reason)
    return {"status": "ok", "gate": body.value, "reason": body.reason}


@router.get("/history")
async def get_audit_history(request: Request, days: int = Query(7, ge=1, le=90),
                            _admin=Depends(require_admin)):
    runner = getattr(request.app.state, "nightly_audit_runner", None)
    if not runner:
        return {"history": []}

    history = await runner.get_history(days=days)
    return {"status": "ok", "days": days, "count": len(history), "history": history}


@router.get("/health")
async def nightly_audit_health(request: Request):
    runner = getattr(request.app.state, "nightly_audit_runner", None)
    if not runner:
        return {"status": "ok", "configured": False}
    return {"status": "ok", **runner.health()}
