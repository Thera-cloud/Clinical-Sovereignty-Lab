"""Narrative Coherence Enforcer (NCE) — ensures generation continuity.

Reads the NSO and the last N generations to build a coherence context
block that is injected into generation prompts. The NCE prevents:
  - Contradicting established character arcs
  - Repeating identical imagery or metaphors
  - Referencing elements the user hasn't encountered yet
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_MAX_RECENT_GENS = 10


class NarrativeCoherenceEnforcer:
    """Build coherence context for generation prompts."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def build_coherence_context(
        self,
        user_id: str,
        nso: Optional[dict] = None,
    ) -> str:
        """Return a text block summarizing narrative state for prompt injection."""
        parts = []

        if nso:
            state = nso.get("state", {})
            arc_stage = state.get("arc_stage")
            emotional_theme = state.get("emotional_theme")
            recent_metaphors = state.get("recent_metaphors", [])
            character_threads = state.get("character_threads", [])

            if arc_stage:
                parts.append(f"Current arc stage: {arc_stage}")
            if emotional_theme:
                parts.append(f"Emotional theme: {emotional_theme}")
            if recent_metaphors:
                parts.append(f"Recently used metaphors (DO NOT repeat): {', '.join(recent_metaphors[-5:])}")
            if character_threads:
                parts.append(f"Active character threads: {', '.join(character_threads[-5:])}")

        recent = await self._get_recent_generations(user_id)
        if recent:
            summaries = []
            for gen in recent:
                gen_type = gen.get("generation_type", "unknown")
                moment = gen.get("moment_class", "")
                prompt_snip = (gen.get("prompt_used") or "")[:80]
                summaries.append(f"  - [{gen_type}/{moment}] {prompt_snip}")
            parts.append("Recent generations (maintain continuity):\n" + "\n".join(summaries))

        if not parts:
            return "[COHERENCE CONTEXT: No prior narrative state. Begin fresh.]"

        return "[COHERENCE CONTEXT]\n" + "\n".join(parts)

    async def _get_recent_generations(self, user_id: str) -> list[dict]:
        if not self.db_pool:
            return []
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT generation_type, moment_class, prompt_used, generated_at "
                    "FROM sse_delivery_generation_log "
                    "WHERE user_id = $1 "
                    "ORDER BY generated_at DESC LIMIT $2",
                    user_id, _MAX_RECENT_GENS,
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("NCE recent gen fetch failed: %s", e)
            return []

    async def update_nso_after_generation(
        self,
        user_id: str,
        generation_result: dict,
        write_nso_fn,
    ) -> None:
        """Push new metaphors and arc updates into the NSO after a generation."""
        updates = {}
        new_metaphors = generation_result.get("metaphors_used", [])
        if new_metaphors:
            updates["recent_metaphors_append"] = new_metaphors

        new_arc_stage = generation_result.get("arc_stage_transition")
        if new_arc_stage:
            updates["arc_stage"] = new_arc_stage

        if updates:
            try:
                await write_nso_fn(
                    user_id,
                    updates,
                    generation_id=generation_result.get("generation_id"),
                    reason="nce_post_generation",
                )
            except Exception as e:
                logger.warning("NCE NSO update failed: %s", e)
