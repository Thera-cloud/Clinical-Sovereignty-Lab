"""
Shared six-quotient score upsert used by REST /scores and auto-judge.

AI evaluator ids must pass judge calibration before upsert.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sovereign.six_quotient_score_intake")

_AI_EVAL_MARKERS = (
    "gpt", "claude", "gemini", "grok", "judge", "llm", "model",
    "openai", "anthropic", "azure",
)


def is_ai_evaluator(evaluator_id: str) -> bool:
    low = (evaluator_id or "").lower()
    return any(m in low for m in _AI_EVAL_MARKERS)


async def upsert_scores(
    db_pool,
    *,
    run_id: str,
    evaluator_id: str,
    scores: List[Dict[str, Any]],
    require_calibration: bool = True,
) -> Dict[str, Any]:
    """
    scores items: scenario_id, section?, primary, accuracy, naturalness, notes?
    Returns {ok, scores_upserted, error?}.
    """
    if not db_pool:
        return {"ok": False, "error": "no_db_pool"}
    evaluator_id = (evaluator_id or "").strip()
    if not evaluator_id:
        return {"ok": False, "error": "evaluator_id required"}
    if evaluator_id.lower() in ("self", "cli", "little_nate", "nate", "auto", "system"):
        return {"ok": False, "error": "evaluator_id must be external human or designated model id"}
    if not scores:
        return {"ok": False, "error": "scores required"}

    if require_calibration and is_ai_evaluator(evaluator_id):
        from app.services.six_quotient_judge_calibration import evaluator_is_calibrated

        if not await evaluator_is_calibrated(db_pool, evaluator_id):
            return {
                "ok": False,
                "error": "AI evaluator not calibrated — POST /judge/calibrate first",
            }

    async with db_pool.acquire() as conn:
        run = await conn.fetchrow(
            "SELECT id, status FROM six_quotient_runs WHERE id = $1::uuid",
            run_id,
        )
        if not run:
            return {"ok": False, "error": "run not found"}

        inserted = 0
        for item in scores:
            sid = str(item.get("scenario_id") or "").strip()
            if not sid:
                continue
            section = (item.get("section") or sid.split("-")[0] or "").upper()
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
                run_id,
                sid,
                section,
                int(item["primary"]),
                int(item["accuracy"]),
                int(item["naturalness"]),
                evaluator_id,
                str(item.get("notes") or ""),
            )
            inserted += 1

        await conn.execute(
            """UPDATE six_quotient_runs
               SET status = 'awaiting_scores', updated_at = NOW()
               WHERE id = $1::uuid AND status IN ('running', 'awaiting_scores', 'failed')""",
            run_id,
        )

    return {"ok": True, "scores_upserted": inserted, "evaluator_id": evaluator_id}
