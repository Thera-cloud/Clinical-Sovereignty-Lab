"""Coach voice-campaign copy → marketing_content review queue. No publishers."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.services.google_workspace_service import FlagOff

logger = logging.getLogger("voice_campaign_generator")

REVIEW = "pending_review"
ALLOWED_CAMPAIGN_TYPES = frozenset({"linkedin_post", "drip_touch", "newsletter_issue"})
ALLOWED_AUDIENCES = frozenset({"clients", "assistant_coaches"})
MAX_DAYS = 36


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


def _body_hash(text: str) -> str:
    norm = " ".join((text or "").lower().split())
    return hashlib.sha256(norm.encode()).hexdigest()


def _audience_brief(audience: str, profile: Optional[Dict[str, Any]] = None) -> str:
    profile = profile or {}
    if audience == "assistant_coaches":
        stance = (
            profile.get("assistant_stance")
            or profile.get("stance")
            or "encourage without diagnosing"
        )
        return (
            "Audience: assistant coaches. Training and encouragement. "
            f"Coach assistant stance: {stance}. "
            "No client clinical material. No diagnosis."
        )
    return (
        "Audience: clients. Clinical warmth, invitation, steadiness. "
        "No diagnosis. No assistant-coach training language."
    )


async def _safe_body(body: str, fallback: str) -> str:
    try:
        from app.services.nate_response_validator import NateResponseValidator

        _cleaned, warnings = await NateResponseValidator().validate(body or "", {})
        if any("hallucination_pattern" in w or "unverified" in w for w in (warnings or [])):
            return fallback
    except Exception as exc:
        logger.warning("campaign copy validator skipped: %s", exc)
    return body or fallback


async def coach_is_master(db_pool, coach_id: str) -> bool:
    if not db_pool:
        return False
    async with db_pool.acquire() as conn:
        n = await conn.fetchval(
            """
            SELECT COUNT(*) FROM coach_hierarchy
            WHERE master_coach_id = $1 AND status = 'active'
            """,
            coach_id,
        )
    return int(n or 0) > 0


async def _ln_day_pieces(
    title: str,
    day_n: int,
    length_days: int,
    audience: str,
    profile: Dict[str, Any],
    transcript: str,
    prior: List[str],
    crystal_ctx: str = "",
) -> Optional[List[Dict[str, str]]]:
    try:
        from app.services.nate_inference_router import NateInferenceRouter

        router = NateInferenceRouter()
        from app.services.coach_voice_biometrics import style_presence_block

        style = json.dumps(profile or {})[:2200]
        presence = style_presence_block(profile)
        prior_block = "\n---\n".join(prior[-8:]) if prior else "(none)"
        types = ["linkedin_post", "drip_touch"]
        if _flag_on("ENABLE_COACH_NEWSLETTER"):
            types.append("newsletter_issue")
        result = await router.generate(
            prompt=(
                f"Campaign title: {title}\nDay {day_n} of {length_days}.\n"
                f"{_audience_brief(audience, profile)}\n"
                f"{presence}\n"
                f"Coach style JSON: {style}\n"
                f"Interview excerpt (tone only, do not quote at length):\n{(transcript or '')[:2500]}\n"
                f"Coach interview crystals:\n{(crystal_ctx or '')[:1500]}\n"
                f"Already written (do not repeat):\n{prior_block}\n"
                f"Return JSON array of {len(types)} objects with content_type, title, draft_body, platform. "
                f"content_type must be one of {list(types)}. Each draft_body unique for this day."
            ),
            system="Return a JSON array only. No markdown.",
            domain="clinical" if audience == "clients" else "coaching",
            max_tokens=1200,
            temperature=0.3 if audience == "clients" else 0.5,
        )
        raw = ""
        if isinstance(result, dict):
            raw = (result.get("text") or result.get("content") or "").strip()
        elif isinstance(result, str):
            raw = result.strip()
        start, end = raw.find("["), raw.rfind("]")
        if start < 0 or end <= start:
            return None
        data = json.loads(raw[start : end + 1])
        if not isinstance(data, list):
            return None
        out: List[Dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            ctype = (item.get("content_type") or "").strip()
            if ctype not in ALLOWED_CAMPAIGN_TYPES:
                continue
            out.append(
                {
                    "content_type": ctype,
                    "title": (item.get("title") or f"{title} — {ctype} day {day_n}")[:240],
                    "draft_body": (item.get("draft_body") or "").strip(),
                    "platform": item.get("platform") or ("linkedin" if ctype == "linkedin_post" else "email"),
                }
            )
        return out or None
    except Exception as exc:
        logger.warning("campaign LN day compose failed: %s", exc)
        return None


def _vary_stub(title: str, day_n: int, transcript: str, audience: str) -> List[Dict[str, str]]:
    slice_at = max(0, (day_n - 1) * 40)
    hint = " ".join((transcript or title).split()[slice_at : slice_at + 12]) or title
    window = "clients" if audience == "clients" else "assistants"
    pieces = compose_day_n_pieces(title, day_n)
    for p in pieces:
        p["draft_body"] = f"{p['draft_body']} [{window} · {hint}]"
    return pieces


async def generate_campaign(
    db_pool,
    coach_id: str,
    *,
    title: str,
    day_n: int = 0,
    pieces: Optional[List[Dict[str, str]]] = None,
    length_days: int = 1,
    audience: str = "clients",
) -> Dict[str, Any]:
    if not _flag_on("ENABLE_VOICE_CAMPAIGN"):
        raise FlagOff("ENABLE_VOICE_CAMPAIGN")
    coach_id = (coach_id or "").strip()
    if not coach_id:
        raise ValueError("coach_id (hardware_id) required")
    audience = (audience or "clients").strip()
    if audience not in ALLOWED_AUDIENCES:
        raise ValueError("audience must be clients or assistant_coaches")
    if audience == "assistant_coaches" and not await coach_is_master(db_pool, coach_id):
        raise PermissionError("assistant_coaches window requires master coach")
    days = max(1, min(MAX_DAYS, int(length_days or 1)))

    profile: Dict[str, Any] = {}
    transcript = ""
    crystal_ctx = ""
    if pieces is None:
        try:
            from app.services.coach_voice_profile_service import load_profile_and_transcript

            profile, transcript = await load_profile_and_transcript(db_pool, coach_id)
        except Exception as exc:
            logger.warning("campaign profile load skipped: %s", exc)
        try:
            from app.websocket.crystal_recall_bridge import recall_crystals_for_context

            crystal_ctx = await recall_crystals_for_context(
                db_pool, coach_id, max_results=4, source="coach_voice_interview"
            ) or ""
        except Exception as exc:
            logger.warning("campaign crystal recall skipped: %s", exc)

    content_ids: List[int] = []
    campaign_id = None
    seen: set[str] = set()
    now = datetime.now(timezone.utc)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO coach_marketing_campaigns
              (coach_id, title, status, day_n, length_days, audience)
            VALUES ($1, $2, 'draft', $3, $4, $5)
            RETURNING id
            """,
            coach_id,
            title,
            int(day_n) or 1,
            days,
            audience,
        )
        campaign_id = row["id"]
        prior: List[str] = []
        for d in range(1, days + 1):
            if pieces is not None and d == 1:
                day_pieces = pieces
            elif pieces is not None:
                break
            elif profile or transcript:
                day_pieces = await _ln_day_pieces(
                    title, d, days, audience, profile, transcript, prior, crystal_ctx
                ) or _vary_stub(title, d, transcript, audience)
            else:
                day_pieces = compose_day_n_pieces(title, d if days > 1 else day_n)
            sched = now + timedelta(days=d - 1)
            for p in day_pieces:
                ctype = (p.get("content_type") or "").strip()
                if ctype not in ALLOWED_CAMPAIGN_TYPES:
                    continue
                if ctype == "newsletter_issue" and not _flag_on("ENABLE_COACH_NEWSLETTER"):
                    continue
                stub = _vary_stub(title, d, transcript, audience)
                stub_body = next(
                    (s.get("draft_body") or "" for s in stub if s.get("content_type") == ctype),
                    f"{title} day {d}",
                )
                body = await _safe_body((p.get("draft_body") or "").strip(), stub_body)
                h = _body_hash(body)
                if h in seen:
                    body = f"{body} (day {d} · {audience})"
                    h = _body_hash(body)
                if h in seen:
                    continue
                seen.add(h)
                prior.append(body[:400])
                crow = await conn.fetchrow(
                    """
                    INSERT INTO marketing_content (
                        content_type, platform, audience, title, draft_body, status,
                        generation_meta, created_by, campaign_id, coach_id, scheduled_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6,
                        $7::jsonb, $8, $9, $10, $11
                    )
                    RETURNING id
                    """,
                    ctype,
                    p.get("platform") or ctype,
                    audience,
                    p.get("title") or title,
                    body,
                    REVIEW,
                    json.dumps(
                        {
                            "source": "voice_campaign_generator",
                            "day_n": d if days > 1 else day_n,
                            "audience": audience,
                            "length_days": days,
                            "body_hash": h,
                        }
                    ),
                    "voice_campaign_generator",
                    campaign_id,
                    coach_id,
                    sched,
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
        for p in (pieces or [])
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
        "length_days": days,
        "audience": audience,
    }


async def list_review_queue(db_pool, coach_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    coach_id = (coach_id or "").strip()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, content_type, status, campaign_id, coach_id, post_urn,
                   audience, scheduled_at, generation_meta,
                   LEFT(draft_body, 2000) AS draft_body,
                   hero_image_prompt, hero_image_url, hero_image_generated_at
            FROM marketing_content
            WHERE coach_id = $1 AND status = $2
            ORDER BY scheduled_at ASC NULLS LAST, id DESC
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
                   audience, scheduled_at, generation_meta,
                   LEFT(draft_body, 2000) AS draft_body,
                   hero_image_prompt, hero_image_url, hero_image_generated_at
            FROM marketing_content
            WHERE coach_id = $1 AND status = 'approved' AND COALESCE(post_urn, '') = ''
            ORDER BY scheduled_at ASC NULLS LAST, id DESC
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
            RETURNING id, status, post_urn, title, draft_body, audience
            """,
            status,
            int(content_id),
            coach_id,
            REVIEW,
        )
    if not row:
        return {"ok": False, "reason": "not_in_queue"}
    if status == "approved":
        try:
            from app.services.coach_voice_profile_service import crystallize_approved_draft

            await crystallize_approved_draft(
                db_pool,
                coach_id,
                row.get("title") or "",
                row.get("draft_body") or "",
                row.get("audience") or "clients",
            )
        except Exception as exc:
            logger.warning("approved-draft crystallize skipped: %s", exc)
    return {"ok": True, "id": int(row["id"]), "status": row["status"], "published": False}
