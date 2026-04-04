"""SSE Intake Session — backend handler for the 10-turn Identity Forge conversation.

Called by the Flutter IntakeConversationScreen via POST /api/sse/intake/turn.
"""
from __future__ import annotations

import json, logging
from app.sse.layer1_identity_forge import get_intake_prompt, extract_intake_data

logger = logging.getLogger(__name__)

_CLOSING = (
    "Thank you for sharing that with me, {name}. I hear you. "
    "I know where to begin with you now. Your journey starts tomorrow. "
    "I'll be with you every step."
)


async def process_intake_turn(
    user_id: str, user_name: str, turn: int,
    user_message: str, conversation_history: list, db_pool
) -> dict:
    """Process a single intake turn. Returns the next prompt or extraction result."""
    conversation_history.append({"role": "user", "content": user_message})

    if turn < 10:
        next_prompt = get_intake_prompt(turn + 1, user_name)
        conversation_history.append({"role": "assistant", "content": next_prompt})
        return {
            "turn": turn + 1,
            "nate_message": next_prompt,
            "complete": False,
            "conversation_history": conversation_history,
        }

    intake_data = await extract_intake_data(conversation_history, db_pool, user_id)
    closing = _CLOSING.replace("{name}", user_name)
    try:
        # Validate recommended storyboard against approved storyboards in DB
        raw_rec = (intake_data or {}).get("recommended_storyboard", "")
        approved = []
        try:
            async with db_pool.acquire() as vc:
                approved = [r["storyboard_id"] for r in await vc.fetch(
                    "SELECT DISTINCT storyboard_id FROM sse_delivery_config WHERE status = 'active'"
                )]
        except Exception:
            pass
        # Try exact match first, then fuzzy match on keywords
        storyboard = "you_can_walk_in_it_beloved"  # default fallback
        if raw_rec in approved:
            storyboard = raw_rec
        else:
            for sid in approved:
                if any(w in raw_rec.lower() for w in sid.replace("_", " ").split() if len(w) > 3):
                    storyboard = sid
                    break
        async with db_pool.acquire() as c:
            await c.execute(
                "INSERT INTO sse_enrolled_users (enrollment_id, user_id, storyboard_id) "
                "VALUES (gen_random_uuid(), $1, $2) "
                "ON CONFLICT (user_id, storyboard_id) DO NOTHING",
                user_id, storyboard)
        logger.info("SSE intake complete: enrolled %s in %s", user_id, storyboard)
    except Exception as e:
        logger.warning("SSE enrollment insert failed for %s: %s", user_id, e)
    return {
        "turn": 10,
        "nate_message": closing,
        "complete": True,
        "intake_data": intake_data,
        "archetype_image_url": (intake_data or {}).get("archetype_image_url"),
        "conversation_history": conversation_history,
    }


async def get_intake_status(user_id: str, db_pool) -> dict:
    """Check if a user has completed intake."""
    async with db_pool.acquire() as c:
        row = await c.fetchrow(
            "SELECT character_visual,cultural_context,spiritual_framework,"
            "archetype_hint,presenting_concern,wound_indicator,strength_indicator,"
            "recommended_storyboard,clinical_eligibility_estimate,safety_flags,"
            "language_notes,status,completed_at "
            "FROM sse_identity_forge WHERE user_id=$1", user_id)
    if not row or row["status"] != "complete":
        return {"completed": False, "intake_data": None}
    return {
        "completed": True,
        "intake_data": {
            "character_visual": row["character_visual"],
            "cultural_context": row["cultural_context"],
            "spiritual_framework": row["spiritual_framework"],
            "archetype_hint": row["archetype_hint"],
            "presenting_concern": row["presenting_concern"],
            "wound_indicator": row["wound_indicator"],
            "strength_indicator": row["strength_indicator"],
            "recommended_storyboard": row["recommended_storyboard"],
            "clinical_eligibility_estimate": row["clinical_eligibility_estimate"],
            "safety_flags": json.loads(row["safety_flags"]) if row["safety_flags"] else [],
            "language_notes": row["language_notes"],
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        },
    }
