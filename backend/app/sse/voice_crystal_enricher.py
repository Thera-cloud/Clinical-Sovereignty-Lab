"""Voice Crystal Enricher — tags crystals from voice sessions with session metadata."""

import json
import logging

logger = logging.getLogger(__name__)

_VOICE_CONFIDENCE_BOOST = 1.1


async def enrich_crystals_from_voice(
    session_call_sid: str, username: str, duration_s: float, db_pool
) -> dict:
    """After a voice session, boost confidence and tag crystals created during the call."""
    if not username or not db_pool or duration_s < 10:
        return {"enriched": 0}

    duration_min = round(duration_s / 60, 1)
    enriched = 0

    try:
        async with db_pool.acquire() as conn:
            # Crystals forged in the last N minutes (call duration + 2 min buffer)
            window_min = int(duration_min) + 2
            rows = await conn.fetch(
                "SELECT crystal_id, confidence FROM nate_intelligence_crystals "
                "WHERE (user_id = (SELECT id FROM users WHERE username=$1 LIMIT 1) "
                "       OR user_id IS NULL) "
                "AND created_at > NOW() - make_interval(mins => $2) "
                "AND (scope != 'archived' OR scope IS NULL) "
                "ORDER BY created_at DESC LIMIT 50",
                username, window_min)

            for row in rows:
                new_conf = min(0.95, row["confidence"] * _VOICE_CONFIDENCE_BOOST)
                meta = json.dumps({"source": "voice", "session_duration_min": duration_min,
                                   "call_sid": session_call_sid})
                await conn.execute(
                    "UPDATE nate_intelligence_crystals "
                    "SET confidence = $1, "
                    "    crystal_text = crystal_text || E'\\n[voice session: ' || $2 || ' min]' "
                    "WHERE crystal_id = $3",
                    new_conf, str(duration_min), row["crystal_id"])
                enriched += 1

            # Store a voice session summary for story context
            await conn.execute(
                "INSERT INTO family_shared_events (family_id, event_type, event_data) "
                "VALUES ('voice_sessions', 'voice_session_summary', $1::jsonb)",
                json.dumps({"username": username, "call_sid": session_call_sid,
                            "duration_min": duration_min, "crystals_enriched": enriched}))
    except Exception as e:
        logger.warning("voice_crystal_enricher: %s", e)

    logger.info("voice_crystal_enricher: enriched %d crystals for %s (%s min)",
                enriched, username, duration_min)
    return {"enriched": enriched, "duration_min": duration_min}
