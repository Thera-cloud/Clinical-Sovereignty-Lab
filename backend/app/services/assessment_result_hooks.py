"""
Post-save hooks for assessments — PG row + wisdom lifecycle (additive).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def schedule_assessment_completion_side_effects(
    db_pool,
    user_id: str,
    assessment_type: str,
    scores_0_100: Dict[str, Any],
    result_summary: str,
) -> None:
    """
    Persist to assessment_results and queue wisdom extraction (assessment source).
    Safe to call from REST; wisdom runs in a background task.
    """
    if not db_pool or not user_id:
        return

    try:
        from app.sse.adapters.assessment_bridge import AssessmentBridge

        canonical = AssessmentBridge.canonical_scores_from_dimensions(scores_0_100)
        scores_blob = {
            "dimensions_0_100": scores_0_100,
            "canonical_0_10": canonical,
        }
    except Exception as e:
        logger.warning("assessment hook canonical scores: %s", e)
        scores_blob = {"dimensions_0_100": scores_0_100 or {}}

    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO assessment_results (
                    user_id, assessment_type, scores, result_summary, status, completed_at
                ) VALUES ($1, $2, $3::jsonb, $4, 'completed', NOW())
                """,
                user_id.strip(),
                (assessment_type or "assessment")[:256],
                json.dumps(scores_blob),
                (result_summary or "")[:8000],
            )
    except Exception as e:
        logger.warning("assessment_results insert failed: %s", e)
        return

    content = (
        f"Assessment: {assessment_type}\n"
        f"{result_summary}\n"
        f"Scores: {json.dumps(scores_blob, default=str)[:4000]}"
    )

    async def _wisdom() -> None:
        try:
            from app.services.wisdom_lifecycle_manager import WisdomLifecycleManager

            wl = WisdomLifecycleManager(db_pool, None)
            await wl.extract_wisdom(
                "assessment",
                content,
                user_id=None,
                domain="clinical",
                confidence=0.55,
            )
        except Exception as ex:
            logger.debug("assessment wisdom extract: %s", ex)

    try:
        asyncio.get_running_loop().create_task(_wisdom())
    except RuntimeError:
        logger.debug("assessment wisdom: no running loop")
