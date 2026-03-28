"""
SOVEREIGN SWARM — Sovereign Immunity API
REST endpoints for quarantine management, anomaly detection, and ethical audit.

Phase 3D — Code Guidelines Section XI.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.services.api_server import require_admin

router = APIRouter(
    prefix="/api/immunity",
    tags=["Sovereign Immunity"],
    dependencies=[Depends(require_admin)],
)


@router.get("/status")
async def sovereign_immunity_status():
    """Lightweight health-check for architecture diagrams."""
    return {"status": "active", "service": "sovereign_immunity"}


# =============================================================================
# REQUEST MODELS
# =============================================================================


class QuarantineRequest(BaseModel):
    """Body for quarantining a fibre."""

    reason: str = Field(..., min_length=1)
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    triggered_by: str = Field(default="api", max_length=64)


class ReleaseQuarantineRequest(BaseModel):
    """Body for releasing a fibre from quarantine."""

    resolution: str = Field(default="", description="Resolution notes from investigation")


# =============================================================================
# HELPERS
# =============================================================================


def _get_immunity(request: Request):
    """Get SovereignImmunityService from app state."""
    svc = getattr(request.app.state, "sovereign_immunity", None)
    if not svc:
        raise HTTPException(status_code=503, detail="Sovereign Immunity not available")
    return svc


def _get_fibre_manager(request: Request):
    """Get FibreManager from app state."""
    mgr = getattr(request.app.state, "fibre_manager", None)
    if not mgr:
        raise HTTPException(status_code=503, detail="Sovereign Swarm not enabled")
    return mgr


def _serialize_row(row: Any) -> Dict:
    """Convert asyncpg row to JSON-serializable dict."""
    result = {}
    for k, v in (row.items() if hasattr(row, "items") else row._mapping.items()):
        if isinstance(v, UUID):
            result[k] = str(v)
        elif hasattr(v, "isoformat"):
            result[k] = v.isoformat() if v else None
        else:
            result[k] = v
    return result


# =============================================================================
# QUARANTINE ENDPOINTS
# =============================================================================


@router.get("/quarantine")
async def list_quarantined_fibres(request: Request):
    """
    List all fibres currently in quarantine.
    Queries quarantine_log where resolved = FALSE.
    """
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT ql.*, f.name as fibre_name, f.fibre_type
            FROM quarantine_log ql
            LEFT JOIN fibres f ON f.fibre_id = ql.fibre_id
            WHERE ql.resolved = FALSE
            ORDER BY ql.created_at DESC
        """)

    return {
        "quarantined": [_serialize_row(r) for r in rows],
        "total": len(rows),
    }


@router.post("/quarantine/{fibre_id}")
async def quarantine_fibre(request: Request, fibre_id: UUID, body: QuarantineRequest):
    """
    Quarantine a fibre: isolate from Mesh, preserve journal, log forensics.
    """
    immunity = _get_immunity(request)

    try:
        result = await immunity.quarantine(
            fibre_id=fibre_id,
            reason=body.reason,
            severity=body.severity,
            triggered_by=body.triggered_by,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quarantine/{fibre_id}/release")
async def release_quarantine(request: Request, fibre_id: UUID, body: ReleaseQuarantineRequest):
    """
    Release a fibre from quarantine after investigation.
    """
    immunity = _get_immunity(request)

    released = await immunity.release_quarantine(fibre_id, resolution=body.resolution)
    if not released:
        raise HTTPException(
            status_code=404,
            detail="Fibre not found in quarantine or already released",
        )
    return {"status": "released", "fibre_id": str(fibre_id)}


# =============================================================================
# THREATS (ANOMALY DETECTION)
# =============================================================================


@router.get("/threats")
async def get_threats_summary(request: Request):
    """
    Get anomaly summary for all active fibres.
    Iterates fibre_manager._active_fibres and runs detect_anomaly per fibre.
    """
    immunity = _get_immunity(request)
    fibre_manager = _get_fibre_manager(request)

    summaries = []
    active_fibres = getattr(fibre_manager, "_active_fibres", {}) or {}

    for fid, fibre in active_fibres.items():
        try:
            anomaly = immunity.detect_anomaly(fid)
            anomaly["name"] = getattr(fibre, "name", None) or str(fid)
            anomaly["is_quarantined"] = immunity.is_quarantined(fid)
            summaries.append(anomaly)
        except Exception as e:
            summaries.append({
                "fibre_id": str(fid),
                "anomaly_score": 0.0,
                "is_anomalous": False,
                "error": str(e),
            })

    return {
        "threats": summaries,
        "total_active": len(active_fibres),
        "anomalous_count": sum(1 for s in summaries if s.get("is_anomalous")),
    }


# =============================================================================
# ETHICAL AUDIT LOG
# =============================================================================


@router.get("/audit-log")
async def get_audit_log(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
):
    """
    Get ethical audit history from ethical_audit_log.
    """
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT eal.*, f.name as fibre_name, f.fibre_type
            FROM ethical_audit_log eal
            LEFT JOIN fibres f ON f.fibre_id = eal.fibre_id
            ORDER BY eal.created_at DESC
            LIMIT $1
        """, limit)

    return {
        "entries": [_serialize_row(r) for r in rows],
        "limit": limit,
    }
