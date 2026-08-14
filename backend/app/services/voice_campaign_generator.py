"""Coach voice-campaign copy → marketing_content review queue. No publishers."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from app.services.google_workspace_service import FlagOff

REVIEW = "pending_review"
ALLOWED_CAMPAIGN_TYPES = frozenset({"linkedin_post", "drip_touch", "newsletter_issue"})


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


def compose_day_n_pieces(title: str, day_n: int = 0) -> List[Dict[str, str]]:
    title = (title or "Campaign").strip()
    pieces = [
        {
            "content_type": "linkedin_post",
            "title": f"{title} — LinkedIn day {day_n}",
            "draft_body": f"{title}: invite a conversation. Day {day_n}.",
            "platform": "linkedin",
        },
        {
            "content_type": "drip_touch",
            "title": f"{title} — drip day {day_n}",
            "draft_body": f"Follow-up touch for {title} (day {day_n}).",
            "platform": "email",
        },
    ]
    if _flag_on("ENABLE_COACH_NEWSLETTER"):
        pieces.append(
            {
                "content_type": "newsletter_issue",
                "title": f"{title} — newsletter day {day_n}",
                "draft_body": f"Newsletter draft for {title} (day {day_n}).",
                "platform": "email",
            }
        )
    return pieces


async def generate_campaign(
    db_pool,
    coach_id: str,
    *,
    title: str,
    day_n: int = 0,
    pieces: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    if not _flag_on("ENABLE_VOICE_CAMPAIGN"):
        raise FlagOff("ENABLE_VOICE_CAMPAIGN")
    coach_id = (coach_id or "").strip()
    if not coach_id:
        raise ValueError("coach_id (hardware_id) required")
    pieces = pieces or compose_day_n_pieces(title, day_n)
    content_ids: List[int] = []
    campaign_id = None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO coach_marketing_campaigns (coach_id, title, status, day_n)
            VALUES ($1, $2, 'draft', $3)
            RETURNING id
            """,
            coach_id,
            title,
            int(day_n),
        )
        campaign_id = row["id"]
        for p in pieces:
            ctype = (p.get("content_type") or "").strip()
            if ctype not in ALLOWED_CAMPAIGN_TYPES:
                continue
            if ctype == "newsletter_issue" and not _flag_on("ENABLE_COACH_NEWSLETTER"):
                continue
            crow = await conn.fetchrow(
                """
                INSERT INTO marketing_content (
                    content_type, platform, audience, title, draft_body, status,
                    generation_meta, created_by, campaign_id, coach_id
                ) VALUES (
                    $1, $2, 'general', $3, $4, $5,
                    $6::jsonb, $7, $8, $9
                )
                RETURNING id
                """,
                ctype,
                p.get("platform") or ctype,
                p.get("title") or title,
                p.get("draft_body") or "",
                REVIEW,
                json.dumps({"source": "voice_campaign_generator", "day_n": day_n}),
                "voice_campaign_generator",
                campaign_id,
                coach_id,
            )
            content_ids.append(int(crow["id"]))
        await conn.execute(
            """
            UPDATE coach_marketing_campaigns
            SET status = 'in_review', updated_at = NOW()
            WHERE id = $1
            """,
            campaign_id,
        )
    newsletter_titles = [
        (p.get("title") or title)
        for p in pieces
        if (p.get("content_type") or "") == "newsletter_issue"
    ]
    if newsletter_titles and _flag_on("ENABLE_COACH_NEWSLETTER"):
        from app.services.newsletter_service import record_topics, stamp_source_crystal

        await record_topics(db_pool, newsletter_titles, domain="marketing")
        await stamp_source_crystal(
            db_pool, text=f"Newsletter: {title}", domain="marketing"
        )
    return {
        "ok": True,
        "campaign_id": str(campaign_id),
        "content_ids": content_ids,
        "status": REVIEW,
        "published": False,
    }


async def list_review_queue(db_pool, coach_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    coach_id = (coach_id or "").strip()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, content_type, status, campaign_id, coach_id, post_urn,
                   LEFT(draft_body, 2000) AS draft_body,
                   hero_image_prompt, hero_image_url, hero_image_generated_at
            FROM marketing_content
            WHERE coach_id = $1 AND status = $2
            ORDER BY id DESC
            LIMIT $3
            """,
            coach_id,
            REVIEW,
            int(limit),
        )
    from app.services.coach_campaign_editor import serialize_item

    return [serialize_item(r) for r in rows]


async def list_approved_unpublished(db_pool, coach_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    coach_id = (coach_id or "").strip()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, content_type, status, campaign_id, coach_id, post_urn,
                   LEFT(draft_body, 2000) AS draft_body,
                   hero_image_prompt, hero_image_url, hero_image_generated_at
            FROM marketing_content
            WHERE coach_id = $1 AND status = 'approved' AND COALESCE(post_urn, '') = ''
            ORDER BY id DESC
            LIMIT $2
            """,
            coach_id,
            int(limit),
        )
    from app.services.coach_campaign_editor import serialize_item

    return [serialize_item(r) for r in rows]


async def set_review_status(
    db_pool,
    content_id: int,
    *,
    coach_id: str,
    status: str,
) -> Dict[str, Any]:
    """Approve/reject only. Never published and never writes post_urn (Seam 5)."""
    if status not in ("approved", "rejected"):
        raise ValueError("status must be approved or rejected")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE marketing_content
            SET status = $1, updated_at = NOW()
            WHERE id = $2 AND coach_id = $3 AND status = $4
              AND COALESCE(post_urn, '') = ''
            RETURNING id, status, post_urn
            """,
            status,
            int(content_id),
            coach_id,
            REVIEW,
        )
    if not row:
        return {"ok": False, "reason": "not_in_queue"}
    return {"ok": True, "id": int(row["id"]), "status": row["status"], "published": False}
