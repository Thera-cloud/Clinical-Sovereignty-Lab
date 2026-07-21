"""
Six-Quotient Battery Admin API — runs list, scores intake, gap analyze, trigger.

All endpoints require admin. Scores without evaluator_id are rejected.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.services.api_server import require_admin

logger = logging.getLogger("nate.six_quotient_api")

router = APIRouter(
    prefix="/api/admin/six-quotient",
    tags=["six-quotient-battery"],
    dependencies=[Depends(require_admin)],
)


def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(500, "Database pool unavailable")
    return pool


def _enabled() -> bool:
    return os.getenv("ENABLE_SIX_QUOTIENT_BATTERY", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


# AI judge ids must pass /judge/calibrate; human clinician ids are exempt.
_AI_EVAL_MARKERS = (
    "gpt", "claude", "gemini", "grok", "judge", "llm", "model",
    "openai", "anthropic", "azure",
)


def _is_ai_evaluator(evaluator_id: str) -> bool:
    low = (evaluator_id or "").lower()
    return any(m in low for m in _AI_EVAL_MARKERS)


class ScoreItem(BaseModel):
    scenario_id: str
    section: str = ""
    primary: int = Field(..., ge=0, le=3)
    accuracy: int = Field(..., ge=0, le=3)
    naturalness: int = Field(..., ge=0, le=3)
    notes: str = ""

    @field_validator("scenario_id")
    @classmethod
    def _sid(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("scenario_id required")
        return v


class ScoresIntake(BaseModel):
    run_id: str
    evaluator_id: str
    scores: List[ScoreItem]
    analyze: bool = True

    @field_validator("evaluator_id")
    @classmethod
    def _eval(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("evaluator_id required — external scorer only")
        if v.lower() in ("self", "cli", "little_nate", "nate", "auto", "system"):
            raise ValueError("evaluator_id must be an external human or designated model id")
        return v


class TriggerRequest(BaseModel):
    dry_run: bool = True
    limit: int = 0
    environment: str = "staging"
    persist: bool = True
    multi_turn: bool = True


class ApproveScenarioBody(BaseModel):
    scenario_key: str
    approved_by: str = "admin"


class GenerateBody(BaseModel):
    sections: List[str] = Field(default_factory=lambda: ["AQ", "SQ", "CQ"])
    n_per_section: int = 1
    boundary: bool = True
    environment: str = "staging"


class StandardsApproveBody(BaseModel):
    item_id: str
    approved_by: str = "admin"
    crystallize: bool = True


class StandardsRejectBody(BaseModel):
    item_id: str
    rejected_by: str = "admin"


class JudgeCalibrateBody(BaseModel):
    evaluator_id: str
    ratings: List[Dict[str, Any]]

    @field_validator("evaluator_id")
    @classmethod
    def _eval(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("evaluator_id required")
        return v


@router.get("/health")
async def health(request: Request):
    """Battery subsystem health — always structurally non-empty."""
    pool = _pool(request)
    enabled = _enabled()
    living = os.getenv("ENABLE_SIX_QUOTIENT_LIVING_BATTERY", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )
    last_run = None
    bank_approved = 0
    standards_pending = 0
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id::text, status, battery_version, environment,
                          started_at, scored_at
                   FROM six_quotient_runs
                   ORDER BY started_at DESC LIMIT 1"""
            )
            if row:
                last_run = dict(row)
                if last_run.get("started_at"):
                    last_run["started_at"] = last_run["started_at"].isoformat()
                if last_run.get("scored_at"):
                    last_run["scored_at"] = last_run["scored_at"].isoformat()
            try:
                bank_approved = int(
                    await conn.fetchval(
                        "SELECT COUNT(*) FROM six_quotient_scenario_bank WHERE status = 'approved'"
                    )
                    or 0
                )
                standards_pending = int(
                    await conn.fetchval(
                        "SELECT COUNT(*) FROM six_quotient_standards_items WHERE status = 'pending_review'"
                    )
                    or 0
                )
            except Exception:
                pass
    except Exception as e:
        logger.warning("six_quotient health query: %s", e)
        return {
            "status": "degraded",
            "enabled": enabled,
            "living": living,
            "tables_ok": False,
            "error": str(e)[:200],
            "last_run": None,
            "bank_approved": 0,
            "standards_pending": 0,
        }
    return {
        "status": "ok",
        "enabled": enabled,
        "living": living,
        "tables_ok": True,
        "last_run": last_run or {"status": "none"},
        "bank_approved": bank_approved,
        "standards_pending": standards_pending,
    }


@router.get("/runs")
async def list_runs(request: Request, limit: int = 20):
    pool = _pool(request)
    limit = max(1, min(int(limit or 20), 100))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id::text, battery_version, environment, git_hash, status,
                      started_at, finished_at, scored_at,
                      gap_summary
               FROM six_quotient_runs
               ORDER BY started_at DESC
               LIMIT $1""",
            limit,
        )
    out = []
    for r in rows:
        d = dict(r)
        for k in ("started_at", "finished_at", "scored_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        if isinstance(d.get("gap_summary"), str):
            try:
                d["gap_summary"] = json.loads(d["gap_summary"])
            except Exception:
                pass
        out.append(d)
    return {"status": "ok", "runs": out, "count": len(out)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id::text, battery_version, environment, git_hash, status,
                      results_json, gap_summary, started_at, finished_at,
                      scored_at, error_message
               FROM six_quotient_runs WHERE id = $1::uuid""",
            run_id,
        )
        if not row:
            raise HTTPException(404, "run not found")
        scores = await conn.fetch(
            """SELECT scenario_id, section, primary_score, accuracy_score,
                      naturalness_score, evaluator_id, notes, created_at
               FROM six_quotient_scores WHERE run_id = $1::uuid
               ORDER BY scenario_id""",
            run_id,
        )
    d = dict(row)
    for k in ("started_at", "finished_at", "scored_at"):
        if d.get(k):
            d[k] = d[k].isoformat()
    for key in ("results_json", "gap_summary"):
        if isinstance(d.get(key), str):
            try:
                d[key] = json.loads(d[key])
            except Exception:
                pass
    score_list = []
    for s in scores:
        sd = dict(s)
        if sd.get("created_at"):
            sd["created_at"] = sd["created_at"].isoformat()
        score_list.append(sd)
    return {"status": "ok", "run": d, "scores": score_list}


@router.post("/scores")
async def submit_scores(body: ScoresIntake, request: Request):
    """External score intake. Rejects missing/self evaluator_id."""
    pool = _pool(request)
    if not body.scores:
        raise HTTPException(400, "scores required")

    # QUANTUM-CRYSTAL-ARCH — shared intake (REST + auto-judge)
    from app.services.six_quotient_score_intake import upsert_scores

    up = await upsert_scores(
        pool,
        run_id=body.run_id,
        evaluator_id=body.evaluator_id,
        scores=[s.model_dump() for s in body.scores],
        require_calibration=True,
    )
    if not up.get("ok"):
        err = up.get("error") or "score_intake_failed"
        if "not found" in err:
            raise HTTPException(404, err)
        if "calibrat" in err:
            raise HTTPException(403, err)
        raise HTTPException(400, err)
    inserted = int(up.get("scores_upserted") or 0)

    analysis: Dict[str, Any] = {"skipped": True}
    if body.analyze:
        from app.services.six_quotient_gap_analyzer import analyze_and_enqueue

        analysis = await analyze_and_enqueue(pool, body.run_id)
        # Feed growth engine when available
        growth = getattr(request.app.state, "six_quotient_growth_engine", None)
        if growth and analysis.get("ok") and hasattr(growth, "ingest_battery_findings"):
            try:
                await growth.ingest_battery_findings(body.run_id, analysis)
            except Exception as e:
                logger.warning("growth ingest: %s", e)

    return {
        "status": "ok",
        "run_id": body.run_id,
        "scores_upserted": inserted,
        "evaluator_id": body.evaluator_id,
        "analysis": analysis,
    }


@router.post("/analyze/{run_id}")
async def reanalyze(run_id: str, request: Request):
    pool = _pool(request)
    from app.services.six_quotient_gap_analyzer import analyze_and_enqueue

    result = await analyze_and_enqueue(pool, run_id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "analyze_failed"))
    growth = getattr(request.app.state, "six_quotient_growth_engine", None)
    if growth and hasattr(growth, "ingest_battery_findings"):
        try:
            await growth.ingest_battery_findings(run_id, result)
        except Exception as e:
            logger.warning("growth ingest: %s", e)
    return {"status": "ok", "analysis": result}


@router.get("/scorecard")
async def scorecard(request: Request, limit: int = 10):
    """Trend surface for scored runs."""
    pool = _pool(request)
    limit = max(1, min(int(limit or 10), 50))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id::text, battery_version, environment, git_hash,
                      started_at, scored_at, gap_summary
               FROM six_quotient_runs
               WHERE status = 'scored'
               ORDER BY scored_at DESC NULLS LAST
               LIMIT $1""",
            limit,
        )
    history = []
    for r in rows:
        gap = r["gap_summary"] or {}
        if isinstance(gap, str):
            try:
                gap = json.loads(gap)
            except Exception:
                gap = {}
        history.append({
            "run_id": r["id"],
            "battery_version": r["battery_version"],
            "environment": r["environment"],
            "git_hash": r["git_hash"],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "scored_at": r["scored_at"].isoformat() if r["scored_at"] else None,
            "composite": gap.get("composite"),
            "quotients": gap.get("quotients"),
        })
    return {"status": "ok", "history": history, "count": len(history)}


@router.post("/trigger")
async def trigger_battery(body: TriggerRequest, request: Request):
    """Queue an in-process dry-run battery (safe default). Live WS is opt-in via agent."""
    if not _enabled() and not body.dry_run:
        raise HTTPException(403, "ENABLE_SIX_QUOTIENT_BATTERY is off; use dry_run=true")

    agent = getattr(request.app.state, "six_quotient_battery_agent", None)
    if not agent or not hasattr(agent, "run_once"):
        raise HTTPException(503, "six_quotient_battery_agent unavailable")
    result = await agent.run_once(
        dry_run=body.dry_run,
        limit=body.limit,
        environment=body.environment,
        persist=body.persist,
        multi_turn=body.multi_turn,
    )
    return {"status": "ok", "result": result}


@router.get("/bank")
async def list_scenario_bank(
    request: Request, status: str = "approved", section: str = "", limit: int = 100
):
    pool = _pool(request)
    from app.services.six_quotient_scenario_bank import list_bank

    rows = await list_bank(
        pool,
        status=status or None,
        section=section or None,
        limit=limit,
    )
    return {"status": "ok", "scenarios": rows, "count": len(rows)}


@router.post("/bank/seed")
async def seed_bank(request: Request):
    pool = _pool(request)
    from app.services.six_quotient_scenario_bank import seed_v4_anchors

    result = await seed_v4_anchors(pool)
    return {"status": "ok", "result": result}


@router.post("/bank/approve")
async def approve_bank_scenario(body: ApproveScenarioBody, request: Request):
    pool = _pool(request)
    from app.services.six_quotient_scenario_bank import approve_scenario

    result = await approve_scenario(pool, body.scenario_key, body.approved_by)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "approve_failed"))
    return {"status": "ok", **result}


@router.post("/generate")
async def generate_scenarios(body: GenerateBody, request: Request):
    if os.getenv("ENABLE_SIX_QUOTIENT_SCENARIO_GEN", "false").strip().lower() not in (
        "1", "true", "yes", "on",
    ):
        raise HTTPException(403, "ENABLE_SIX_QUOTIENT_SCENARIO_GEN is off")
    pool = _pool(request)
    from app.services.six_quotient_scenario_generator import generate_drafts

    result = await generate_drafts(
        pool,
        request.app.state,
        sections=body.sections,
        n_per_section=body.n_per_section,
        boundary=body.boundary,
        environment=body.environment,
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "generate_failed"))
    return {"status": "ok", "result": result}


@router.get("/standards")
async def list_standards(
    request: Request, status: str = "pending_review", quotient: str = "", limit: int = 50
):
    idx = getattr(request.app.state, "six_quotient_standards_index", None)
    if idx and hasattr(idx, "list_items"):
        rows = await idx.list_items(
            status=status, quotient=quotient or None, limit=limit
        )
        return {"status": "ok", "items": rows, "count": len(rows)}
    # Fallback direct query
    pool = _pool(request)
    async with pool.acquire() as conn:
        if quotient:
            rows = await conn.fetch(
                """SELECT id::text, quotient, title, url, published_year, status, source_name
                   FROM six_quotient_standards_items
                   WHERE status = $1 AND quotient = $2
                   ORDER BY fetched_at DESC LIMIT $3""",
                status,
                quotient.upper(),
                limit,
            )
        else:
            rows = await conn.fetch(
                """SELECT id::text, quotient, title, url, published_year, status, source_name
                   FROM six_quotient_standards_items
                   WHERE status = $1
                   ORDER BY fetched_at DESC LIMIT $2""",
                status,
                limit,
            )
    return {"status": "ok", "items": [dict(r) for r in rows], "count": len(rows)}


@router.post("/standards/sync")
async def sync_standards(request: Request):
    if os.getenv("ENABLE_SIX_QUOTIENT_STANDARDS_INDEX", "false").strip().lower() not in (
        "1", "true", "yes", "on",
    ):
        raise HTTPException(403, "ENABLE_SIX_QUOTIENT_STANDARDS_INDEX is off")
    idx = getattr(request.app.state, "six_quotient_standards_index", None)
    if not idx:
        raise HTTPException(503, "standards index unavailable")
    result = await idx.run_once()
    return {"status": "ok", "result": result}


@router.post("/standards/approve")
async def approve_standard(body: StandardsApproveBody, request: Request):
    idx = getattr(request.app.state, "six_quotient_standards_index", None)
    if not idx:
        raise HTTPException(503, "standards index unavailable")
    result = await idx.approve(
        body.item_id, body.approved_by, crystallize=body.crystallize
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "approve_failed"))
    return {"status": "ok", **result}


@router.post("/standards/reject")
async def reject_standard(body: StandardsRejectBody, request: Request):
    """Reject off-topic / junk pending_review standards items."""
    # QUANTUM-CRYSTAL-ARCH
    idx = getattr(request.app.state, "six_quotient_standards_index", None)
    if not idx or not hasattr(idx, "reject"):
        raise HTTPException(503, "standards index unavailable")
    result = await idx.reject(body.item_id, body.rejected_by)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "reject_failed"))
    return {"status": "ok", **result}


@router.get("/ability")
async def get_ability_state(request: Request, environment: str = "staging"):
    pool = _pool(request)
    from app.services.six_quotient_scenario_bank import get_ability

    return {"status": "ok", "ability": await get_ability(pool, environment)}


class SelfDevTriggerBody(BaseModel):
    environment: str = "production"
    persist_drafts: bool = True
    enqueue: bool = True
    n_drafts: int = 2


@router.post("/self-dev/trigger")
async def trigger_self_development(body: SelfDevTriggerBody, request: Request):
    """On-demand Nate self-development proposal (bi-weekly agent also runs)."""
    # QUANTUM-CRYSTAL-ARCH
    agent = getattr(request.app.state, "six_quotient_self_dev_agent", None)
    if not agent or not hasattr(agent, "run_once"):
        raise HTTPException(503, "six_quotient_self_dev_agent unavailable")
    result = await agent.run_once(
        environment=body.environment,
        persist_drafts=body.persist_drafts,
        enqueue=body.enqueue,
        n_drafts=body.n_drafts,
    )
    return {"status": "ok", "result": result}


@router.get("/judge/gold")
async def judge_gold(request: Request):
    from app.services.six_quotient_judge_calibration import load_gold

    gold = load_gold()
    # Hide gold ratings from casual peek? Admin-only router — return full for calibration UX
    return {"status": "ok", "gold": gold}


@router.post("/judge/calibrate")
async def judge_calibrate(body: JudgeCalibrateBody, request: Request):
    pool = _pool(request)
    from app.services.six_quotient_judge_calibration import (
        calibrate_evaluator,
        persist_calibration,
    )

    result = calibrate_evaluator(body.ratings)
    cal_id = await persist_calibration(pool, body.evaluator_id, result)
    return {
        "status": "ok",
        "calibration_id": cal_id,
        "evaluator_id": body.evaluator_id,
        "result": result,
    }


class HoldoutBody(BaseModel):
    fraction: float = 0.3
    environment: str = "production"


class NightlyTriggerBody(BaseModel):
    limit: int = 8


@router.post("/bank/holdout")
async def bank_holdout(body: HoldoutBody, request: Request):
    """Deterministic holdout split for transfer measurement (D.12)."""
    # QUANTUM-CRYSTAL-ARCH
    pool = _pool(request)
    from app.services.six_quotient_scenario_bank import mark_holdout

    result = await mark_holdout(
        pool, fraction=body.fraction, environment=body.environment
    )
    return {"status": "ok", **result}


@router.get("/trend")
async def theta_trend(
    request: Request,
    days: int = 30,
    environment: str = "production",
):
    """Nightly/weekly/transfer θ trend rows (newest first)."""
    # QUANTUM-CRYSTAL-ARCH
    pool = _pool(request)
    days = max(1, min(int(days or 30), 365))
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, environment, run_id::text, run_kind, theta,
                          theta_by_section, seen_theta, held_out_theta,
                          scenario_count, created_at
                   FROM six_quotient_theta_trend
                   WHERE environment = $1
                     AND created_at >= NOW() - ($2::int * INTERVAL '1 day')
                   ORDER BY created_at DESC
                   LIMIT 200""",
                environment,
                days,
            )
    except Exception as e:
        logger.warning("trend query: %s", e)
        return []
    out = []
    for r in rows:
        d = dict(r)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        tbs = d.get("theta_by_section")
        if isinstance(tbs, str):
            try:
                d["theta_by_section"] = json.loads(tbs)
            except Exception:
                pass
        out.append(d)
    # Auditor rule: empty list, never {}
    return out


@router.post("/nightly/trigger")
async def trigger_nightly(body: NightlyTriggerBody, request: Request):
    """Smoke: force nightly measure (bypasses 02–03 UTC hour gate)."""
    # QUANTUM-CRYSTAL-ARCH
    agent = getattr(request.app.state, "six_quotient_battery_agent", None)
    if not agent or not hasattr(agent, "_maybe_nightly"):
        raise HTTPException(503, "six_quotient_battery_agent unavailable")
    result = await agent._maybe_nightly(force=True, limit=body.limit)
    if result.get("status") == 409 or (
        not result.get("ok") and "off" in str(result.get("error") or "")
    ):
        raise HTTPException(409, result.get("error") or "nightly off")
    return {"status": "ok", "result": result}
