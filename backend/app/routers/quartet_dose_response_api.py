"""
Quartet dose-response scoring API (quartet_dose_response_v1).

Read-only against generation data (six_quotient_human_gold, recovered
transcripts), write-only to quartet_dose_response_queue. Scores the safety
quartet (AQ-1, AQ-2, AQ-G07, AQ-G08) under two conditions —
before_no_affinity vs after_affinity_fix — with the standard capability-track
rubric (primary/accuracy/naturalness/safety_veto) plus a six-move-per-scenario
spine checklist (present/partial/absent), stored as JSONB.

Seeding (populating the queue) is a one-time operational step done via
backend/scripts/seed_quartet_dose_response.py, not via this router — this
router never reads six_quotient_human_gold or the recovered transcripts
directly; it only serves/scores rows already in quartet_dose_response_queue.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.services.api_server import require_admin
from app.services.quartet_spine_moves import (
    QUARTET_SCENARIOS,
    SPINE_MOVES,
    SPINE_MOVE_VALUES,
    moves_present_count,
)

logger = logging.getLogger("nate.quartet_dose_response_api")

router = APIRouter(
    prefix="/api/admin/quartet-dose-response",
    tags=["quartet-dose-response"],
    dependencies=[Depends(require_admin)],
)

_ALLOWED_RATERS = frozenset({"DrNevedal1"})
# Same D.14b dwell floor as the principal-review gold surface.
MIN_ITEM_LATENCY_MS = 45000
_CONDITION_PAIRS = {
    "quartet_dose_response_v1": ("before_no_affinity", "after_affinity_fix"),
    "quartet_dose_response_v2": ("before_compound_must", "after_must_sequence_pack"),
}
_CONDITIONS = _CONDITION_PAIRS["quartet_dose_response_v1"]
_DEFAULT_SESSION_LABEL = "quartet_dose_response_v1"


def _conditions_for_session(session_label: str) -> tuple:
    return _CONDITION_PAIRS.get(
        (session_label or "").strip(),
        _CONDITION_PAIRS["quartet_dose_response_v1"],
    )


def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(500, "Database pool unavailable")
    return pool


def _rater(user: Dict[str, Any]) -> str:
    u = (user or {}).get("username") or (user or {}).get("user") or (user or {}).get("name") or ""
    return str(u).strip()


def _as_dict(value: Any) -> Dict[str, Any]:
    """asyncpg may return JSONB as a raw str depending on codec setup — never
    assume it's already a dict."""
    if isinstance(value, str):
        try:
            return json.loads(value) or {}
        except Exception:
            return {}
    return dict(value) if value else {}


def _enforce_item_latency(latency_ms: int) -> int:
    ms = int(latency_ms)
    if ms < MIN_ITEM_LATENCY_MS:
        raise HTTPException(
            422,
            f"latency_ms={ms} below floor {MIN_ITEM_LATENCY_MS} "
            "(dose-response scoring requires the same >=45s/item dwell as gold scoring)",
        )
    return ms


@router.get("/health")
async def health():
    return {"status": "ok", "surface": "quartet_dose_response"}


@router.get("/moves")
async def get_moves():
    """Static move definitions for UI rendering — one entry per quartet scenario."""
    return {"status": "ok", "scenarios": QUARTET_SCENARIOS, "moves": SPINE_MOVES}


class StartSessionBody(BaseModel):
    session_label: str = _DEFAULT_SESSION_LABEL
    notes: str = ""


@router.post("/session/start")
async def session_start(
    body: StartSessionBody,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    """Reuses six_quotient_gold_admin_runs for session bookkeeping (rater
    allowlist + latency-floor gate identical to the gold surface), tagged
    with purpose='quartet_dose_response_v1' so it never collides with normal
    gold-scoring runs in reporting."""
    rater = _rater(admin)
    if rater not in _ALLOWED_RATERS:
        raise HTTPException(403, f"rater_id {rater!r} not in allowlist")

    run_id = f"qdr_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
    pool = _pool(request)
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO six_quotient_gold_admin_runs
               (run_id, purpose, rater_id, notes)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (run_id) DO NOTHING""",
            run_id,
            "quartet_dose_response_v1",
            rater[:64],
            (body.notes or "")[:2000] or None,
        )
    return {
        "status": "ok",
        "run_id": run_id,
        "rater_id": rater,
        "session_label": (body.session_label or _DEFAULT_SESSION_LABEL)[:120],
        "min_item_latency_ms": MIN_ITEM_LATENCY_MS,
    }


@router.get("/items")
async def get_items(
    request: Request,
    session_label: str = _DEFAULT_SESSION_LABEL,
):
    """8 rows, interleaved by scenario (before/after pairs adjacent), ordered
    by sort_order as seeded. Read-only against quartet_dose_response_queue."""
    pool = _pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, session_label, scenario_id, section, client_says,
                      condition_label, response_text, source, original_run_id,
                      text_provenance, sort_order, primary_score, accuracy_score,
                      naturalness_score, safety_veto, spine_moves,
                      moves_present_count, notes, human_scored, rater_id,
                      scored_at, score_latency_ms
               FROM quartet_dose_response_queue
               WHERE session_label = $1
               ORDER BY sort_order ASC""",
            session_label,
        )
    if not rows:
        raise HTTPException(
            404,
            f"no rows for session_label={session_label!r} — run "
            "backend/scripts/seed_quartet_dose_response.py first",
        )
    items = []
    for r in rows:
        d = dict(r)
        d["id"] = int(d["id"])
        d["spine_moves"] = _as_dict(d["spine_moves"])
        items.append(d)
    scored = sum(1 for i in items if i["human_scored"])
    return {
        "status": "ok",
        "session_label": session_label,
        "count": len(items),
        "scored": scored,
        "remaining": len(items) - scored,
        "moves": SPINE_MOVES,
        "items": items,
    }


class SpineMoveEntry(BaseModel):
    value: str
    reason: Optional[str] = None

    @field_validator("value")
    @classmethod
    def _val(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in SPINE_MOVE_VALUES:
            raise ValueError(f"value must be one of {sorted(SPINE_MOVE_VALUES)}")
        return v

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        # "one-word reason" — keep it terse; take the first token if someone pastes a sentence.
        return v.split()[0][:40]


class QuartetScoreBody(BaseModel):
    item_id: int
    run_id: str
    primary: int = Field(..., ge=0, le=3)
    accuracy: int = Field(..., ge=0, le=3)
    naturalness: int = Field(..., ge=0, le=3)
    safety_veto: Optional[str] = None
    notes: str = ""
    latency_ms: int = Field(..., ge=0)
    spine_moves: Dict[str, SpineMoveEntry]

    @field_validator("safety_veto")
    @classmethod
    def _veto(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip().lower()
        if v not in ("ok", "fail"):
            raise ValueError("safety_veto must be ok|fail")
        return v


@router.post("/score")
async def score_item(
    body: QuartetScoreBody,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    rater = _rater(admin)
    if rater not in _ALLOWED_RATERS:
        raise HTTPException(403, f"rater_id {rater!r} not in allowlist")
    latency_ms = _enforce_item_latency(body.latency_ms)
    pool = _pool(request)

    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            "SELECT run_id, rater_id, purpose FROM six_quotient_gold_admin_runs WHERE run_id = $1",
            body.run_id,
        )
        if not run:
            raise HTTPException(404, "session run not found — start a session first")
        if (run["rater_id"] or "") != rater:
            raise HTTPException(403, "run belongs to a different rater")

        target = await conn.fetchrow(
            "SELECT id, scenario_id FROM quartet_dose_response_queue WHERE id = $1",
            body.item_id,
        )
        if not target:
            raise HTTPException(404, "item not found in quartet_dose_response_queue")

        expected_moves = {m["id"] for m in SPINE_MOVES.get(target["scenario_id"], [])}
        submitted_moves = set(body.spine_moves.keys())
        unknown = submitted_moves - expected_moves
        if unknown:
            raise HTTPException(422, f"unknown move ids for {target['scenario_id']}: {sorted(unknown)}")
        missing = expected_moves - submitted_moves
        if missing:
            raise HTTPException(422, f"missing move ids for {target['scenario_id']}: {sorted(missing)}")

        for move_id, entry in body.spine_moves.items():
            if entry.value == "partial" and not entry.reason:
                raise HTTPException(422, f"move {move_id!r} marked partial requires a one-word reason")

        spine_json = {k: {"value": v.value, "reason": v.reason} for k, v in body.spine_moves.items()}
        count = moves_present_count(spine_json)

        await conn.execute(
            """UPDATE quartet_dose_response_queue SET
                 primary_score = $2,
                 accuracy_score = $3,
                 naturalness_score = $4,
                 safety_veto = $5,
                 spine_moves = $6::jsonb,
                 moves_present_count = $7,
                 notes = COALESCE(NULLIF($8, ''), notes),
                 human_scored = true,
                 rater_id = $9,
                 scored_at = NOW(),
                 score_latency_ms = $10,
                 score_session_id = $11,
                 gold_admin_run_id = $11
               WHERE id = $1""",
            body.item_id,
            body.primary,
            body.accuracy,
            body.naturalness,
            body.safety_veto,
             json.dumps(spine_json),
            count,
            (body.notes or "").strip()[:4000],
            rater[:64],
            latency_ms,
            body.run_id[:80],
        )

    return {
        "status": "ok",
        "item_id": body.item_id,
        "scenario_id": target["scenario_id"],
        "moves_present_count": count,
        "rater_id": rater,
        "latency_ms": latency_ms,
    }


@router.get("/report")
async def report(
    request: Request,
    session_label: str = _DEFAULT_SESSION_LABEL,
):
    """2x4 grid (condition x scenario) of move-counts, plus per-move transfer
    rates across conditions (present-rate in after_affinity_fix minus
    present-rate in before_no_affinity, per move id, pooled across scenarios
    that share that move id)."""
    pool = _pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT scenario_id, condition_label, primary_score, accuracy_score,
                      naturalness_score, safety_veto, spine_moves, moves_present_count,
                      human_scored
               FROM quartet_dose_response_queue
               WHERE session_label = $1""",
            session_label,
        )
    if not rows:
        raise HTTPException(404, f"no rows for session_label={session_label!r}")

    by_key: Dict[tuple, Dict[str, Any]] = {(r["scenario_id"], r["condition_label"]): dict(r) for r in rows}
    total = len(rows)
    scored = sum(1 for r in rows if r["human_scored"])
    before_cond, after_cond = _conditions_for_session(session_label)

    grid: List[Dict[str, Any]] = []
    for scenario_id in QUARTET_SCENARIOS:
        row_entry = {"scenario_id": scenario_id}
        for cond in (before_cond, after_cond):
            r = by_key.get((scenario_id, cond))
            row_entry[cond] = {
                "human_scored": bool(r and r["human_scored"]),
                "moves_present_count": (r or {}).get("moves_present_count"),
                "primary_score": (r or {}).get("primary_score"),
                "safety_veto": (r or {}).get("safety_veto"),
            }
        grid.append(row_entry)

    # Per-move transfer rate: present-rate delta (after - before), pooled
    # across every (scenario, move_id) pair that is scored in BOTH conditions.
    move_stats: Dict[str, Dict[str, int]] = {}
    for scenario_id in QUARTET_SCENARIOS:
        before = by_key.get((scenario_id, before_cond))
        after = by_key.get((scenario_id, after_cond))
        if not (before and after and before["human_scored"] and after["human_scored"]):
            continue
        before_moves = _as_dict(before["spine_moves"])
        after_moves = _as_dict(after["spine_moves"])
        for move_def in SPINE_MOVES.get(scenario_id, []):
            mid = move_def["id"]
            key = f"{scenario_id}:{mid}"
            b_val = (before_moves.get(mid) or {}).get("value")
            a_val = (after_moves.get(mid) or {}).get("value")
            if b_val is None or a_val is None:
                continue
            move_stats[key] = {
                "scenario_id": scenario_id,
                "move_id": mid,
                "before": b_val,
                "after": a_val,
                "improved": 1 if _rank(a_val) > _rank(b_val) else 0,
                "regressed": 1 if _rank(a_val) < _rank(b_val) else 0,
                "unchanged": 1 if _rank(a_val) == _rank(b_val) else 0,
            }

    pairs_scored = sum(1 for k, v in move_stats.items())
    improved = sum(v["improved"] for v in move_stats.values())
    regressed = sum(v["regressed"] for v in move_stats.values())
    unchanged = sum(v["unchanged"] for v in move_stats.values())

    condition_totals = {}
    for cond in (before_cond, after_cond):
        vals = [by_key[(s, cond)]["moves_present_count"] for s in QUARTET_SCENARIOS if (s, cond) in by_key and by_key[(s, cond)]["human_scored"]]
        condition_totals[cond] = {
            "n_scenarios_scored": len(vals),
            "avg_moves_present": round(sum(vals) / len(vals), 2) if vals else None,
            "total_moves_present": round(sum(vals), 1) if vals else None,
        }

    return {
        "status": "ok",
        "session_label": session_label,
        "total_rows": total,
        "scored_rows": scored,
        "grid": grid,
        "condition_totals": condition_totals,
        "move_transfer": {
            "pairs_evaluated": pairs_scored,
            "improved": improved,
            "regressed": regressed,
            "unchanged": unchanged,
            "detail": list(move_stats.values()),
        },
        "dose_response_ready": scored == total,
    }


def _rank(value: str) -> int:
    return {"absent": 0, "partial": 1, "present": 2}.get(value, -1)
