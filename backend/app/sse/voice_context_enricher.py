"""Voice Context Enricher — fetches SSE identity for voice sessions."""

import logging

logger = logging.getLogger(__name__)


async def get_voice_story_context(user_id: str, db_pool) -> dict:
    """Fetch SSE story context to enrich voice session prompts."""
    ctx: dict = {
        "archetype": None,
        "biome": None,
        "active_quest": None,
        "active_mission": None,
        "last_panel_summary": None,
    }
    if not user_id or not db_pool:
        return ctx
    ids = [user_id]
    try:
        async with db_pool.acquire() as conn:
            j = await conn.fetchrow(
                "SELECT current_biome, dominant_character FROM sse_user_journeys "
                "WHERE user_id = ANY($1) LIMIT 1", ids)
            if j:
                ctx["biome"] = j["current_biome"]
                ctx["archetype"] = j["dominant_character"]
            q = await conn.fetchval(
                "SELECT goal FROM sse_quests WHERE user_id = ANY($1) "
                "AND status='active' ORDER BY created_at DESC LIMIT 1", ids)
            if q:
                ctx["active_quest"] = q
            m = await conn.fetchval(
                "SELECT relationship_target FROM sse_missions WHERE user_id = ANY($1) "
                "AND status='active' ORDER BY created_at DESC LIMIT 1", ids)
            if m:
                ctx["active_mission"] = m
            p = await conn.fetchval(
                "SELECT narrative_text FROM sse_panel_log WHERE user_id = ANY($1) "
                "ORDER BY generated_at DESC LIMIT 1", ids)
            if p:
                ctx["last_panel_summary"] = p[:200]
    except Exception as e:
        logger.warning("voice_context_enricher: %s", e)
    return ctx
