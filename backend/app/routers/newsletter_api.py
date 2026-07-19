"""Little Nate Dispatch public + admin API.

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field

from app.services.api_server import require_admin

logger = logging.getLogger("nate.newsletter_api")

router = APIRouter(prefix="/api/newsletter", tags=["newsletter"])
admin_router = APIRouter(
    prefix="/api/newsletter/admin",
    tags=["newsletter-admin"],
)

TOKEN_SALT = os.getenv("NEWSLETTER_TOKEN_SALT", "nate-dispatch")
# Dev/test: allow subscribe without Turnstile when explicitly enabled
ALLOW_OPEN_SUBSCRIBE = os.getenv("NEWSLETTER_ALLOW_OPEN_SUBSCRIBE", "false").strip().lower() in (
    "1",
    "true",
    "yes",
)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(f"{TOKEN_SALT}:{raw}".encode()).hexdigest()


def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    return pool


class SubscribeBody(BaseModel):
    email: EmailStr
    phone: Optional[str] = None
    research_consent: bool = False
    turnstile_token: Optional[str] = None
    source: Optional[str] = "web"
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    ref: Optional[str] = None


class FeedbackBody(BaseModel):
    reply_text: Optional[str] = Field(None, max_length=2000)
    liked: Optional[bool] = None


class UpdateIssueBody(BaseModel):
    subject_line: Optional[str] = Field(None, max_length=300)
    topic: Optional[str] = Field(None, max_length=300)
    opener: Optional[str] = Field(None, max_length=2000)
    body_md: Optional[str] = Field(None, max_length=50000)


class RewriteIssueBody(BaseModel):
    notes: Optional[str] = Field(None, max_length=2000)


def _row_json(row) -> Dict[str, Any]:
    from uuid import UUID

    d = dict(row)
    for k, v in list(d.items()):
        if isinstance(v, UUID):
            d[k] = str(v)
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


# ── Public ───────────────────────────────────────────────────────────


@router.get("/health")
async def health():
    return {"status": "ok", "service": "little_nate_dispatch"}


@router.post("/subscribe")
async def subscribe(body: SubscribeBody, request: Request):
    pool = _pool(request)
    # Rate limit by IP
    ip = request.client.host if request.client else "unknown"
    redis = getattr(request.app.state, "redis", None) or getattr(
        request.app.state, "cache_redis", None
    )
    if redis is not None:
        try:
            key = f"newsletter:sub_rl:{ip}"
            n = await redis.incr(key)
            if n == 1:
                await redis.expire(key, 3600)
            if n > 10:
                raise HTTPException(429, "Too many requests")
        except HTTPException:
            raise
        except Exception:
            pass

    if not ALLOW_OPEN_SUBSCRIBE:
        from app.services.turnstile import verify_turnstile

        ok = await verify_turnstile(body.turnstile_token or "", remote_ip=ip)
        if not ok:
            raise HTTPException(400, "Turnstile verification failed")

    email = body.email.strip().lower()
    raw_confirm = secrets.token_urlsafe(32)
    confirm_hash = _hash_token(raw_confirm)
    unsub_raw = secrets.token_urlsafe(24)
    unsub_hash = _hash_token(unsub_raw)
    expires = datetime.now(timezone.utc) + timedelta(hours=48)

    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id, status FROM newsletter_subscribers WHERE LOWER(email) = $1",
            email,
        )
        if existing and existing["status"] == "active":
            return {"status": "ok", "message": "If eligible, a confirmation was sent."}
        if existing and existing["status"] == "suppressed":
            return {"status": "ok", "message": "If eligible, a confirmation was sent."}

        await conn.execute(
            """
            INSERT INTO newsletter_subscribers (
                email, phone_e164, status, confirm_token_hash, confirm_token_expires_at,
                unsubscribe_token_hash, consent_research_at, consent_ip, consent_scope,
                source, utm_source, utm_medium, utm_campaign
            ) VALUES (
                $1, $2, 'pending', $3, $4, $5,
                CASE WHEN $6 THEN NOW() ELSE NULL END,
                $7, 'delivery',
                $8, $9, $10, $11
            )
            ON CONFLICT (email) DO UPDATE SET
                status = CASE
                    WHEN newsletter_subscribers.status = 'active' THEN newsletter_subscribers.status
                    ELSE 'pending'
                END,
                confirm_token_hash = EXCLUDED.confirm_token_hash,
                confirm_token_expires_at = EXCLUDED.confirm_token_expires_at,
                phone_e164 = COALESCE(EXCLUDED.phone_e164, newsletter_subscribers.phone_e164),
                consent_research_at = CASE
                    WHEN $6 THEN NOW()
                    ELSE newsletter_subscribers.consent_research_at
                END,
                updated_at = NOW()
            """,
            email,
            body.phone,
            confirm_hash,
            expires,
            unsub_hash,
            body.research_consent,
            ip,
            body.source,
            body.utm_source,
            body.utm_medium,
            body.utm_campaign,
        )

    await _send_confirm_email(email, raw_confirm)
    return {"status": "ok", "message": "If eligible, a confirmation was sent."}


async def _send_confirm_email(email: str, raw_token: str) -> None:
    api_key = os.getenv("SENDGRID_API_KEY", "").strip()
    if not api_key:
        logger.warning("confirm email skipped — no SENDGRID_API_KEY")
        return
    api_base = os.getenv("API_PUBLIC_BASE", "https://api.sovereignsanctuary.net").rstrip("/")
    url = f"{api_base}/api/newsletter/confirm?t={raw_token}"
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email, To, Content

        msg = Mail(
            from_email=Email(
                os.getenv("SENDGRID_FROM_EMAIL", "support@sovereignsanctuary.net"),
                "Little Nate Dispatch",
            ),
            to_emails=To(email),
            subject="Confirm your Little Nate Dispatch subscription",
            html_content=Content(
                "text/html",
                f"<p>Confirm your subscription to Little Nate Dispatch:</p>"
                f'<p><a href="{url}">Confirm email</a></p>'
                f"<p>This link expires in 48 hours.</p>",
            ),
        )
        SendGridAPIClient(api_key).send(msg)
    except Exception as e:
        logger.warning("confirm email failed: %s", e)


@router.get("/confirm")
async def confirm(request: Request, t: str = Query(...)):
    pool = _pool(request)
    th = _hash_token(t)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, confirm_token_expires_at FROM newsletter_subscribers
            WHERE confirm_token_hash = $1 AND status = 'pending'
            """,
            th,
        )
        if not row:
            return HTMLResponse(
                "<html><body><p>Link invalid or already used.</p></body></html>",
                status_code=400,
            )
        if row["confirm_token_expires_at"] and row["confirm_token_expires_at"] < datetime.now(
            timezone.utc
        ):
            return HTMLResponse(
                "<html><body><p>Link expired. Please subscribe again.</p></body></html>",
                status_code=400,
            )
        email = await conn.fetchval(
            "SELECT email FROM newsletter_subscribers WHERE id = $1", row["id"]
        )
        await conn.execute(
            """
            UPDATE newsletter_subscribers
            SET status = 'active', consent_delivery_at = NOW(),
                confirm_token_hash = NULL, confirm_token_expires_at = NULL,
                updated_at = NOW()
            WHERE id = $1
            """,
            row["id"],
        )
        channel = "direct"
        if email:
            wl = await conn.fetchval(
                """
                UPDATE newsletter_warm_leads
                SET status = 'converted', updated_at = NOW()
                WHERE LOWER(email) = LOWER($1) AND status IN ('pending', 'invited')
                RETURNING id
                """,
                email,
            )
            if wl:
                channel = "warm_lead"
        await conn.execute(
            """
            INSERT INTO newsletter_growth_ledger (day, channel, subscribers_gained, conversions)
            VALUES (CURRENT_DATE, $1, 1, $2)
            ON CONFLICT (day, channel) DO UPDATE
            SET subscribers_gained = newsletter_growth_ledger.subscribers_gained + 1,
                conversions = newsletter_growth_ledger.conversions + EXCLUDED.conversions
            """,
            channel,
            1 if channel == "warm_lead" else 0,
        )
    return HTMLResponse(
        "<html><body style='background:#050505;color:#C9A962;font-family:Georgia,serif;padding:40px;'>"
        "<h1>You're in.</h1><p>Little Nate Dispatch is confirmed.</p></body></html>"
    )


@router.get("/unsubscribe")
async def unsubscribe_get(
    request: Request,
    t: str = Query(...),
    sid: Optional[str] = Query(None),
):
    """GET shows confirm; does not mutate."""
    sid_attr = f'<input type="hidden" name="sid" value="{sid}">' if sid else ""
    return HTMLResponse(
        f"""<html><body style="background:#050505;color:#E8D5A3;font-family:Georgia,serif;padding:40px;">
        <h1>Unsubscribe</h1>
        <p>Confirm you want to leave Little Nate Dispatch.</p>
        <form method="POST" action="/api/newsletter/unsubscribe">
          <input type="hidden" name="t" value="{t}">
          {sid_attr}
          <button type="submit" style="background:#C9A962;border:0;padding:12px 20px;">Unsubscribe</button>
        </form>
        </body></html>"""
    )


@router.post("/unsubscribe")
async def unsubscribe_post(request: Request):
    pool = _pool(request)
    form = await request.form()
    t = str(form.get("t") or "")
    sid = form.get("sid")
    if not t:
        try:
            body = await request.json()
            t = str(body.get("t", ""))
            sid = body.get("sid") or sid
        except Exception:
            pass
    th = _hash_token(t)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id FROM newsletter_subscribers
            WHERE unsubscribe_token_hash = $1 OR confirm_token_hash = $1
            LIMIT 1
            """,
            th,
        )
        if row:
            await conn.execute(
                """
                UPDATE newsletter_subscribers
                SET status = 'unsubscribed', updated_at = NOW()
                WHERE id = $1
                """,
                row["id"],
            )
        elif sid:
            expected = hashlib.sha256(
                f"{TOKEN_SALT}:unsub:{sid}".encode()
            ).hexdigest()[:40]
            if secrets.compare_digest(t, expected):
                await conn.execute(
                    """
                    UPDATE newsletter_subscribers
                    SET status = 'unsubscribed', updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    sid,
                )
    return HTMLResponse(
        "<html><body style='background:#050505;color:#8B7355;padding:40px;'>"
        "<p>You have been unsubscribed.</p></body></html>"
    )


@router.get("/rate")
async def rate(
    request: Request,
    issue: str = Query(...),
    score: int = Query(..., ge=1, le=5),
    sid: Optional[str] = Query(None),
    t: str = Query(...),
):
    """One-tap GET rating (email clients). Idempotent."""
    pool = _pool(request)
    async with pool.acquire() as conn:
        issue_row = await conn.fetchrow(
            "SELECT id FROM newsletter_issues WHERE slug = $1", issue
        )
        if not issue_row:
            raise HTTPException(404, "Issue not found")
        # Lightweight token check: must match expected hash pattern length
        if len(t) < 16:
            raise HTTPException(400, "Invalid token")
        sub_id = None
        if sid:
            try:
                import uuid as _uuid

                sub_id = _uuid.UUID(sid)
            except Exception:
                sub_id = None
        topic = await conn.fetchval(
            "SELECT topic FROM newsletter_issues WHERE id = $1", issue_row["id"]
        )
        await conn.execute(
            """
            INSERT INTO newsletter_feedback (issue_id, subscriber_id, helpful_score, rating_token_hash)
            VALUES ($1, $2, $3, $4)
            """,
            issue_row["id"],
            sub_id,
            score,
            _hash_token(t),
        )
    if topic:
        try:
            from app.services.newsletter_signals import record_theme_signal

            await record_theme_signal(pool, topic, source="feedback")
        except Exception:
            pass
    return HTMLResponse(
        "<html><body style='background:#050505;color:#C9A962;padding:40px;'>"
        "<p>Thank you — Nate is learning from your rating.</p>"
        "<p>Know someone who'd benefit? Forward your Dispatch email or share the Story Library link.</p>"
        "</body></html>"
    )


@router.get("/library")
async def library_list(request: Request, limit: int = Query(20, ge=1, le=100)):
    pool = _pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT slug, topic, subject_line, sent_at, external_link
            FROM newsletter_issues
            WHERE status = 'sent'
            ORDER BY sent_at DESC NULLS LAST
            LIMIT $1
            """,
            limit,
        )
    return {
        "status": "ok",
        "issues": [dict(r) for r in rows],
    }


@router.get("/library/{slug}")
async def library_issue(slug: str, request: Request):
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT slug, topic, subject_line, opener, body_md, final_body,
                   techniques, citations, external_link, sent_at
            FROM newsletter_issues
            WHERE slug = $1 AND status = 'sent'
            """,
            slug,
        )
        if not row:
            raise HTTPException(404, "Not found")
        await conn.execute(
            """
            INSERT INTO newsletter_library_stats (slug, view_count)
            VALUES ($1, 1)
            ON CONFLICT (slug) DO UPDATE
            SET view_count = newsletter_library_stats.view_count + 1,
                updated_at = NOW()
            """,
            slug,
        )
    d = dict(row)
    if d.get("topic"):
        try:
            from app.services.newsletter_signals import record_theme_signal

            await record_theme_signal(pool, d["topic"], source="library")
        except Exception:
            pass
    return {"status": "ok", "issue": d}


@router.get("/library/{slug}/page")
async def library_issue_html(slug: str, request: Request):
    """HTML Story Library page — works without static nginx /library/."""
    from app.services.newsletter_delivery import render_library_html

    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT slug, topic, subject_line, opener, body_md, final_body, sent_at
            FROM newsletter_issues
            WHERE slug = $1 AND status = 'sent'
            """,
            slug,
        )
        if not row:
            raise HTTPException(404, "Not found")
        await conn.execute(
            """
            INSERT INTO newsletter_library_stats (slug, view_count)
            VALUES ($1, 1)
            ON CONFLICT (slug) DO UPDATE
            SET view_count = newsletter_library_stats.view_count + 1,
                updated_at = NOW()
            """,
            slug,
        )
    return HTMLResponse(render_library_html(dict(row)))


@router.get("/share")
async def share_track(
    request: Request,
    slug: str = Query(...),
    channel: str = Query("link"),
):
    pool = _pool(request)
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM newsletter_issues WHERE slug = $1 AND status = 'sent'", slug
        )
        if not exists:
            raise HTTPException(404)
        await conn.execute(
            """
            INSERT INTO newsletter_library_stats (slug, share_count)
            VALUES ($1, 1)
            ON CONFLICT (slug) DO UPDATE
            SET share_count = newsletter_library_stats.share_count + 1,
                updated_at = NOW()
            """,
            slug,
        )
    try:
        from app.services.newsletter_signals import bump_growth_ledger

        await bump_growth_ledger(pool, f"share_{channel[:32]}", conversions=0)
    except Exception:
        pass
    from app.services.newsletter_delivery import library_page_url
    from fastapi.responses import RedirectResponse

    return RedirectResponse(library_page_url(slug), status_code=302)


@router.get("/rss")
async def rss(request: Request):
    from app.services.newsletter_delivery import library_page_url

    pool = _pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT slug, topic, subject_line, sent_at
            FROM newsletter_issues WHERE status = 'sent'
            ORDER BY sent_at DESC NULLS LAST LIMIT 50
            """
        )
    items = []
    base = os.getenv("NEWSLETTER_PUBLIC_BASE", "https://app.sovereignsanctuary.net").rstrip("/")
    for r in rows:
        items.append(
            f"<item><title>{_xml(r['subject_line'] or r['topic'])}</title>"
            f"<link>{library_page_url(r['slug'])}</link>"
            f"<guid>{r['slug']}</guid></item>"
        )
    xml = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<title>Little Nate Dispatch</title>"
        f"<link>{base}/nate_story_library.html</link>"
        + "".join(items)
        + "</channel></rss>"
    )
    return HTMLResponse(xml, media_type="application/rss+xml")


def _xml(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ── Admin ────────────────────────────────────────────────────────────


@admin_router.get("/issues")
async def admin_list_issues(request: Request, admin: Dict = Depends(require_admin)):
    pool = _pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, slug, status, topic, subject_line, opener,
                   LEFT(COALESCE(body_md, ''), 160) AS body_preview,
                   created_at, sent_at, approved_at, updated_at
            FROM newsletter_issues
            ORDER BY created_at DESC LIMIT 50
            """
        )
    return {"status": "ok", "issues": [_row_json(r) for r in rows]}


@admin_router.get("/issues/{issue_id}")
async def admin_get_issue(issue_id: str, request: Request, admin: Dict = Depends(require_admin)):
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM newsletter_issues WHERE id = $1::uuid", issue_id
        )
    if not row:
        raise HTTPException(404, "Issue not found")
    return {"status": "ok", "issue": _row_json(row)}


@admin_router.get("/issues/{issue_id}/preview")
async def admin_preview_issue(
    issue_id: str, request: Request, admin: Dict = Depends(require_admin)
):
    """HTML preview as subscribers / Story Library will see it (draft body)."""
    from app.services.newsletter_delivery import render_library_html

    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM newsletter_issues WHERE id = $1::uuid", issue_id
        )
    if not row:
        raise HTTPException(404, "Issue not found")
    issue = _row_json(row)
    # Preview uses current editor body, not only final_body
    issue["final_body"] = issue.get("body_md") or issue.get("final_body") or ""
    return HTMLResponse(render_library_html(issue))


@admin_router.put("/issues/{issue_id}")
async def admin_update_issue(
    issue_id: str,
    body: UpdateIssueBody,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    """Editor save — subject / topic / opener / body while in_review or draft."""
    pool = _pool(request)
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "No fields to update")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status, body_md FROM newsletter_issues WHERE id = $1::uuid",
            issue_id,
        )
        if not row:
            raise HTTPException(404, "Issue not found")
        if row["status"] not in ("in_review", "draft", "rejected"):
            raise HTTPException(400, f"Cannot edit status={row['status']}")
        new_body = fields.get("body_md", row["body_md"])
        content_hash = (
            hashlib.sha256((new_body or "").encode()).hexdigest() if new_body else None
        )
        await conn.execute(
            """
            UPDATE newsletter_issues SET
                subject_line = COALESCE($2, subject_line),
                topic = COALESCE($3, topic),
                opener = COALESCE($4, opener),
                body_md = COALESCE($5, body_md),
                draft_body = COALESCE($5, draft_body),
                final_body = NULL,
                content_hash = COALESCE($6, content_hash),
                status = CASE WHEN status = 'rejected' THEN 'in_review' ELSE status END,
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            issue_id,
            fields.get("subject_line"),
            fields.get("topic"),
            fields.get("opener"),
            fields.get("body_md"),
            content_hash,
        )
        updated = await conn.fetchrow(
            "SELECT * FROM newsletter_issues WHERE id = $1::uuid", issue_id
        )
    return {
        "status": "ok",
        "saved": True,
        "issue": _row_json(updated),
        "editor": admin.get("username") or "admin",
    }


@admin_router.post("/issues/{issue_id}/rewrite")
async def admin_rewrite_issue(
    issue_id: str,
    body: RewriteIssueBody,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    """Regenerate draft from research bundle + optional editor direction."""
    from app.services.newsletter_pipeline import rewrite_existing_issue

    result = await rewrite_existing_issue(
        _pool(request), issue_id, notes=body.notes or ""
    )
    if not result.get("ok"):
        raise HTTPException(400, detail=result)
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM newsletter_issues WHERE id = $1::uuid", issue_id
        )
    return {
        "status": "ok",
        "rewritten": True,
        "issue": _row_json(row) if row else None,
        "editor": admin.get("username") or "admin",
    }


@admin_router.post("/issues/{issue_id}/approve")
async def admin_approve(issue_id: str, request: Request, admin: Dict = Depends(require_admin)):
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE newsletter_issues
            SET status = 'approved', approved_at = NOW(),
                approved_by = $2, final_body = body_md,
                updated_at = NOW()
            WHERE id = $1::uuid AND status = 'in_review'
            RETURNING id, slug, subject_line
            """,
            issue_id,
            admin.get("username") or "admin",
        )
    if not row:
        raise HTTPException(400, "Issue not in_review or not found")
    return {
        "status": "ok",
        "issue_id": issue_id,
        "approved": True,
        "slug": row["slug"],
    }


@admin_router.post("/issues/{issue_id}/reject")
async def admin_reject(
    issue_id: str,
    request: Request,
    admin: Dict = Depends(require_admin),
    reason: str = Query("editor_reject"),
):
    pool = _pool(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    why = (body.get("reason") if isinstance(body, dict) else None) or reason
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE newsletter_issues
            SET status = 'rejected', rejected_reason = $2, updated_at = NOW()
            WHERE id = $1::uuid AND status IN ('in_review', 'draft', 'approved')
            """,
            issue_id,
            str(why)[:500],
        )
    return {"status": "ok", "rejected": True}


@admin_router.post("/issues/{issue_id}/send")
async def admin_send(issue_id: str, request: Request, admin: Dict = Depends(require_admin)):
    from app.services.newsletter_delivery import send_issue_to_subscribers

    redis = getattr(request.app.state, "redis", None) or getattr(
        request.app.state, "cache_redis", None
    )
    result = await send_issue_to_subscribers(_pool(request), issue_id, redis=redis)
    return {"status": "ok", **result}


@admin_router.post("/pipeline/run")
async def admin_run_pipeline(request: Request, admin: Dict = Depends(require_admin)):
    agent = getattr(request.app.state, "newsletter_agent", None)
    if agent is None:
        from app.services.newsletter_agent import NewsletterAgent

        agent = NewsletterAgent(db_pool=_pool(request), app_state=request.app.state)
    result = await agent.run_pipeline_to_review()
    return {"status": "ok", **result}


@admin_router.get("/subscribers/stats")
async def admin_sub_stats(request: Request, admin: Dict = Depends(require_admin)):
    pool = _pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT status, COUNT(*)::int AS n
            FROM newsletter_subscribers GROUP BY status
            """
        )
        warm = await conn.fetchval("SELECT COUNT(*)::int FROM newsletter_warm_leads")
    return {
        "status": "ok",
        "by_status": {r["status"]: r["n"] for r in rows},
        "warm_leads": warm or 0,
    }
