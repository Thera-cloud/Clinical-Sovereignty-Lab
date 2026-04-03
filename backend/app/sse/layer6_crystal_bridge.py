"""SSE Stage 7 — Layer 6 Crystal Bridge.

Bridge between SSE delivery pipeline and Little Nate's crystal memory system.
Calls existing functions in crystal_recall_bridge.py directly.
"""
from __future__ import annotations

import logging
from typing import Any

from app.websocket.crystal_recall_bridge import (
    recall_crystals_for_context,
    crystallize_from_conversation,
)

logger = logging.getLogger(__name__)

_CRISIS_KEYWORDS = {"crisis", "shutdown", "dissociation", "suicidal", "self-harm", "destabilized"}
_CONFRONT_KEYWORDS = {"confrontation", "descent", "exposure", "provocation"}


async def get_user_crystals_for_panel(
    user_id: str, phase: str, db_pool
) -> list[dict[str, Any]]:
    """Recall crystals relevant to a story phase for panel prompt enrichment."""
    try:
        raw = await recall_crystals_for_context(
            db_pool=db_pool,
            hardware_id=user_id,
            max_results=5,
            source="sse_panel_generation",
            query_text=phase,
        )
    except Exception as e:
        logger.warning("layer6_crystal_bridge: recall failed for %s: %s", user_id, e)
        return []
    if not raw or not raw.strip():
        return []
    return [{"summary": line.strip()} for line in raw.strip().split("\n") if line.strip()]


async def crystallize_panel_delivery(
    user_id: str, panel_description: str, delivery_note: str, db_pool
) -> None:
    """Record a panel delivery as a crystal so Nate remembers story content sent."""
    try:
        await crystallize_from_conversation(
            db_pool=db_pool,
            hardware_id=user_id,
            user_text=panel_description,
            nate_response=delivery_note,
            domain="sse_story",
            origin_surface="sse_delivery",
        )
    except Exception as e:
        logger.warning("layer6_crystal_bridge: crystallize failed for %s: %s", user_id, e)


async def validate_therapeutic_consistency(
    story_plot: dict, db_pool
) -> dict[str, Any]:
    """Check story phases against user crystals for therapeutic contradictions."""
    flags: list[dict[str, str]] = []
    panels = story_plot.get("panels", [])
    reviewed = 0

    for panel in panels:
        phase_id = panel.get("phase_id", panel.get("id", ""))
        scene = panel.get("scene_description", "")
        action = (panel.get("therapeutic_action", "") or "").lower()
        if not scene:
            continue
        reviewed += 1

        try:
            raw = await recall_crystals_for_context(
                db_pool=db_pool,
                hardware_id=story_plot.get("user_id", ""),
                max_results=3,
                source="sse_clinical_review",
                query_text=scene,
            )
        except Exception:
            continue

        if not raw:
            continue

        crystal_lower = raw.lower()
        has_crisis = any(kw in crystal_lower for kw in _CRISIS_KEYWORDS)
        has_confront = any(kw in action for kw in _CONFRONT_KEYWORDS)

        if has_crisis and has_confront:
            flags.append({
                "phase_id": phase_id,
                "concern": "Crisis/shutdown indicators in crystal history conflict with "
                           f"therapeutic_action '{action}'",
                "recommendation": "Consider delaying this phase or substituting a "
                                  "stabilization-focused panel sequence",
            })

    return {"consistent": len(flags) == 0, "flags": flags, "reviewed_phases": reviewed}
