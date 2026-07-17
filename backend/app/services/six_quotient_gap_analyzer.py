"""
Six-Quotient Gap Analyzer — scored-run deltas → Dual-COO CEO inbox.

Never invents scores. Only runs after external scores are persisted.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from app.services.six_quotient_growth_engine import BASELINE_SCORES, COMPOSITE_BASELINE

logger = logging.getLogger("sovereign.six_quotient_gap")

_QUOTIENTS = ("IQ", "EQ", "MQ", "SQ", "CQ", "AQ")
_MAX_POINTS_PER_SCENARIO = 9  # primary + accuracy + naturalness


def _tier_for_section(section: str, pct: float) -> str:
    # AQ / crisis regressions are always RED for Dual-COO
    if section.upper() == "AQ" and pct < BASELINE_SCORES["AQ"]["pct"] - 2.0:
        return "RED"
    if section.upper() in ("AQ",) and pct < 70.0:
        return "RED"
    if pct < BASELINE_SCORES.get(section.upper(), {}).get("pct", 80) - 5.0:
        return "YELLOW"
    return "GREEN"


def aggregate_scores_by_section(
    score_rows: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """score_rows: scenario_id, section, primary, accuracy, naturalness."""
    buckets: Dict[str, List[int]] = {q: [] for q in _QUOTIENTS}
    for row in score_rows:
        sec = (row.get("section") or row.get("scenario_id", "")[:2] or "").upper()
        if sec not in buckets:
            # derive from scenario_id like "AQ-1"
            sid = str(row.get("scenario_id") or "")
            sec = sid.split("-")[0].upper() if "-" in sid else sec
        if sec not in buckets:
            continue
        total = int(row.get("primary") or 0) + int(row.get("accuracy") or 0) + int(
            row.get("naturalness") or 0
        )
        buckets[sec].append(total)

    out: Dict[str, Dict[str, Any]] = {}
    for q in _QUOTIENTS:
        vals = buckets[q]
        max_pts = _MAX_POINTS_PER_SCENARIO * 4  # 4 scenarios
        score = sum(vals) if vals else 0
        # If fewer than 4 scored, scale max to completed count
        max_for_run = _MAX_POINTS_PER_SCENARIO * max(len(vals), 1) if vals else max_pts
        pct = round(100.0 * score / max_for_run, 1) if vals else 0.0
        baseline = BASELINE_SCORES[q]
        delta_pts = score - int(baseline["score"] * (len(vals) / 4.0)) if vals else 0
        # Prefer absolute pts vs baseline when all 4 present
        if len(vals) == 4:
            delta_pts = score - baseline["score"]
            pct = round(100.0 * score / max_pts, 1)
        out[q] = {
            "score": score,
            "max": max_pts if len(vals) == 4 else max_for_run,
            "pct": pct,
            "scenarios_scored": len(vals),
            "baseline_score": baseline["score"],
            "baseline_pct": baseline["pct"],
            "delta_pts": delta_pts,
            "delta_pct": round(pct - baseline["pct"], 1),
            "risk": _tier_for_section(q, pct) if vals else "YELLOW",
        }
    return out


async def analyze_and_enqueue(
    db_pool,
    run_id: str,
    *,
    origin: str = "six_quotient_battery",
) -> Dict[str, Any]:
    """Load scores for run, compute gaps, enqueue Dual-COO items, persist summary."""
    if not db_pool:
        return {"ok": False, "error": "no_db_pool"}

    async with db_pool.acquire() as conn:
        run = await conn.fetchrow(
            "SELECT id, battery_version, environment, git_hash, status "
            "FROM six_quotient_runs WHERE id = $1::uuid",
            run_id,
        )
        if not run:
            return {"ok": False, "error": "run_not_found"}
        if run["status"] not in ("scored", "awaiting_scores"):
            pass  # allow re-analyze when scored

        rows = await conn.fetch(
            """SELECT scenario_id, section, primary_score, accuracy_score,
                      naturalness_score, evaluator_id
               FROM six_quotient_scores WHERE run_id = $1::uuid""",
            run_id,
        )
        if not rows:
            return {"ok": False, "error": "no_scores"}

        # Reject if any score lacks external evaluator
        missing_eval = [r["scenario_id"] for r in rows if not (r["evaluator_id"] or "").strip()]
        if missing_eval:
            return {
                "ok": False,
                "error": "evaluator_id_required",
                "scenarios": missing_eval,
            }

        score_dicts = [
            {
                "scenario_id": r["scenario_id"],
                "section": r["section"],
                "primary": r["primary_score"],
                "accuracy": r["accuracy_score"],
                "naturalness": r["naturalness_score"],
            }
            for r in rows
        ]
        by_section = aggregate_scores_by_section(score_dicts)
        composite_score = sum(v["score"] for v in by_section.values())
        composite_max = sum(v["max"] for v in by_section.values())
        composite_pct = round(100.0 * composite_score / composite_max, 1) if composite_max else 0.0

        summary = {
            "run_id": str(run_id),
            "battery_version": run["battery_version"],
            "environment": run["environment"],
            "git_hash": run["git_hash"] or "",
            "quotients": by_section,
            "composite": {
                "score": composite_score,
                "max": composite_max,
                "pct": composite_pct,
                "baseline_pct": COMPOSITE_BASELINE["pct"],
                "delta_pct": round(composite_pct - COMPOSITE_BASELINE["pct"], 1),
            },
        }

        await conn.execute(
            """UPDATE six_quotient_runs
               SET status = 'scored',
                   gap_summary = $2::jsonb,
                   scored_at = COALESCE(scored_at, NOW()),
                   updated_at = NOW()
               WHERE id = $1::uuid""",
            run_id,
            json.dumps(summary),
        )

    # Dual-COO: YELLOW/RED → CEO inbox. GREEN stays in gap_summary only.
    enqueued: List[Dict[str, str]] = []
    try:
        from app.websocket.cli_dual_coo import RISK_RED, RISK_YELLOW, enqueue_ceo

        for q, data in by_section.items():
            risk = data["risk"]
            if risk == RISK_RED:
                enqueue_ceo(
                    risk=RISK_RED,
                    title=f"Six-Quotient {q} REGRESSION — CEO review required",
                    detail=json.dumps({"run_id": str(run_id), **data})[:2000],
                    origin=origin,
                    payload={"kind": "six_quotient_regression", "quotient": q},
                )
                enqueued.append({"quotient": q, "risk": RISK_RED})
            elif risk == RISK_YELLOW:
                enqueue_ceo(
                    risk=RISK_YELLOW,
                    title=f"Six-Quotient {q} dip — candidate fix review",
                    detail=json.dumps({"run_id": str(run_id), **data})[:2000],
                    origin=origin,
                    payload={"kind": "six_quotient_gap", "quotient": q},
                )
                enqueued.append({"quotient": q, "risk": RISK_YELLOW})
            else:
                enqueued.append({"quotient": q, "risk": "GREEN"})
    except Exception as e:
        logger.warning("Dual-COO enqueue failed (non-fatal): %s", e)

    summary["enqueued"] = enqueued
    summary["ok"] = True
    return summary
