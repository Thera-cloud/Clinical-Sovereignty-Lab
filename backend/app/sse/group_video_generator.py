"""Group Video Generator — monthly group videos for families, corporate, etc.

Flow: load context → generate composite image (Replicate + multi-LoRA)
→ animate to video (Grok) → store in R2 → deliver to all members.

4-LoRA CAP: Replicate Flux supports max 4 LoRAs per call. Active members
get priority (by session count desc), then background. Members beyond the
cap are described in the text prompt only and logged as text-only.

Staging composite images are RETAINED at
groups/{group_entity_id}/staging/{year}-{month:02d}-composite.png
for debugging failed video jobs.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import aiohttp

from app.sse.adapters.group_lora_manager import get_group_lora_folder, sync_group_lora_folder
from app.sse.adapters.participation_tracker import get_group_participation
from app.sse.infrastructure import grok_imagine_client as grok, r2_storage
from app.sse.infrastructure import replicate_client as replicate

logger = logging.getLogger(__name__)

_SCENE_PROMPTS: dict[str, str] = {
    "family_sanctuary": "warm family gathering in a magical sanctuary garden, golden hour light, intimate and nurturing atmosphere",
    "corporate_wellness": "professional wellness retreat in a modern sunlit atrium, energetic and collaborative",
    "therapy_circle": "supportive therapy circle in a cozy room with soft lighting, grounded and hopeful",
    "rehabilitation_space": "dignified recovery space with calm natural light, peaceful and calm",
    "ble_proximity": "friends gathered in a shared communal space, warm and connected",
}

_DURATION_HINTS: dict[str, str] = {
    "family": "warm, intimate, 60 second cinematic",
    "corporate": "energetic, forward-looking, 45 second cinematic",
    "therapy_group": "grounded, hopeful, 45 second cinematic",
    "aa_meeting": "grounded, hopeful, 45 second cinematic",
    "rehab": "dignified, calm, 45 second cinematic",
    "prison": "dignified, calm, 45 second cinematic",
    "student": "energetic, forward-looking, 45 second cinematic",
    "ble_proximity": "warm, connected, 45 second cinematic",
}

_MAX_LORA = 4
_IMG_COST = 0.04
_VID_COST = 0.25


async def _poll_video(vid_id: str) -> dict:
    backoff = 5
    for _ in range(15):
        await asyncio.sleep(backoff)
        r = await grok.poll_video_status(vid_id)
        if r["status"] != "processing":
            return r
        backoff = min(backoff * 2, 60)
    return {"status": "timeout", "url": None}


async def generate_monthly_group_video(
    group_entity_id: str,
    month: int,
    year: int,
    db_pool,
) -> dict[str, Any]:
    """Generate the monthly group video. Single entry point.

    Returns dict with video_url, status, cost, and member details.
    """
    gen_id = str(uuid.uuid4())
    result: dict[str, Any] = {
        "group_entity_id": group_entity_id,
        "month": month, "year": year,
        "status": "pending", "cost": 0.0,
    }

    try:
        async with db_pool.acquire() as conn:
            group = await conn.fetchrow(
                "SELECT group_type, group_name, scene_context "
                "FROM group_entities WHERE group_entity_id = $1",
                group_entity_id)

        if not group:
            result["status"] = "failed"
            result["error"] = "Group entity not found"
            return result

        group_type = group["group_type"]
        scene_ctx = group["scene_context"] or group_type
        group_name = group["group_name"] or "Group"

        participation = await get_group_participation(
            group_entity_id, month, year, db_pool)
        active_ids = participation["active_members"]
        bg_ids = participation["background_members"]

        lora_entries = await get_group_lora_folder(
            group_entity_id, db_pool,
            active_client_ids=active_ids,
            background_client_ids=bg_ids)

        if not lora_entries:
            result["status"] = "skipped"
            result["error"] = "No members with active LoRA"
            await _log_group_video(db_pool, group_entity_id, month, year,
                                   None, None, "skipped", "No members with LoRA")
            return result

        lora_entries.sort(key=lambda x: (-x["lora_scale"], x["client_id"]))
        lora_for_api = lora_entries[:_MAX_LORA]
        text_only = lora_entries[_MAX_LORA:]

        if text_only:
            text_only_ids = [e["client_id"] for e in text_only]
            logger.info(
                "[GROUP_VIDEO] 4-LoRA cap: %d members text-only for group %s: %s",
                len(text_only_ids), group_entity_id, text_only_ids)

        lora_urls = [e["lora_url"] for e in lora_for_api]
        lora_scales = [e["lora_scale"] for e in lora_for_api]

        scene_base = _SCENE_PROMPTS.get(scene_ctx, f"group scene, {scene_ctx}")
        active_count = len(active_ids)
        bg_count = len(bg_ids)
        text_only_desc = ""
        if text_only:
            text_only_desc = (
                f", plus {len(text_only)} additional people visible "
                "in the midground as supporting presence")

        prompt = (
            f"{scene_base}. {active_count} people in the foreground "
            f"actively engaged, {bg_count} people in the midground "
            f"present and visible{text_only_desc}. "
            f"All characters clearly visible throughout the scene. "
            f"{group_name} monthly gathering."
        )

        composite_imgs = await replicate.generate_with_loras(
            prompt, lora_urls=lora_urls, lora_scales=lora_scales)

        if not composite_imgs:
            raise RuntimeError("Replicate returned no images for group composite")

        composite_url_remote = composite_imgs[0]
        cost = _IMG_COST
        logger.info("[COST] group_video composite %s: $%.4f (replicate)", group_entity_id, _IMG_COST)

        staging_key = f"groups/{group_entity_id}/staging/{year}-{month:02d}-composite.png"
        async with aiohttp.ClientSession() as sess:
            async with sess.get(composite_url_remote) as resp:
                img_bytes = await resp.read()
        staging_r2_url = await r2_storage.store_image(img_bytes, staging_key)

        duration_hint = _DURATION_HINTS.get(group_type, "cinematic, 45 second")
        video_prompt = f"{prompt} {duration_hint} animation"

        vid_id = await grok.generate_video(video_prompt, staging_r2_url)
        r = await _poll_video(vid_id)

        if r["status"] == "completed" and r.get("url"):
            video_key = f"groups/{group_entity_id}/videos/{year}-{month:02d}-monthly.mp4"
            video_url = await r2_storage.store_video(r["url"], video_key)
            cost += _VID_COST
            logger.info("[COST] group_video total %s: $%.4f", group_entity_id, cost)

            await _log_group_video(
                db_pool, group_entity_id, month, year,
                video_url, staging_r2_url, "success", None)

            result["status"] = "success"
            result["video_url"] = video_url
            result["composite_url"] = staging_r2_url
            result["cost"] = cost
            result["lora_members"] = len(lora_for_api)
            result["text_only_members"] = len(text_only)
        else:
            raise RuntimeError(f"Video generation {r['status']}")

    except Exception as e:
        logger.error("[GROUP_VIDEO] Failed for group %s %d/%d: %s",
                     group_entity_id, month, year, e)
        result["status"] = "failed"
        result["error"] = str(e)[:500]
        await _log_group_video(
            db_pool, group_entity_id, month, year,
            None, result.get("composite_url"), "failed", str(e)[:500])

    return result


async def _log_group_video(
    db_pool,
    group_entity_id: str,
    month: int,
    year: int,
    video_url: str | None,
    composite_url: str | None,
    status: str,
    error_message: str | None,
) -> None:
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO group_videos "
                "(id, group_entity_id, month, year, video_url, composite_url, "
                " generated_at, status, error_message) "
                "VALUES ($1, $2, $3, $4, $5, $6, NOW(), $7, $8) "
                "ON CONFLICT (group_entity_id, month, year) DO UPDATE SET "
                "video_url = EXCLUDED.video_url, composite_url = EXCLUDED.composite_url, "
                "generated_at = EXCLUDED.generated_at, status = EXCLUDED.status, "
                "error_message = EXCLUDED.error_message",
                str(uuid.uuid4()), group_entity_id, month, year,
                video_url, composite_url, status, error_message)
    except Exception as e:
        logger.warning("[GROUP_VIDEO] Failed to log: %s", e)
