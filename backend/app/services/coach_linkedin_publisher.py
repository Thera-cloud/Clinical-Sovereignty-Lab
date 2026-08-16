"""Per-coach LinkedIn publish. Isolated from SkyEye token rows."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from app.services.google_workspace_service import FlagOff

UGC_URL = "https://api.linkedin.com/v2/ugcPosts"
REGISTER_UPLOAD_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


async def load_coach_linkedin_token(db_pool, coach_id: str) -> Optional[str]:
    if not db_pool:
        return None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT access_token FROM coach_linkedin_connection
            WHERE coach_id = $1 AND revoked_at IS NULL
            """,
            coach_id,
        )
    if not row:
        return None
    from app.services.skyeye_platform_base import TokenCipher
    return TokenCipher.get().decrypt(row["access_token"])


def _ugc_headers(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _audio_publish_on() -> bool:
    raw = os.getenv("ENABLE_COACH_LINKEDIN_AUDIO", "").strip().lower()
    if raw in ("0", "false", "no"):
        return False
    if raw in ("1", "true", "yes"):
        return True
    return _flag_on("ENABLE_COACH_LINKEDIN")


async def linkedin_ugc_post(
    access_token: str,
    person_urn: str,
    text: str,
    *,
    media_urn: str = "",
) -> Optional[str]:
    import aiohttp

    share: Dict[str, Any] = {
        "shareCommentary": {"text": text[:3000]},
        "shareMediaCategory": "NONE",
    }
    if media_urn:
        share = {
            "shareCommentary": {"text": text[:3000]},
            "shareMediaCategory": "VIDEO",
            "media": [
                {
                    "status": "READY",
                    "description": {"text": text[:200]},
                    "media": media_urn,
                    "title": {"text": "Campaign audio"},
                }
            ],
        }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            UGC_URL,
            headers=_ugc_headers(access_token),
            json={
                "author": person_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {"com.linkedin.ugc.ShareContent": share},
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            },
        ) as resp:
            if resp.status not in (200, 201):
                return None
            data = await resp.json(content_type=None)
            return data.get("id")


async def linkedin_upload_video(
    access_token: str,
    person_urn: str,
    mp4: bytes,
) -> Optional[str]:
    if not mp4 or not person_urn:
        return None
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.post(
            REGISTER_UPLOAD_URL,
            headers=_ugc_headers(access_token),
            json={
                "registerUploadRequest": {
                    "owner": person_urn,
                    "recipes": ["urn:li:digitalmediaRecipe:feedshare-video"],
                    "serviceRelationships": [
                        {
                            "identifier": "urn:li:userGeneratedContent",
                            "relationshipType": "OWNER",
                        }
                    ],
                }
            },
        ) as resp:
            if resp.status not in (200, 201):
                return None
            data = await resp.json(content_type=None)
        value = (data or {}).get("value") or {}
        asset = value.get("asset") or ""
        mech = (value.get("uploadMechanism") or {}).get(
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
        ) or {}
        upload_url = mech.get("uploadUrl") or ""
        if not asset or not upload_url:
            return None
        async with session.put(
            upload_url,
            headers={"Authorization": f"Bearer {access_token}"},
            data=mp4,
        ) as put:
            if put.status not in (200, 201, 204):
                return None
        return asset


async def publish_approved_post(
    db_pool,
    *,
    coach_id: str,
    content_id: int,
    include_audio: bool = False,
) -> Dict[str, Any]:
    if not _flag_on("ENABLE_COACH_LINKEDIN"):
        raise FlagOff("ENABLE_COACH_LINKEDIN")
    coach_id = (coach_id or "").strip()
    token = await load_coach_linkedin_token(db_pool, coach_id)
    if not token:
        return {
            "ok": False,
            "reason": "connect_linkedin",
            "status": "approved",
            "published": False,
        }
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT mc.id, mc.title, mc.draft_body, mc.status, mc.content_type, li.person_urn
            FROM marketing_content mc
            LEFT JOIN coach_linkedin_connection li ON li.coach_id = mc.coach_id
            WHERE mc.id = $1 AND mc.coach_id = $2
            """,
            int(content_id),
            coach_id,
        )
    if not row or row["status"] != "approved" or row["content_type"] != "linkedin_post":
        return {"ok": False, "reason": "not_approved_linkedin_post"}
    body = row["draft_body"] or row["title"] or ""
    media_urn = ""
    audio_provider = ""
    if include_audio and _audio_publish_on():
        try:
            from app.services.coach_campaign_clone import synthesize_campaign, wrap_audio_as_mp4
            from app.services.coach_voice_profile_service import load_profile_and_transcript

            style, _ = await load_profile_and_transcript(db_pool, coach_id)
            audio, audio_provider = await synthesize_campaign(body, coach_id, style=style)
            mp4 = wrap_audio_as_mp4(audio) if audio else None
            if mp4:
                media_urn = await linkedin_upload_video(token, row["person_urn"] or "", mp4) or ""
        except Exception:
            media_urn = ""
    urn = await linkedin_ugc_post(
        token, row["person_urn"] or "", body, media_urn=media_urn
    )
    if not urn:
        return {
            "ok": False,
            "reason": "linkedin_api",
            "published": False,
            "status": "approved",
            "audio_provider": audio_provider,
        }
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE marketing_content
            SET status = 'published', post_urn = $1, published_at = NOW(), updated_at = NOW()
            WHERE id = $2 AND coach_id = $3
            """,
            urn,
            int(content_id),
            coach_id,
        )
        if _flag_on("ENABLE_CAMPAIGN_NUDGES"):
            await conn.execute(
                """
                INSERT INTO post_nudges (coach_id, content_id, channel, sent_at)
                VALUES ($1, $2, 'linkedin', NOW())
                """,
                coach_id,
                int(content_id),
            )
    return {
        "ok": True,
        "published": True,
        "post_urn": urn,
        "audio": bool(media_urn),
        "audio_provider": audio_provider,
    }
