"""
SOVEREIGN SWARM — Fibre & Mesh API
REST endpoints for querying active Fibres, spawning new ones,
and checking Wisdom Mesh health.

Phase 3C — UI Integration Layer.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["fibres", "mesh"])


# ─── Request Models ──────────────────────────────────────────────────────────

class SpawnRequest(BaseModel):
    fibre_type: str
    name: str
    domain_tags: List[str] = []
    reason: str = ""


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_fibre_manager(request: Request):
    """Get FibreManager from app state."""
    mgr = getattr(request.app.state, "fibre_manager", None)
    if not mgr:
        raise HTTPException(status_code=503, detail="Sovereign Swarm not enabled")
    return mgr


def _get_wisdom_mesh(request: Request):
    """Get WisdomMeshService from app state."""
    mesh = getattr(request.app.state, "wisdom_mesh", None)
    if not mesh:
        raise HTTPException(status_code=503, detail="Wisdom Mesh not available")
    return mesh


# ─── Fibre Endpoints ─────────────────────────────────────────────────────────

@router.get("/fibres")
async def list_fibres(request: Request):
    """List all active Fibres with status."""
    mgr = _get_fibre_manager(request)
    fibres = await mgr.inventory()
    return {
        "fibres": fibres,
        "total": len(fibres),
    }


@router.get("/fibres/{fibre_id}")
async def get_fibre_detail(request: Request, fibre_id: str):
    """Get detailed info about a specific Fibre."""
    mgr = _get_fibre_manager(request)

    try:
        uid = UUID(fibre_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid fibre_id format")

    fibre = mgr.get_fibre(uid)
    if not fibre:
        raise HTTPException(status_code=404, detail="Fibre not found")

    # Build detailed response
    detail = {
        "fibre_id": str(uid),
        "name": fibre.name,
        "type": fibre.fibre_type.value,
        "status": fibre.status.value,
        "autonomy": fibre.autonomy_level.value,
        "alignment_scores": fibre.alignment_scores,
        "tokens_used": fibre._tokens_used_this_hour,
        "tasks_completed": fibre._completed_tasks,
        "config": {
            "domain_tags": fibre.config.domain_tags if fibre.config else [],
            "token_budget_per_hour": fibre.config.token_budget_per_hour if fibre.config else 0,
        },
    }

    # Include recent journal entries if available
    try:
        if hasattr(fibre, "journal") and fibre.journal:
            detail["journal_entries"] = fibre.journal[-10:]
    except Exception:
        pass

    return detail


@router.post("/fibres/spawn")
async def spawn_fibre(request: Request, body: SpawnRequest):
    """Spawn a new Fibre."""
    mgr = _get_fibre_manager(request)

    from app.models.fibre import FibreConfig, FibreType

    try:
        fibre_type = FibreType(body.fibre_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown fibre_type: {body.fibre_type}. "
                   f"Available: {[t.value for t in FibreType]}"
        )

    config = FibreConfig(
        fibre_type=fibre_type,
        name=body.name,
        domain_tags=body.domain_tags,
    )

    try:
        fibre = await mgr.spawn(config, spawn_reason=body.reason)
        return {
            "status": "spawned",
            "fibre_id": str(fibre.fibre_id) if hasattr(fibre, "fibre_id") else None,
            "name": fibre.name,
            "type": fibre.fibre_type.value,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Mesh Health Endpoint ────────────────────────────────────────────────────

@router.get("/mesh/health")
async def get_mesh_health(request: Request):
    """Get Wisdom Mesh health metrics."""
    mesh = _get_wisdom_mesh(request)

    try:
        health = await mesh.get_mesh_health()
        return {
            "total_messages": health.total_messages_24h,
            "messages_per_minute": health.messages_per_minute,
            "average_latency_ms": health.average_latency_ms,
            "delivery_success_rate": health.delivery_success_rate,
            "active_topics": health.active_subscriptions,
            "subscribers": health.active_subscriptions,
            "convergence_alerts": health.convergence_alerts_24h,
            "bandwidth_utilization": health.bandwidth_utilization,
            "pending_messages": health.pending_messages,
        }
    except Exception as e:
        return {
            "status": "degraded",
            "error": str(e),
            "total_messages": 0,
            "active_topics": 0,
            "subscribers": 0,
            "convergence_alerts": 0,
        }
