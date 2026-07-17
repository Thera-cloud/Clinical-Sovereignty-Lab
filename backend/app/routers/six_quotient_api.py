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


@router.get("/health")
async def health(request: Request):
    """Battery subsystem health — always structurally non-empty."""
    pool = _pool(request)
    enabled = _enabled()
    last_run = None
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
    except Exception as e:
        logger.warning("six_quotient health query: %s", e)
        return {
            "status": "degraded",
            "enabled": enabled,
            "tables_ok": False,
            "error": str(e)[:200],
            "last_run": None,
        }
    return {
        "status": "ok",
        "enabled": enabled,
        "tables_ok": True,
        "last_run": last_run or {"status": "none"},
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

    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            "SELECT id, status FROM six_quotient_runs WHERE id = $1::uuid",
            body.run_id,
        )
        if not run:
            raise HTTPException(404, "run not found")

        inserted = 0
        for item in body.scores:
            section = item.section or item.scenario_id.split("-")[0]
            await conn.execute(
                """INSERT INTO six_quotient_scores
                   (run_id, scenario_id, section, primary_score, accuracy_score,
                    naturalness_score, evaluator_id, notes)
                   VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8)
                   ON CONFLICT (run_id, scenario_id) DO UPDATE SET
                     primary_score = EXCLUDED.primary_score,
                     accuracy_score = EXCLUDED.accuracy_score,
                     naturalness_score = EXCLUDED.naturalness_score,
                     evaluator_id = EXCLUDED.evaluator_id,
                     notes = EXCLUDED.notes""",
                body.run_id,
                item.scenario_id,
                section.upper(),
                item.primary,
                item.accuracy,
                item.naturalness,
                body.evaluator_id,
                item.notes or "",
            )
            inserted += 1

        await conn.execute(
            """UPDATE six_quotient_runs
               SET status = 'awaiting_scores', updated_at = NOW()
               WHERE id = $1::uuid AND status IN ('running', 'awaiting_scores', 'failed')""",
            body.run_id,
        )

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
    )
    return {"status": "ok", "result": result}
