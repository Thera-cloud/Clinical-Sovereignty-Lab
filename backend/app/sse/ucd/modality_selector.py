"""Modality Selector — picks output format based on TMC class + engagement + deployment context.

Implements the Modality Safety Matrix (S2) inline: certain moment-modality
combinations are prohibited, and institutional deployments restrict video.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

ALLOWED_MODALITIES = {
    "THRESHOLD": ["panel", "text_reflection", "audio_narrative"],
    "BREAKTHROUGH": ["panel", "video", "composite"],
    "INTEGRATION": ["panel", "text_reflection", "guided_meditation"],
    "RECURRENCE": ["panel", "audio_narrative", "text_reflection"],
    "REST": ["panel", "text_reflection", "guided_meditation"],
    "CRISIS": ["text_reflection", "audio_narrative"],
    "HERITAGE": ["panel", "video", "composite"],
}

FORBIDDEN_PAIRS: set[tuple[str, str]] = {
    ("CRISIS", "video"),
    ("CRISIS", "composite"),
    ("CRISIS", "panel"),
    ("REST", "video"),
}

INSTITUTIONAL_BLOCKED_MODALITIES = {"video", "composite"}


class ModalitySelector:
    """Select the best modality for a classified moment."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def select(
        self,
        user_id: str,
        moment_class: str,
        deployment_context: str = "private",
        engagement_history: Optional[list[dict]] = None,
        additional_blocked: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Return the selected modality with reasoning."""
        allowed = list(ALLOWED_MODALITIES.get(moment_class, ["panel"]))

        blocked_reasons = []
        for modality in list(allowed):
            if (moment_class, modality) in FORBIDDEN_PAIRS:
                allowed.remove(modality)
                blocked_reasons.append(
                    f"{modality} blocked: forbidden pair ({moment_class}, {modality})"
                )

            if deployment_context == "institutional" and modality in INSTITUTIONAL_BLOCKED_MODALITIES:
                if modality in allowed:
                    allowed.remove(modality)
                    blocked_reasons.append(
                        f"{modality} blocked: institutional deployment"
                    )

        if additional_blocked:
            for modality in list(allowed):
                if modality in additional_blocked:
                    allowed.remove(modality)
                    blocked_reasons.append(
                        f"{modality} blocked: safety gate restriction"
                    )

        if not allowed:
            allowed = ["text_reflection"]
            blocked_reasons.append("all modalities blocked; falling back to text_reflection")

        if engagement_history:
            preferred = self._rank_by_engagement(allowed, engagement_history)
        else:
            preferred = allowed[0]

        return {
            "selected_modality": preferred,
            "allowed": allowed,
            "blocked_reasons": blocked_reasons,
            "deployment_context": deployment_context,
        }

    def _rank_by_engagement(
        self, allowed: list[str], history: list[dict]
    ) -> str:
        """Prefer modalities with higher past engagement rates."""
        modality_scores: dict[str, float] = {}
        engagement_values = {
            "discussed": 1.0,
            "viewed": 0.6,
            "skipped": 0.1,
            "ignored": 0.0,
        }

        for entry in history:
            mod = entry.get("generation_type") or entry.get("modality")
            action = entry.get("engagement_action")
            if mod and action:
                score = engagement_values.get(action, 0.3)
                modality_scores[mod] = modality_scores.get(mod, 0.0) + score

        best = allowed[0]
        best_score = -1.0
        for mod in allowed:
            s = modality_scores.get(mod, 0.0)
            if s > best_score:
                best_score = s
                best = mod

        return best

    async def get_engagement_history(
        self, user_id: str, limit: int = 50
    ) -> list[dict]:
        """Fetch recent engagement data from generation log."""
        if not self.db_pool:
            return []
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT generation_type, engagement_action, moment_class, "
                    "generated_at FROM sse_delivery_generation_log "
                    "WHERE user_id = $1 AND engagement_action IS NOT NULL "
                    "ORDER BY generated_at DESC LIMIT $2",
                    user_id, limit,
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("Engagement history fetch failed: %s", e)
            return []
