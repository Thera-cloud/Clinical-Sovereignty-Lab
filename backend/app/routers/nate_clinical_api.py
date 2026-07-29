"""QUANTUM-CRYSTAL-ARCH — Nate clinical coevolution admin API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("nate_clinical_api")

router = APIRouter(prefix="/api/nate-clinical", tags=["nate-clinical"])

try:
    from app.services.api_server import require_admin
except Exception:
    async def require_admin():  # type: ignore
        return {"role": "ADMIN"}


def _pool(request: Request):
    return getattr(request.app.state, "db_pool", None)


def _agent(request: Request):
    return getattr(request.app.state, "nate_clinical_bakeoff_agent", None)


@router.get("/health")
async def health(request: Request, _admin=Depends(require_admin)):
    from app.services.nate_clinical_flags import flag_snapshot, min_preference_yield

    stats = {}
    pool = _pool(request)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT matches_attempted, matches_complete, preferences_written,
                           both_failed_gate, one_failed_gate, tie_or_discordant
                    FROM nate_clinical_bakeoff_nightly_stats
                    ORDER BY night_bucket DESC LIMIT 1
                    """
                )
                if row:
                    stats = dict(row)
                    att = int(stats.get("matches_attempted") or 0)
                    pref = int(stats.get("preferences_written") or 0)
                    stats["preference_yield_rate"] = (pref / att) if att else 0.0
        except Exception as e:
            stats = {"error": str(e)}
    return {
        "status": "ok",
        "flags": flag_snapshot(),
        "min_preference_yield": min_preference_yield(),
        "latest_nightly": stats or {"matches_attempted": 0, "preferences_written": 0},
        "agent": _agent(request) is not None,
    }


@router.post("/bakeoff/run")
async def bakeoff_run(
    request: Request,
    max_matches: int = 3,
    _admin=Depends(require_admin),
):
    agent = _agent(request)
    if agent is None:
        raise HTTPException(503, "bakeoff agent not initialized")
    from app.services.nate_clinical_flags import bakeoff_enabled

    if not bakeoff_enabled():
        raise HTTPException(400, "ENABLE_NATE_CLINICAL_BAKEOFF is false")
    result = await agent.run_night(max_matches=max(1, min(max_matches, 20)))
    return result


@router.get("/leaderboard")
async def leaderboard(request: Request, _admin=Depends(require_admin)):
    pool = _pool(request)
    if pool is None:
        return {"status": "ok", "rows": []}
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT winner, COUNT(*) AS wins
                FROM nate_clinical_bakeoff_matches
                WHERE status = 'complete' AND winner IN ('a', 'b')
                GROUP BY winner
                ORDER BY wins DESC
                """
            )
            night = await conn.fetchrow(
                """
                SELECT matches_attempted, preferences_written, matches_complete
                FROM nate_clinical_bakeoff_nightly_stats
                ORDER BY night_bucket DESC LIMIT 1
                """
            )
        return {
            "status": "ok",
            "wins_by_side": [dict(r) for r in rows],
            "yield_block": dict(night) if night else {},
        }
    except Exception as e:
        return {"status": "ok", "rows": [], "error": str(e)}


@router.post("/export/dpo")
async def export_dpo(request: Request, _admin=Depends(require_admin)):
    from app.services.nate_clinical_dpo_export import export_preferences_jsonl

    return await export_preferences_jsonl(_pool(request))


class RevisionBody(BaseModel):
    revision_id: str
    checkpoint_ref: str
    provider: str = Field(..., pattern="^(sovereign|home_gpu)$")
    activate: bool = False
    ceo_decision_id: Optional[str] = None


@router.post("/revisions")
async def create_revision(
    body: RevisionBody,
    request: Request,
    _admin=Depends(require_admin),
):
    from app.services.nate_clinical_dpo_export import register_revision

    return await register_revision(
        _pool(request),
        revision_id=body.revision_id,
        checkpoint_ref=body.checkpoint_ref,
        provider=body.provider,
        activate=body.activate,
        ceo_decision_id=body.ceo_decision_id,
    )


@router.post("/revisions/{revision_id}/activate")
async def activate_revision(
    revision_id: str,
    request: Request,
    _admin=Depends(require_admin),
):
    from app.services.nate_clinical_dpo_export import rollback_revision

    return await rollback_revision(_pool(request), revision_id)
