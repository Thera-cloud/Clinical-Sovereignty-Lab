"""
Auto-judge for nightly measurement — grok-judge-v1 via calibrated score intake.

Never fabricates scores on LLM failure; leaves run awaiting_scores.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sovereign.six_quotient_auto_judge")

_LLM_TIMEOUT_S = 120.0  # QUANTUM-CRYSTAL-ARCH — clinical judge prompts can exceed 45s on Workers/Grok
DEFAULT_EVALUATOR = "grok-judge-v1"


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _clamp_score(v: Any) -> Optional[int]:
    try:
        i = int(v)
    except Exception:
        return None
    if 0 <= i <= 3:
        return i
    return None


async def _llm_judge(
    app_state,
    *,
    scenario_id: str,
    section: str,
    rubric_focus: str,
    client_says: str,
    response: str,
) -> Optional[Dict[str, int]]:
    system = (
        "You are a calibrated clinical therapy judge (TherapyJudgeBench style). "
        "Score Nate's response 0-3 on primary (clinical skill), accuracy "
        "(standards-sound), naturalness (real therapist, not chatbot). "
        "Return ONLY JSON: "
        '{"primary":0-3,"accuracy":0-3,"naturalness":0-3,"notes":"..."}'
    )
    user = (
        f"scenario_id: {scenario_id}\n"
        f"section: {section}\n"
        f"rubric_focus: {rubric_focus}\n"
        f"client_says: {client_says}\n"
        f"nate_response: {response}\n"
    )
    # QUANTUM-CRYSTAL-ARCH — app.state has littlenate_inference only; router not mounted.
    # Instantiate NateInferenceRouter (same pattern as newsletter / commitments).
    router = None
    if app_state:
        router = getattr(app_state, "nate_inference_router", None)
    if router is None or not hasattr(router, "generate"):
        try:
            from app.services.nate_inference_router import NateInferenceRouter

            router = NateInferenceRouter(app_state=app_state)
        except Exception as e:
            logger.warning("auto_judge LLM: router init failed: %s", e)
            return None
    try:
        resp = await asyncio.wait_for(
            router.generate(
                prompt=user,
                system=system,
                domain="clinical",
                tier="clinical",
                max_tokens=300,
                temperature=0.2,
            ),
            timeout=_LLM_TIMEOUT_S,
        )
    except Exception as e:
        logger.warning("auto_judge LLM: %s: %s", type(e).__name__, e or repr(e))
        return None
    text = ""
    if isinstance(resp, dict):
        text = str(resp.get("text") or resp.get("content") or resp.get("response") or "")
    else:
        text = str(getattr(resp, "text", None) or getattr(resp, "content", None) or resp or "")
    parsed = _extract_json(text)
    if not parsed:
        logger.warning("auto_judge parse fail: %s", (text or "")[:180])
        return None
    p = _clamp_score(parsed.get("primary"))
    a = _clamp_score(parsed.get("accuracy"))
    n = _clamp_score(parsed.get("naturalness"))
    if p is None or a is None or n is None:
        logger.warning("auto_judge score clamp fail: %s", parsed)
        return None
    return {
        "primary": p,
        "accuracy": a,
        "naturalness": n,
        "notes": str(parsed.get("notes") or "")[:500],
    }


async def auto_score_run(
    db_pool,
    app_state,
    run_id: str,
    evaluator_id: str = DEFAULT_EVALUATOR,
    *,
    enqueue_ceo: bool = False,
    update_ability: bool = True,
    ingest_growth: bool = False,
) -> Dict[str, Any]:
    """
    Load run responses, LLM-score each, upsert via shared intake, analyze.
    On any failure: return ok=False without fabricating remaining scores.
    """
    if not db_pool:
        return {"ok": False, "error": "no_db_pool"}
    try:
        async with db_pool.acquire() as conn:
            run = await conn.fetchrow(
                """SELECT id::text, status, results_json, environment
                   FROM six_quotient_runs WHERE id = $1::uuid""",
                run_id,
            )
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    if not run:
        return {"ok": False, "error": "run not found"}

    payload = run["results_json"] or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    results = payload.get("results") or []
    if not results:
        return {"ok": False, "error": "no results on run"}

    scored: List[Dict[str, Any]] = []
    for r in results:
        sid = str(r.get("scenario_id") or r.get("id") or "").strip()
        if not sid:
            continue
        response = str(r.get("response") or "")
        if not response.strip():
            return {"ok": False, "error": f"empty response for {sid}"}
        judged = await _llm_judge(
            app_state,
            scenario_id=sid,
            section=str(r.get("section") or sid.split("-")[0]),
            rubric_focus=str(r.get("rubric_focus") or ""),
            client_says=str(r.get("client_says") or ""),
            response=response,
        )
        if not judged:
            return {"ok": False, "error": f"judge failed for {sid}", "scored_partial": len(scored)}
        scored.append({
            "scenario_id": sid,
            "section": str(r.get("section") or sid.split("-")[0]).upper(),
            **judged,
        })

    from app.services.six_quotient_score_intake import upsert_scores

    up = await upsert_scores(
        db_pool,
        run_id=run_id,
        evaluator_id=evaluator_id,
        scores=scored,
        require_calibration=True,
    )
    if not up.get("ok"):
        return up

    from app.services.six_quotient_gap_analyzer import analyze_and_enqueue

    analysis = await analyze_and_enqueue(
        db_pool,
        run_id,
        origin="six_quotient_nightly",
        enqueue_ceo=enqueue_ceo,
        update_ability=update_ability,
    )
    if ingest_growth and analysis.get("ok") and app_state:
        growth = getattr(app_state, "six_quotient_growth_engine", None)
        if growth and hasattr(growth, "ingest_battery_findings"):
            try:
                await growth.ingest_battery_findings(run_id, analysis)
            except Exception as e:
                logger.warning("auto_judge growth ingest: %s", e)

    return {
        "ok": bool(analysis.get("ok")),
        "run_id": run_id,
        "evaluator_id": evaluator_id,
        "scores_upserted": up.get("scores_upserted"),
        "analysis": analysis,
        "error": analysis.get("error"),
    }
