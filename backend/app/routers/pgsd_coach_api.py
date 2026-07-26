"""
Coach-facing PGSD REST (ACCESS/FIELD + Tier 2 pack).  # QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from app.services.api_server import require_coach

logger = logging.getLogger("sovereign.pgsd_coach_api")

router = APIRouter(
    prefix="/api/coach/pgsd",
    tags=["coach-pgsd"],
    dependencies=[Depends(require_coach)],
)


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _pool(request: Request):
    return getattr(request.app.state, "db_pool", None)


@router.get("/flags")
async def pgsd_flags(request: Request):
    return {
        "status": "ok",
        "PGSD_ENABLED": _env_true("PGSD_ENABLED"),
        "ENABLE_PGSD_ACCESS": _env_true("ENABLE_PGSD_ACCESS"),
        "ENABLE_PGSD_FIELD": _env_true("ENABLE_PGSD_FIELD"),
        "ENABLE_PGSD_HEARTBEAT": _env_true("ENABLE_PGSD_HEARTBEAT"),
        "ENABLE_PGSD_HELIX_HINT": _env_true("ENABLE_PGSD_HELIX_HINT"),
        "TIER2_REQUIRE_SURFACE_HITS": os.environ.get(
            "TIER2_REQUIRE_SURFACE_HITS", "true"
        ).strip().lower()
        not in ("0", "false", "no", "off"),
    }


@router.get("/client/{client_id}")
async def pgsd_client_view(client_id: str, request: Request):
    """Snapshot + discernment + briefing + optional FIELD wells/ground."""
    pool = _pool(request)
    if pool is None:
        raise HTTPException(503, "database unavailable")
    if not _env_true("PGSD_ENABLED"):
        return {"status": "disabled", "client_id": client_id, "data": {}}

    from app.services.pgsd_briefing import build_field_briefing
    from app.services.pgsd_engine import PGSDEngine

    eng = PGSDEngine(db_pool=pool)
    resolved = await eng.resolve_pgsd_subject(client_id)
    if not resolved:
        raise HTTPException(404, "client not found")
    hw = resolved["hardware_id"]
    briefing = await build_field_briefing(pool, hw)

    out: Dict[str, Any] = {
        "status": "ok",
        "hardware_id": hw,
        "username": resolved.get("username"),
        "briefing": briefing,
        "access": _env_true("ENABLE_PGSD_ACCESS"),
        "field": _env_true("ENABLE_PGSD_FIELD"),
        "snapshot": None,
        "discernment": None,
        "cross_domain": None,
        "trauma_wells": [],
        "ground_state": None,
    }
    try:
        async with pool.acquire() as conn:
            snap = await conn.fetchrow(
                """
                SELECT coherence, d4_temporal_depth, session_region, trigger_source, computed_at
                FROM pgsd_snapshots WHERE user_id = $1
                ORDER BY computed_at DESC LIMIT 1
                """,
                hw,
            )
            if snap:
                out["snapshot"] = {
                    "coherence": float(snap["coherence"] or 0),
                    "d4_temporal_depth": float(snap["d4_temporal_depth"] or 0),
                    "session_region": snap["session_region"],
                    "trigger_source": snap["trigger_source"],
                    "computed_at": snap["computed_at"].isoformat()
                    if snap["computed_at"]
                    else None,
                }
            if _env_true("ENABLE_PGSD_ACCESS"):
                disc = await conn.fetchrow(
                    """
                    SELECT score_composite, score_past, score_present, score_future, computed_at
                    FROM pgsd_discernment_scores WHERE user_id = $1
                    ORDER BY computed_at DESC LIMIT 1
                    """,
                    hw,
                )
                if disc:
                    out["discernment"] = {
                        "composite": float(disc["score_composite"] or 0),
                        "past": float(disc["score_past"] or 0),
                        "present": float(disc["score_present"] or 0),
                        "future": float(disc["score_future"] or 0),
                        "computed_at": disc["computed_at"].isoformat()
                        if disc["computed_at"]
                        else None,
                    }
                agr = await conn.fetchrow(
                    """
                    SELECT agreement_score, surfaces, computed_at
                    FROM pgsd_cross_domain_agreement WHERE user_id = $1
                    ORDER BY computed_at DESC LIMIT 1
                    """,
                    hw,
                )
                if agr:
                    out["cross_domain"] = {
                        "agreement_score": float(agr["agreement_score"] or 0),
                        "surfaces": agr["surfaces"],
                        "computed_at": agr["computed_at"].isoformat()
                        if agr["computed_at"]
                        else None,
                    }
            if _env_true("ENABLE_PGSD_FIELD"):
                wells = await conn.fetch(
                    """
                    SELECT temporal_class, depth, collapsed, updated_at
                    FROM pgsd_trauma_wells WHERE user_id = $1
                    ORDER BY updated_at DESC LIMIT 12
                    """,
                    hw,
                )
                out["trauma_wells"] = [
                    {
                        "temporal_class": w["temporal_class"],
                        "depth": float(w["depth"] or 0) if w["depth"] is not None else None,
                        "collapsed": w["collapsed"],
                        "updated_at": w["updated_at"].isoformat()
                        if w["updated_at"]
                        else None,
                    }
                    for w in wells
                ]
                ground = await conn.fetchrow(
                    """
                    SELECT ground_energy, relocation, computed_at
                    FROM pgsd_ground_states WHERE user_id = $1
                    ORDER BY computed_at DESC LIMIT 1
                    """,
                    hw,
                )
                if ground:
                    out["ground_state"] = {
                        "ground_energy": float(ground["ground_energy"] or 0),
                        "relocation": float(ground["relocation"] or 0),
                        "computed_at": ground["computed_at"].isoformat()
                        if ground["computed_at"]
                        else None,
                    }
    except Exception as e:
        logger.warning("pgsd_client_view: %s", e)
        raise HTTPException(500, "pgsd query failed") from e
    return out


@router.get("/tier2/latest")
async def tier2_latest_pack(request: Request):
    pool = _pool(request)
    if pool is None:
        raise HTTPException(503, "database unavailable")
    from app.services.tier2_cross_domain_battery import latest_pack_summary

    return {"status": "ok", **await latest_pack_summary(pool)}
