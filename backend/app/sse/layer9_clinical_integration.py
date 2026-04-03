"""SSE Stage 7 — Layer 9 Clinical Integration.

Therapeutic consistency validation, clinical pacing suggestions,
and delivery outcome learning loop.
"""
from __future__ import annotations

import logging
import math
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_PACING = {
    "truth_telling": 7,
    "parts_work": 21,
    "exile_access": 21,
    "descent": 14,
    "confrontation": 14,
    "integration": 21,
    "identity_consolidation": 21,
    "surrender": 14,
    "leap": 14,
}


async def review_story_clinical_consistency(
    story_plot: dict, db_pool
) -> dict[str, Any]:
    """Review story for clinical consistency using crystal history."""
    from app.sse.layer6_crystal_bridge import validate_therapeutic_consistency

    result = await validate_therapeutic_consistency(story_plot, db_pool)

    if result["flags"] and db_pool:
        sid = story_plot.get("storyboard_id", story_plot.get("id", ""))
        try:
            async with db_pool.acquire() as c:
                for f in result["flags"]:
                    await c.execute(
                        "INSERT INTO sse_clinical_review_log "
                        "(review_id,storyboard_id,phase_id,concern,recommendation) "
                        "VALUES($1,$2,$3,$4,$5)",
                        str(uuid.uuid4()), sid, f["phase_id"],
                        f["concern"], f["recommendation"],
                    )
        except Exception as e:
            logger.warning("clinical_integration: log failed: %s", e)

    return result


async def suggest_clinical_pacing(
    story_plot: dict, therapeutic_modalities: list | None = None
) -> dict[str, Any]:
    """Pure function — recommend minimum days per phase based on therapeutic action."""
    panels = story_plot.get("panels", [])
    doc_type = story_plot.get("document_type", "")
    multiplier = 1.5 if doc_type == "theological_workbook" else 1.0

    pacing: list[dict[str, Any]] = []
    total = 0

    for panel in panels:
        action = (panel.get("therapeutic_action", "") or "").lower().strip()
        base_days = _PACING.get(action, 7)
        days = int(math.ceil(base_days * multiplier))
        phase_id = panel.get("phase_id", panel.get("id", ""))
        phase_name = panel.get("phase_name", panel.get("title", phase_id))

        pacing.append({
            "phase_id": phase_id,
            "phase_name": phase_name,
            "recommended_days": days,
        })
        total += days

    modality_note = ""
    if therapeutic_modalities:
        modality_note = f" Modalities: {', '.join(therapeutic_modalities)}."

    notes = (
        f"Estimated {total} days across {len(pacing)} phases."
        f"{modality_note}"
        f"{' Theological multiplier (1.5x) applied.' if multiplier > 1 else ''}"
    )

    return {
        "recommended_pacing": pacing,
        "total_estimated_days": total,
        "pacing_notes": notes.strip(),
    }


async def record_delivery_outcome(
    storyboard_id: str, user_id: str, phase_id: str, outcome: str, db_pool
) -> None:
    """Learning loop — record delivery outcomes, crystallize on phase completion."""
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as c:
            await c.execute(
                "INSERT INTO sse_delivery_outcomes "
                "(outcome_id,storyboard_id,user_id,phase_id,outcome) "
                "VALUES($1,$2,$3,$4,$5)",
                str(uuid.uuid4()), storyboard_id, user_id, phase_id, outcome,
            )
    except Exception as e:
        logger.warning("clinical_integration: outcome log failed: %s", e)

    if outcome == "completed_phase":
        try:
            from app.sse.layer6_crystal_bridge import crystallize_panel_delivery
            await crystallize_panel_delivery(
                user_id, phase_id, f"Phase completed: {phase_id}", db_pool
            )
        except Exception as e:
            logger.warning("clinical_integration: crystallize failed: %s", e)
