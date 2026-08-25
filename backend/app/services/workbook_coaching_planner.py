"""Daily coaching planner + LN-influence reflection.

Given a client, this module produces (1) a short "hold in reserve" plan of
1-2 workbook methods for the day and (2) a self-reflection record of how
LN's prior workbook suggestions correlate with the client's cycle phase and
recent tone. It is deterministic, DB-lite, and safe to run without the
LLM.

Inputs:
    - db_pool  (asyncpg pool, optional — degrades to intent-only mode)
    - hardware_id (username or hardware_id)
    - recent_texts (last N client messages, oldest→newest)

Outputs (``plan_for_user``):
    {
        "hardware_id": str,
        "predicted_methods": [ {method, workbook_file, confidence, why}, ... ],
        "cycle_signals": [ {domain, phase, next_peak_days} ],
        "foreshadow": str,   # one-line "positive change if we practice X"
        "self_reflection": {
            "past_offers": int,
            "estimated_influence": "positive|neutral|regressive|unknown",
            "note": str,
        },
    }
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from app.services.workbook_catalog import catalog_titles
from app.services.workbook_intent_classifier import classify

logger = logging.getLogger(__name__)


async def _load_recent_texts(db_pool, hw_id: str, limit: int = 12) -> List[str]:
    if db_pool is None:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_text
                FROM conversation_history
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                hw_id,
                int(limit),
            )
        return [r["user_text"] for r in rows if r and r["user_text"]][::-1]
    except Exception as exc:  # pragma: no cover - deployment quirks
        logger.warning("planner: recent_texts load failed for %s: %s", hw_id, exc)
        return []


async def _load_cycle_signals(app_state, hw_id: str) -> List[Dict[str, Any]]:
    engine = getattr(app_state, "cycle_detection_engine", None) if app_state else None
    if engine is None:
        return []
    try:
        result = await engine.detect_cycles(hw_id)
    except Exception as exc:
        logger.warning("planner: cycle detection failed for %s: %s", hw_id, exc)
        return []
    out: List[Dict[str, Any]] = []
    for dom_id, dom in (result or {}).items():
        if not isinstance(dom, dict):
            continue
        if dom.get("status") != "cycles_detected":
            continue
        cycles = dom.get("detected_cycles") or []
        phase = dom.get("current_phase") or {}
        if cycles:
            top = cycles[0]
            out.append(
                {
                    "domain": dom_id,
                    "display_name": dom.get("display_name") or dom_id,
                    "period_days": float(top.get("period_days") or 0.0),
                    "confidence": float(top.get("confidence") or 0.0),
                    "phase_label": str(phase.get("phase_label") or phase.get("phase") or ""),
                    "peak_is_risk": bool(dom.get("peak_is_risk")),
                }
            )
    out.sort(key=lambda x: x.get("confidence", 0.0), reverse=True)
    return out[:3]


async def _count_prior_offers(db_pool, hw_id: str) -> int:
    if db_pool is None:
        return 0
    try:
        async with db_pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT COUNT(*) FROM nate_intelligence_crystals
                WHERE user_id::text = $1
                  AND domain = 'coaching'
                  AND metadata->>'stance' = 'coaching_not_therapy'
                """,
                str(hw_id),
            )
        return int(n or 0)
    except Exception:
        return 0


def _foreshadow_for(method: str) -> str:
    return {
        "gestalt": "If we do one empty-chair pass this week, the unfinished conversation stops running the background.",
        "ifs": "Naming the parts in one map usually softens the internal fight within 2-3 days.",
        "eft": "Once the pursue/withdraw cycle is on paper, the next argument gets 30% shorter.",
        "polyvagal": "A single ventral-cue practice reduces the shutdown windows by mid-week.",
        "memory_reconsolidation": "One clean juxtaposition pass can loosen a lifelong belief in a single sitting.",
        "boundary_stabilization": "Rehearsing one exact sentence beats replaying the argument ten times.",
        "behavioral_activation": "One 15-minute action today buys you tomorrow's momentum.",
    }.get(method, "Practicing one named tool this week is worth more than three insight conversations.")


async def plan_for_user(
    db_pool,
    app_state,
    hardware_id: str,
    recent_texts: Optional[Sequence[str]] = None,
    skill_plan_locked: bool = False,
) -> Dict[str, Any]:
    catalog = catalog_titles(max_files=32)
    texts = list(recent_texts) if recent_texts else await _load_recent_texts(db_pool, hardware_id)
    predicted: List[Dict[str, Any]] = []
    seen_methods: set[str] = set()
    for i in range(len(texts) - 1, -1, -1):
        res = classify(
            texts[i], recent_texts=texts[:i], skill_plan_locked=skill_plan_locked, catalog=catalog
        )
        if res.method == "none" or res.method in seen_methods:
            continue
        seen_methods.add(res.method)
        predicted.append(
            {
                "method": res.method,
                "workbook_file": res.workbook_file,
                "confidence": res.confidence,
                "action": res.action,
                "why": res.rationale,
            }
        )
        if len(predicted) >= 2:
            break

    cycles = await _load_cycle_signals(app_state, hardware_id)
    priors = await _count_prior_offers(db_pool, hardware_id)

    if predicted:
        foreshadow = _foreshadow_for(predicted[0]["method"])
    else:
        foreshadow = "No clear method match yet — observe another turn or two before offering a tool."

    if priors == 0:
        influence = "unknown"
        influence_note = "No prior workbook offers recorded for this client — first offer will be the baseline."
    elif priors < 3:
        influence = "unknown"
        influence_note = f"{priors} prior offers — sample too small to judge influence."
    else:
        risky_cycle = any(c.get("peak_is_risk") and (c.get("confidence", 0) >= 0.4) for c in cycles)
        if risky_cycle:
            influence = "neutral"
            influence_note = (
                f"{priors} prior offers, but a risk-side cycle is still active — "
                "re-check whether the offered tools were rehearsed or only discussed."
            )
        else:
            influence = "positive"
            influence_note = (
                f"{priors} prior offers with no risk-side cycle currently detected — "
                "workbook practice appears to be tracking with reduced volatility."
            )

    return {
        "hardware_id": hardware_id,
        "predicted_methods": predicted,
        "cycle_signals": cycles,
        "foreshadow": foreshadow,
        "self_reflection": {
            "past_offers": priors,
            "estimated_influence": influence,
            "note": influence_note,
        },
    }


__all__ = ["plan_for_user"]
