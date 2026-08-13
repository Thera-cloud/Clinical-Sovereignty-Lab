"""Per-coach LinkedIn publish. Isolated from SkyEye token rows."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from app.services.google_workspace_service import FlagOff

UGC_URL = "https://api.linkedin.com/v2/ugcPosts"


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


async def linkedin_ugc_post(access_token: str, person_urn: str, text: str) -> Optional[str]:
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.post(
            UGC_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            json={
                "author": person_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": text[:3000]},
                        "shareMediaCategory": "NONE",
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            },
        ) as resp:
            if resp.status not in (200, 201):
                return None
            data = await resp.json(content_type=None)
            return data.get("id")


async def publish_approved_post(
    db_pool,
    *,
    coach_id: str,
    content_id: int,
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
    urn = await linkedin_ugc_post(token, row["person_urn"] or "", row["draft_body"] or row["title"] or "")
    if not urn:
        return {"ok": False, "reason": "linkedin_api", "published": False, "status": "approved"}
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
    return {"ok": True, "published": True, "post_urn": urn}
