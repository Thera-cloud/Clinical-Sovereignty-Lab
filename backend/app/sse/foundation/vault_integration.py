"""SSE Vault Integration — Sovereign Journey folder.

Registers SSE panels/clips/recaps into the Sovereign Vault
under a per-user "Sovereign Journey" folder. Handles 19-day
retention with push-to-photos before deletion.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_FOLDER_NAME = "Sovereign Journey"
_FOLDER_ICON = "🌿"
_FOLDER_COLOR = "#00E5A0"
_RETENTION_DAYS = 19
_GRACE_HOURS = 48


async def ensure_journey_folder(user_id: str, db_pool) -> str:
    """Get or create the Sovereign Journey vault folder for a user."""
    async with db_pool.acquire() as c:
        existing = await c.fetchval(
            "SELECT id FROM vault_folders WHERE member_id=$1 AND name=$2",
            user_id, _FOLDER_NAME)
        if existing:
            return str(existing)

        folder_id = str(uuid.uuid4())
        await c.execute(
            "INSERT INTO vault_folders (id, member_id, name, icon, color, is_system) "
            "VALUES ($1::uuid, $2, $3, $4, $5, true) "
            "ON CONFLICT DO NOTHING",
            folder_id, user_id, _FOLDER_NAME, _FOLDER_ICON, _FOLDER_COLOR)
        return folder_id


async def register_panel_in_vault(
    user_id: str, r2_url: str, phase_id: str, storyboard_id: str,
    generation_type: str, panel_tone: str, db_pool
) -> str:
    """Register a delivered panel/clip/recap as a vault item."""
    folder_id = await ensure_journey_folder(user_id, db_pool)
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(days=_RETENTION_DAYS)).isoformat()

    is_video = generation_type in ("weekly_clip", "monthly_recap")
    ext = "mp4" if is_video else "png"
    mime = "video/mp4" if is_video else "image/png"
    today = now.strftime("%Y-%m-%d")
    filename = f"{storyboard_id}_{phase_id}_{today}.{ext}"

    item_id = str(uuid.uuid4())
    import json
    meta = json.dumps({
        "phase_id": phase_id,
        "storyboard_id": storyboard_id,
        "generation_type": generation_type,
        "panel_tone": panel_tone,
        "delivered_at": now.isoformat(),
        "expires_at": expires,
        "category": "SSE Panel",
    })

    async with db_pool.acquire() as c:
        await c.execute(
            "INSERT INTO vault_items "
            "(id, member_id, folder_id, content_type, filename, display_name, "
            " blob_path, mime_type, dimensions) "
            "VALUES ($1::uuid, $2, $3::uuid, $4, $5, $6, $7, $8, $9::jsonb)",
            item_id, user_id, folder_id, "sse_panel", filename,
            f"{generation_type}: {phase_id}", r2_url, mime, meta)

        await c.execute(
            "UPDATE vault_folders SET item_count = item_count + 1 WHERE id = $1::uuid",
            folder_id)

    return item_id


async def process_expired_panels(db_pool) -> dict[str, Any]:
    """19-day retention: flag for push-to-photos, then delete after grace period."""
    flagged = deleted = 0
    now = datetime.now(timezone.utc)
    grace_cutoff = (now - timedelta(hours=_GRACE_HOURS)).isoformat()

    async with db_pool.acquire() as c:
        to_flag = await c.fetch(
            "SELECT id, dimensions FROM vault_items "
            "WHERE content_type = 'sse_panel' "
            "AND dimensions->>'expires_at' < $1 "
            "AND dimensions->>'push_to_photos_requested' IS NULL",
            now.isoformat())

        for row in to_flag:
            import json
            meta = json.loads(row["dimensions"]) if isinstance(row["dimensions"], str) else dict(row["dimensions"])
            meta["push_to_photos_requested"] = True
            meta["push_requested_at"] = now.isoformat()
            await c.execute(
                "UPDATE vault_items SET dimensions = $1::jsonb WHERE id = $2",
                json.dumps(meta), row["id"])
            flagged += 1

        to_delete = await c.fetch(
            "SELECT id, folder_id FROM vault_items "
            "WHERE content_type = 'sse_panel' "
            "AND dimensions->>'push_to_photos_requested' = 'true' "
            "AND dimensions->>'push_requested_at' < $1",
            grace_cutoff)

        for row in to_delete:
            await c.execute("DELETE FROM vault_items WHERE id = $1", row["id"])
            if row["folder_id"]:
                await c.execute(
                    "UPDATE vault_folders SET item_count = GREATEST(item_count - 1, 0) "
                    "WHERE id = $1", row["folder_id"])
            deleted += 1

    return {"flagged_for_push": flagged, "deleted": deleted}
