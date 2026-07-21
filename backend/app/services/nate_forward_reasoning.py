"""
QUANTUM-CRYSTAL-ARCH: Forward reasoning — symbols/metrics → response constraints (Phase 5c).

Emits pacing/focus constraints only — never clinical conclusions or diagnoses.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.forward_reasoning")

_ALLOWED_CONSTRAINT_TYPES = frozenset(
    {
        "slow_pacing",
        "avoid_topic",
        "witness_not_advise",
        "hold_space",
        "reduce_intensity",
    }
)

_FORBIDDEN_PHRASES = (
    "diagnosis",
    "diagnose",
    "you have ",
    "disorder",
    "icd-",
    "prognosis",
)


def forward_reasoning_enabled() -> bool:
    return os.getenv("ENABLE_FORWARD_REASONING", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _trial_excluded(profile: Optional[Dict[str, Any]]) -> bool:
    if not profile:
        return True
    tier = (profile.get("tier") or "").lower()
    pd = profile.get("profile_data") or {}
    if isinstance(pd, str):
        try:
            pd = json.loads(pd)
        except Exception:
            pd = {}
    if tier == "public_trial" or pd.get("public_trial") is True:
        return True
    return False


async def build_forward_constraints(
    db_pool: Any,
    *,
    username: Optional[str],
    hardware_id: Optional[str] = None,
    state_symbol: Optional[Dict[str, Any]] = None,
    nevedal_snapshot: Optional[Dict[str, Any]] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Returns list of {type, instruction, fired_by} constraint dicts for prompt injection.
    """
    if not forward_reasoning_enabled():
        return []
    if _trial_excluded(profile):
        return []
    if not username and not hardware_id:
        return []

    constraints: List[Dict[str, Any]] = []
    state = state_symbol or {}

    if state.get("distress_present"):
        constraints.append(
            {
                "type": "slow_pacing",
                "instruction": "Use shorter sentences and slower pacing; prioritize witnessing over advice.",
                "fired_by": ["StateSymbol.distress_present"],
            }
        )
        constraints.append(
            {
                "type": "witness_not_advise",
                "instruction": "Reflect and witness; avoid prescriptive homework unless the client asks.",
                "fired_by": ["StateSymbol.distress_present"],
            }
        )

    snapshot = nevedal_snapshot or {}
    if snapshot:
        c_emo = snapshot.get("c_emo")
        trend = (snapshot.get("c_emo_trend") or "").lower()
        if trend == "declining" or (c_emo is not None and float(c_emo) < 0.35):
            constraints.append(
                {
                    "type": "hold_space",
                    "instruction": "Coherence is low — hold space; do not push insight or celebration.",
                    "fired_by": ["nevedal_metrics.c_emo_trend"],
                }
            )
        shame = snapshot.get("shame_index")
        if shame is not None and float(shame) > 0.6:
            constraints.append(
                {
                    "type": "reduce_intensity",
                    "instruction": "Shame markers elevated — soften directness; avoid shame-intensifying language.",
                    "fired_by": ["nevedal_metrics.shame_index"],
                }
            )

    if db_pool and (username or hardware_id):
        try:
            async with db_pool.acquire() as conn:
                # QUANTUM-CRYSTAL-ARCH — resolve to users.id (UUID); biometrics jsonb
                uid = await conn.fetchval(
                    """
                    SELECT id FROM users
                    WHERE username = $1 OR hardware_id = $1
                       OR username = $2 OR hardware_id = $2
                    LIMIT 1
                    """,
                    username or hardware_id,
                    hardware_id or username,
                )
                row = None
                if uid:
                    row = await conn.fetchrow(
                        """
                        SELECT c_emo, biometrics
                        FROM nevedal_metrics
                        WHERE user_id = $1
                        ORDER BY recorded_at DESC NULLS LAST
                        LIMIT 1
                        """,
                        uid,
                    )
            if row and row["biometrics"]:
                mj = row["biometrics"]
                if isinstance(mj, str):
                    mj = json.loads(mj)
                crisis = (mj or {}).get("crisis_perception") or {}
                if crisis.get("type") in ("acute", "elevated"):
                    constraints.append(
                        {
                            "type": "slow_pacing",
                            "instruction": "Crisis-perception signals present — prioritize safety and grounding.",
                            "fired_by": ["nevedal_metrics.crisis_perception"],
                        }
                    )
        except Exception as e:
            logger.warning("forward_reasoning: metrics load failed: %s", e)

    return _sanitize_constraints(constraints)


def _sanitize_constraints(constraints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clean: List[Dict[str, Any]] = []
    for c in constraints:
        ctype = c.get("type")
        instr = (c.get("instruction") or "").strip()
        if ctype not in _ALLOWED_CONSTRAINT_TYPES:
            continue
        lower = instr.lower()
        if any(p in lower for p in _FORBIDDEN_PHRASES):
            continue
        clean.append(
            {
                "type": ctype,
                "instruction": instr,
                "fired_by": list(c.get("fired_by") or []),
            }
        )
    return clean


def format_constraints_for_prompt(constraints: List[Dict[str, Any]]) -> str:
    if not constraints:
        return ""
    lines = ["FORWARD REASONING CONSTRAINTS (pacing/focus only — no clinical labels):"]
    for c in constraints:
        fired = ", ".join(c.get("fired_by") or [])
        lines.append(f"- [{c['type']}] {c['instruction']} (fired_by: {fired})")
    return "\n".join(lines)
