"""BLE Co-Traveler Detection — creates anonymous proximity events for family members.

Also auto-enrolls BLE proximity pairs into group_entities for group video generation.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def process_proximity_event(user1_id: str, user2_id: str, db_pool) -> dict:
    """Record that two family members were detected in BLE proximity."""
    if not user1_id or not user2_id or user1_id == user2_id:
        return {"recorded": False, "reason": "invalid_ids"}

    async with db_pool.acquire() as conn:
        fam1 = await conn.fetchval(
            "SELECT family_id FROM family_members WHERE user_id = $1 LIMIT 1", user1_id)
        fam2 = await conn.fetchval(
            "SELECT family_id FROM family_members WHERE user_id = $1 LIMIT 1", user2_id)

        if not fam1 or not fam2 or fam1 != fam2:
            return {"recorded": False, "reason": "not_same_family"}

        # Dedup: skip if a co_traveler event already exists for this pair today
        existing = await conn.fetchval(
            "SELECT 1 FROM family_shared_events WHERE family_id = $1 "
            "AND event_type = 'co_traveler' AND created_at > CURRENT_DATE "
            "AND (event_data->>'user1' = $2 OR event_data->>'user2' = $2) LIMIT 1",
            fam1, user1_id)
        if existing:
            return {"recorded": False, "reason": "already_recorded_today"}

        await conn.execute(
            "INSERT INTO family_shared_events (family_id, event_type, event_data) "
            "VALUES ($1, 'co_traveler', $2::jsonb)",
            fam1, json.dumps({
                "user1": user1_id, "user2": user2_id,
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }))

    logger.info("co_traveler: proximity recorded %s <-> %s (family %s)", user1_id, user2_id, fam1)
    asyncio.create_task(_ensure_group_entity(fam1, user1_id, user2_id, db_pool))
    return {"recorded": True, "family_id": fam1}


async def get_co_traveler_prompt_addition(user_id: str, db_pool) -> str:
    """Return an image prompt addition if a co-traveler event exists in the last 24h."""
    if not user_id or not db_pool:
        return ""
    try:
        async with db_pool.acquire() as conn:
            fam_id = await conn.fetchval(
                "SELECT family_id FROM family_members WHERE user_id = $1 LIMIT 1", user_id)
            if not fam_id:
                return ""
            hit = await conn.fetchval(
                "SELECT 1 FROM family_shared_events WHERE family_id = $1 "
                "AND event_type = 'co_traveler' "
                "AND created_at > NOW() - INTERVAL '24 hours' "
                "AND (event_data->>'user1' = $2 OR event_data->>'user2' = $2) LIMIT 1",
                fam_id, user_id)
            if hit:
                return "In the distance, another figure walks the same path — a familiar presence nearby.\n"
    except Exception as e:
        logger.warning("co_traveler prompt check: %s", e)
    return ""


async def _ensure_group_entity(family_id: str, user1: str, user2: str, db_pool) -> None:
    """Auto-enroll BLE proximity pair into group_entities for group video."""
    try:
        async with db_pool.acquire() as conn:
            ge_id = await conn.fetchval(
                "SELECT group_entity_id FROM families WHERE family_id = $1",
                family_id)

            if not ge_id:
                ge_id = await conn.fetchval(
                    "INSERT INTO group_entities (group_type, group_name, scene_context) "
                    "VALUES ('ble_proximity', $1, 'ble_proximity') "
                    "RETURNING group_entity_id",
                    f"BLE Family {family_id[:8]}")
                await conn.execute(
                    "UPDATE families SET group_entity_id = $1 WHERE family_id = $2",
                    ge_id, family_id)

            for uid in (user1, user2):
                await conn.execute(
                    "INSERT INTO group_entity_members (group_entity_id, client_id) "
                    "VALUES ($1, $2::uuid) ON CONFLICT (group_entity_id, client_id) DO NOTHING",
                    ge_id, uid)

        from app.sse.adapters.group_lora_manager import compile_group_lora_folder
        asyncio.create_task(compile_group_lora_folder(str(ge_id), db_pool))

    except Exception as e:
        logger.warning("BLE group entity enrollment failed: %s", e)
