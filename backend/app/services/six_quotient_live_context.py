"""
Six-quotient live context — inject CEO-approved + battery weakness cues into therapy.

Flag: ENABLE_SIX_QUOTIENT_LIVE_CONTEXT (default false until soak).

Reads ability θ, latest gap_summary, and live_focus (CEO-approved self-dev).
Returns a short system-prompt addendum. No auto clinical action beyond cueing.

QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("sovereign.six_quotient_live_context")

_FOCUS = {
    "AQ": "crisis safety / lethality witnessing — assess means/intent without debating philosophy",
    "EQ": "affective presence / somatic interrupt — interrupt intellectualization with body cues",
    "MQ": "moral injury / non-prescriptive holding — do not offer coping scripts for unsolvable loss",
    "SQ": "rupture-repair / parallel-process mirror — name control-as-alliance tests",
    "CQ": "cultural formulation / non-decoding metaphor — do not pathologize cultural language",
    "IQ": "clinical reasoning without intellectualization — stay with affect under analysis armor",
}


def _flag_on() -> bool:
    return os.getenv("ENABLE_SIX_QUOTIENT_LIVE_CONTEXT", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _env_name() -> str:
    return (
        os.getenv("SIX_QUOTIENT_BATTERY_ENV")
        or os.getenv("ENVIRONMENT")
        or "production"
    )


async def get_live_addendum(
    db_pool,
    *,
    environment: Optional[str] = None,
) -> str:
    """Return prompt block or empty string when flag off / no signal."""
    if not _flag_on() or not db_pool:
        return ""
    env = environment or _env_name()
    try:
        from app.services.six_quotient_scenario_bank import get_ability

        ability = await get_ability(db_pool, env)
        focus = await _load_live_focus(db_pool, env)
        gap = await _latest_gap(db_pool, env)
        return _format_addendum(ability, focus, gap)
    except Exception as e:
        logger.warning("six_quotient live context: %s", e)
        return ""


async def apply_self_dev_focus(
    db_pool,
    payload: Dict[str, Any],
    *,
    approved_by: str = "ceo",
) -> Dict[str, Any]:
    """Persist CEO-approved self-dev focus + promote matching battery crystals."""
    if not db_pool:
        return {"ok": False, "error": "no_db_pool"}
    env = str(payload.get("environment") or _env_name())
    section = str(payload.get("focus_quotient") or "").upper()
    capability = str(payload.get("focus_capability") or _FOCUS.get(section, section))
    if section not in _FOCUS:
        return {"ok": False, "error": "invalid_focus_quotient"}
    focus = {
        "focus_quotient": section,
        "focus_capability": capability,
        "approved_by": (approved_by or "ceo")[:80],
        "source_run_id": payload.get("source_run_id"),
        "coach_feedback_request": payload.get("coach_feedback_request"),
        "kind": "six_quotient_self_dev",
    }
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO six_quotient_ability_state
               (environment, theta, theta_by_section, live_focus, updated_at)
               VALUES ($1, 0.0, '{}'::jsonb, $2::jsonb, NOW())
               ON CONFLICT (environment) DO UPDATE SET
                 live_focus = EXCLUDED.live_focus,
                 updated_at = NOW()""",
            env,
            json.dumps(focus),
        )
        bumped = await conn.execute(
            """UPDATE nate_intelligence_crystals
               SET confidence = GREATEST(confidence, 0.58),
                   updated_at = NOW()
               WHERE origin_surface = 'six_quotient_battery'
                 AND metadata->>'quotient' = $1
                 AND superseded_by IS NULL""",
            section,
        )
    return {
        "ok": True,
        "environment": env,
        "focus": focus,
        "crystals_bumped": bumped,
    }


async def _load_live_focus(db_pool, environment: str) -> Dict[str, Any]:
    async with db_pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """SELECT live_focus FROM six_quotient_ability_state
                   WHERE environment = $1""",
                environment,
            )
        except Exception:
            return {}
    if not row:
        return {}
    focus = row["live_focus"]
    if isinstance(focus, str):
        try:
            focus = json.loads(focus)
        except Exception:
            return {}
    return focus if isinstance(focus, dict) else {}


async def _latest_gap(db_pool, environment: str) -> Optional[Dict[str, Any]]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT gap_summary FROM six_quotient_runs
               WHERE status = 'scored' AND environment = $1
                 AND gap_summary IS NOT NULL
               ORDER BY scored_at DESC NULLS LAST LIMIT 1""",
            environment,
        )
    if not row:
        return None
    gap = row["gap_summary"]
    if isinstance(gap, str):
        try:
            gap = json.loads(gap)
        except Exception:
            return None
    return gap if isinstance(gap, dict) else None


def _format_addendum(
    ability: Dict[str, Any],
    focus: Dict[str, Any],
    gap: Optional[Dict[str, Any]],
) -> str:
    lines = [
        "## SIX-QUOTIENT DEVELOPMENT CUES (externally scored — do not self-grade)",
        "Use only as clinical stance cues. Never invent battery scores or claim a completed exam.",
    ]
    fq = (focus or {}).get("focus_quotient")
    if fq:
        cap = focus.get("focus_capability") or _FOCUS.get(str(fq).upper(), fq)
        lines.append(
            f"CEO-approved focus this cycle: {fq} — {cap}."
        )
    tbs = ability.get("theta_by_section") or {}
    weak = []
    for q in ("AQ", "EQ", "MQ", "SQ", "CQ", "IQ"):
        meta = (gap or {}).get("quotients", {}).get(q) or {}
        risk = meta.get("risk") or ""
        theta = tbs.get(q)
        if risk in ("RED", "YELLOW") or (
            theta is not None and float(theta) < -0.5
        ):
            weak.append(
                f"{q}({risk or 'low-θ'}): {_FOCUS.get(q, q)}"
            )
    if weak:
        lines.append("Priority reinforcement: " + "; ".join(weak[:3]) + ".")
    if len(lines) <= 2:
        return ""
    return "\n".join(lines) + "\n"
