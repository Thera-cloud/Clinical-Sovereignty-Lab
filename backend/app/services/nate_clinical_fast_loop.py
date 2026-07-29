"""QUANTUM-CRYSTAL-ARCH — Hidden clinical scratchpad (heuristic-first on live).

Live: no extra LLM. Offline bakeoff may call LLM separately.
Shadow default: log only; never mutate client-visible reply unless shadow=false
and κ gate satisfied (caller enforces κ).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Mapping, Optional

from app.services.nate_clinical_flags import (
    fast_loop_enabled,
    fast_loop_shadow,
    modality_router_enabled,
)
from app.services.nate_modality_router import modality_addendum, route_modality

logger = logging.getLogger("nate.clinical_fast_loop")

_RUT_RE = re.compile(
    r"\b(same thing|every time|stuck|going in circles|nothing (works|helps))\b",
    re.I,
)
_RESIST_RE = re.compile(
    r"\b(you don'?t (get|understand)|this is pointless|whatever|"
    r"i already tried)\b",
    re.I,
)


def clinical_reflection_scratchpad(
    turn_ctx: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    """Heuristic pivot directive. Returns None when fast-loop off or no signal."""
    if not fast_loop_enabled():
        return None

    user_text = str(turn_ctx.get("user_text") or "")
    profile = turn_ctx.get("profile") if isinstance(turn_ctx.get("profile"), dict) else {}
    distress = float(turn_ctx.get("distress_hint") or 0.0)

    decision = None
    if modality_router_enabled():
        decision = route_modality(user_text, profile=profile, distress_hint=distress)

    pivot = None
    if _RESIST_RE.search(user_text):
        pivot = "validate_resistance_then_soften_pace"
    elif _RUT_RE.search(user_text):
        pivot = "name_cycle_offer_one_concrete_shift"
    elif decision and decision.source == "crisis":
        pivot = "crisis_safety_protocol"

    if not pivot and not decision:
        return None

    directive: Dict[str, Any] = {
        "pivot": pivot,
        "modality": decision.modality if decision else None,
        "tactic": decision.tactic if decision else None,
        "source": decision.source if decision else "heuristic",
        "shadow": fast_loop_shadow(),
        "addendum": "",
    }
    if decision and not fast_loop_shadow():
        directive["addendum"] = modality_addendum(decision)
    elif decision and fast_loop_shadow():
        # Shadow: keep addendum empty so reply path unchanged; log only.
        directive["addendum"] = ""

    return directive


async def log_fast_loop_shadow(db_pool, user_id: str, directive: Dict[str, Any]) -> None:
    if not db_pool or not directive:
        return
    try:
        import json

        content = json.dumps(
            {"user_id": user_id, "directive": directive},
            default=str,
        )[:4000]
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO skyeye_activity (type, content, platform)
                VALUES ('nate_clinical_fast_loop', $1, 'clinical')
                """,
                content,
            )
    except Exception as e:
        logger.debug("fast_loop shadow log skipped: %s", e)
