"""Group LoRA Folder Manager — compile, sync, and serve group LoRA sets.

compile_group_lora_folder: called at group creation or membership change
sync_group_lora_folder: called when an individual member's LoRA is retrained
get_group_lora_folder: single entry point for video generation
on_member_lora_updated: hook called after any member LoRA training completes

R2 verification of LoRA paths happens here (not in lora_resolver.py).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.sse.adapters.lora_resolver import get_lora_ref

logger = logging.getLogger(__name__)


async def compile_group_lora_folder(
    group_entity_id: str,
    db_pool,
) -> Optional[str]:
    """Build the complete LoRA folder for a group from scratch.

    Queries all active members, resolves each member's LoRA ref,
    stores snapshots in group_entity_members, and updates the
    group's lora_folder_path.

    Returns the group lora_folder_path or None on failure.
    """
    folder_path = f"groups/{group_entity_id}/lora/"
    updated = 0

    try:
        async with db_pool.acquire() as conn:
            members = await conn.fetch(
                "SELECT id, client_id FROM group_entity_members "
                "WHERE group_entity_id = $1 AND is_active = TRUE",
                group_entity_id)

            for m in members:
                ref = await get_lora_ref(str(m["client_id"]), db_pool)
                if ref:
                    await conn.execute(
                        "UPDATE group_entity_members SET lora_snapshot_path = $1 "
                        "WHERE id = $2",
                        ref, m["id"])
                    updated += 1
                else:
                    logger.warning(
                        "[GROUP_LORA] Member %s has no LoRA — excluded from group %s",
                        m["client_id"], group_entity_id)

            await conn.execute(
                "UPDATE group_entities SET lora_folder_path = $1, updated_at = NOW() "
                "WHERE group_entity_id = $2",
                folder_path, group_entity_id)

        logger.info(
            "[GROUP_LORA] Compiled folder for group %s: %d/%d members have LoRA",
            group_entity_id, updated, len(members))
        return folder_path

    except Exception as e:
        logger.error("[GROUP_LORA] compile failed for group %s: %s", group_entity_id, e)
        return None


async def sync_group_lora_folder(
    group_entity_id: str,
    db_pool,
) -> int:
    """Incremental sync — only update members whose LoRA changed.

    Compares current replicate_model_ref against stored lora_snapshot_path.
    Returns count of members updated.
    """
    synced = 0
    try:
        async with db_pool.acquire() as conn:
            members = await conn.fetch(
                "SELECT id, client_id, lora_snapshot_path FROM group_entity_members "
                "WHERE group_entity_id = $1 AND is_active = TRUE",
                group_entity_id)

            for m in members:
                current_ref = await get_lora_ref(str(m["client_id"]), db_pool)
                if not current_ref:
                    continue
                if current_ref != m["lora_snapshot_path"]:
                    await conn.execute(
                        "UPDATE group_entity_members SET lora_snapshot_path = $1 "
                        "WHERE id = $2",
                        current_ref, m["id"])
                    synced += 1

            if synced > 0:
                await conn.execute(
                    "UPDATE group_entities SET updated_at = NOW() "
                    "WHERE group_entity_id = $1",
                    group_entity_id)

        if synced:
            logger.info("[GROUP_LORA] Synced %d member(s) in group %s", synced, group_entity_id)
        return synced

    except Exception as e:
        logger.error("[GROUP_LORA] sync failed for group %s: %s", group_entity_id, e)
        return 0


async def get_group_lora_folder(
    group_entity_id: str,
    db_pool,
    active_client_ids: list[str] | None = None,
    background_client_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return LoRA entries for all active members in a group.

    Returns list of {"client_id": str, "lora_url": str, "lora_scale": float}
    where lora_scale = 0.85 for active_members, 0.5 for background_members.

    If the folder is stale (no lora_folder_path), triggers compile first.
    """
    active_set = set(active_client_ids or [])
    bg_set = set(background_client_ids or [])

    try:
        async with db_pool.acquire() as conn:
            folder = await conn.fetchval(
                "SELECT lora_folder_path FROM group_entities "
                "WHERE group_entity_id = $1", group_entity_id)

            if not folder:
                await compile_group_lora_folder(group_entity_id, db_pool)

            members = await conn.fetch(
                "SELECT client_id, lora_snapshot_path FROM group_entity_members "
                "WHERE group_entity_id = $1 AND is_active = TRUE "
                "AND lora_snapshot_path IS NOT NULL",
                group_entity_id)

        result: list[dict[str, Any]] = []
        for m in members:
            cid = str(m["client_id"])
            if cid in active_set:
                scale = 0.85
            elif cid in bg_set:
                scale = 0.5
            else:
                scale = 0.65
            result.append({
                "client_id": cid,
                "lora_url": m["lora_snapshot_path"],
                "lora_scale": scale,
            })

        return result

    except Exception as e:
        logger.error("[GROUP_LORA] get_folder failed for group %s: %s", group_entity_id, e)
        return []


async def on_member_lora_updated(
    user_id: str,
    db_pool,
) -> None:
    """Hook: called when a member's LoRA training completes.

    Finds all groups this user belongs to and triggers incremental sync.
    """
    try:
        async with db_pool.acquire() as conn:
            groups = await conn.fetch(
                "SELECT group_entity_id FROM group_entity_members "
                "WHERE client_id = $1::uuid AND is_active = TRUE",
                user_id)

        if not groups:
            return

        for g in groups:
            gid = str(g["group_entity_id"])
            synced = await sync_group_lora_folder(gid, db_pool)
            if synced:
                logger.info(
                    "[GROUP_LORA] Auto-synced group %s after LoRA update for user %s",
                    gid, user_id)

    except Exception as e:
        logger.warning("[GROUP_LORA] on_member_lora_updated failed for %s: %s", user_id, e)
