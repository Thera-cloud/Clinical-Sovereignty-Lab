"""SendGrid + SMS delivery for Little Nate Dispatch.

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.newsletter_delivery")

PUBLIC_BASE = os.getenv(
    "NEWSLETTER_PUBLIC_BASE", "https://app.sovereignsanctuary.net"
).rstrip("/")
API_BASE = os.getenv(
    "API_PUBLIC_BASE", "https://api.sovereignsanctuary.net"
).rstrip("/")
PHYSICAL_ADDRESS = os.getenv(
    "NEWSLETTER_PHYSICAL_ADDRESS",
    "Sovereign Sanctuary, Stafford, TX 77477",
)


def library_page_url(slug: str) -> str:
    """Canonical readable URL — API HTML (works without static nginx)."""
    return f"{API_BASE}/api/newsletter/library/{slug}/page"


def _hero_stable_url(slug: str) -> str:
    return f"{API_BASE}/api/newsletter/library/{slug}/hero"


def _hero_img_tag(
    issue: Dict[str, Any],
    *,
    max_width: str = "100%",
    placeholder: bool = False,
) -> str:
    url = (issue.get("hero_image_url") or "").strip()
    slug = issue.get("slug") or ""
    if not url and slug and (
        issue.get("hero_image_r2_key") or issue.get("hero_image_generated_at")
    ):
        url = _hero_stable_url(slug)
    if not url:
        if not placeholder:
            return ""
        return (
            '<div style="max-width:560px;margin:16px 0;padding:48px 20px;border:1px dashed #8B7355;'
            'border-radius:4px;color:#8B7355;text-align:center;font-size:14px;">'
            "Topic image not generated yet — open the Image tab to write a descriptor and generate."
            "</div>"
        )
    alt = (issue.get("topic") or issue.get("subject_line") or "Little Nate Dispatch").replace(
        '"', "'"
    )[:120]
    return (
        f'<img src="{url}" alt="{alt}" width="600" '
        f'style="max-width:{max_width};height:auto;border-radius:4px;margin:16px 0;display:block;" />'
    )


def render_library_html(issue: Dict[str, Any], *, admin_preview: bool = False) -> str:
    slug = issue.get("slug") or "issue"
    body = (issue.get("final_body") or issue.get("body_md") or "").replace("\n", "<br>\n")
    hero = _hero_img_tag(issue, placeholder=admin_preview)
    og_image = ""
    if issue.get("hero_image_url") or issue.get("hero_image_r2_key"):
        og_url = issue.get("hero_image_url") or _hero_stable_url(slug)
        og_image = f'<meta property="og:image" content="{og_url}">'
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><title>{issue.get('subject_line') or 'Little Nate Dispatch'}</title>
<meta property="og:title" content="{issue.get('subject_line') or 'Little Nate Dispatch'}">
<meta property="og:description" content="Little Nate's Story Library">
{og_image}
<link rel="canonical" href="{library_page_url(slug)}">
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"Article","headline":{json_escape(issue.get('subject_line') or '')},"author":{{"@type":"Organization","name":"Little Nate Dispatch"}}}}
</script>
<style>body{{background:#050505;color:#E8D5A3;font-family:Georgia,serif;max-width:720px;margin:40px auto;padding:0 16px;line-height:1.6}}
a{{color:#4ECDC4}} h1{{color:#C9A962}} img{{max-width:100%}}</style>
</head><body>
<h1>Little Nate Dispatch</h1>
<p>{issue.get('topic') or ''}</p>
{hero}
<article>{body}</article>
<footer style="margin-top:48px;font-size:13px;color:#8B7355;">
Little Nate is an AI companion — education, not therapy or medical advice.
Crisis: <a href="https://988lifeline.org">988</a> · <a href="https://findahelpline.com">findahelpline.com</a>
 · <a href="{PUBLIC_BASE}/nate_story_library.html">Story Library</a>
</footer>
</body></html>"""


def _html_email(issue: Dict[str, Any], rate_base: str, unsub_url: str) -> str:
    body = (issue.get("final_body") or issue.get("body_md") or "").replace("\n", "<br>\n")
    slug = issue.get("slug") or ""
    library_url = library_page_url(slug)
    share_track = f"{API_BASE}/api/newsletter/share?slug={slug}&channel=email"
    hero = _hero_img_tag(issue, max_width="560px")
    return f"""<!DOCTYPE html><html><body style="font-family:Georgia,serif;background:#050505;color:#E8D5A3;padding:24px;">
<h1 style="color:#C9A962;">Little Nate Dispatch</h1>
<p style="color:#8B7355;">{issue.get('subject_line') or ''}</p>
{hero}
<div style="color:#ddd;line-height:1.55;">{body}</div>
<hr style="border-color:#333;">
<p><a href="{library_url}" style="color:#4ECDC4;">Read in Story Library</a></p>
<p>Was this helpful?
 <a href="{rate_base}&score=5" style="color:#C9A962;">5</a>
 <a href="{rate_base}&score=4" style="color:#C9A962;">4</a>
 <a href="{rate_base}&score=3" style="color:#C9A962;">3</a>
 <a href="{rate_base}&score=2" style="color:#C9A962;">2</a>
 <a href="{rate_base}&score=1" style="color:#C9A962;">1</a>
</p>
<p><a href="mailto:?subject=Little%20Nate%20Dispatch&body={library_url}" style="color:#C9A962;">Share by email</a>
 · <a href="sms:?&body={library_url}" style="color:#C9A962;">Share by text</a>
 · <a href="{share_track}" style="color:#8B7355;">Track share</a></p>
<p style="font-size:12px;color:#888;">{PHYSICAL_ADDRESS}<br>
<a href="{unsub_url}" style="color:#888;">Unsubscribe</a></p>
</body></html>"""


async def send_issue_to_subscribers(db_pool, issue_id: str, redis=None) -> Dict[str, Any]:
    """Idempotent send with Redis lock + per-subscriber ledger."""
    if not db_pool:
        return {"sent": 0, "error": "no_db"}

    lock_key = f"newsletter:send_lock:{issue_id}"
    if redis is not None:
        try:
            ok = await redis.set(lock_key, "1", nx=True, ex=3600)
            if not ok:
                return {"sent": 0, "error": "lock_held"}
        except Exception as e:
            logger.warning("send lock failed (continuing cautiously): %s", e)

    api_key = os.getenv("SENDGRID_API_KEY", "").strip()
    from_email = os.getenv("SENDGRID_FROM_EMAIL", "support@sovereignsanctuary.net")
    if not api_key:
        return {"sent": 0, "error": "no_sendgrid"}

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import (
            Mail,
            Email,
            To,
            Content,
            CustomArg,
            Header,
        )
    except ImportError:
        return {"sent": 0, "error": "sendgrid_missing"}

    sms_sent = 0
    async with db_pool.acquire() as conn:
        issue = await conn.fetchrow(
            "SELECT * FROM newsletter_issues WHERE id = $1 AND status = 'approved'",
            issue_id,
        )
        if not issue:
            return {"sent": 0, "error": "not_approved"}
        issue_d = dict(issue)

    # Ensure topic hero exists before HTML email (best-effort; send continues if Imagine fails)
    if not issue_d.get("hero_image_url"):
        try:
            from app.services.newsletter_imagery import generate_hero_for_issue, hero_enabled

            if hero_enabled():
                gen = await generate_hero_for_issue(db_pool, issue_id)
                if gen.get("ok") and gen.get("hero_image_url"):
                    issue_d["hero_image_url"] = gen["hero_image_url"]
                    issue_d["hero_image_r2_key"] = (
                        f"newsletter_library/{issue_d.get('slug')}-hero.png"
                    )
        except Exception as e:
            logger.warning("pre-send hero generate: %s", e)

    async with db_pool.acquire() as conn:
        # refresh row in case hero was written
        fresh = await conn.fetchrow(
            "SELECT * FROM newsletter_issues WHERE id = $1", issue_id
        )
        if fresh:
            issue_d = dict(fresh)
        subs = await conn.fetch(
            """
            SELECT * FROM newsletter_subscribers
            WHERE status = 'active'
              AND suppressed_reason IS NULL
            ORDER BY created_at ASC
            """
        )

        sg = SendGridAPIClient(api_key)
        sent = 0
        for sub in subs:
            existing = await conn.fetchval(
                "SELECT id FROM newsletter_sends WHERE issue_id = $1 AND subscriber_id = $2",
                issue_id,
                sub["id"],
            )
            if existing:
                continue
            await conn.execute(
                """
                INSERT INTO newsletter_sends (issue_id, subscriber_id, status)
                VALUES ($1, $2, 'queued')
                ON CONFLICT (issue_id, subscriber_id) DO NOTHING
                """,
                issue_id,
                sub["id"],
            )
            rate_token = hashlib.sha256(
                f"{issue_id}:{sub['id']}:rate:{os.getenv('NEWSLETTER_TOKEN_SALT', 'nate')}".encode()
            ).hexdigest()[:32]
            rate_base = (
                f"{API_BASE}/api/newsletter/rate"
                f"?issue={issue_d['slug']}&sid={sub['id']}&t={rate_token}"
            )
            salt = os.getenv("NEWSLETTER_TOKEN_SALT", "nate-dispatch")
            unsub_raw = hashlib.sha256(
                f"{salt}:unsub:{sub['id']}".encode()
            ).hexdigest()[:40]
            unsub_url = (
                f"{API_BASE}/api/newsletter/unsubscribe"
                f"?sid={sub['id']}&t={unsub_raw}"
            )
            html = _html_email(issue_d, rate_base, unsub_url)
            try:
                message = Mail(
                    from_email=Email(from_email, "Little Nate Dispatch"),
                    to_emails=To(sub["email"]),
                    subject=issue_d.get("subject_line") or "Little Nate Dispatch",
                    html_content=Content("text/html", html),
                )
                message.custom_arg = [
                    CustomArg("channel", "newsletter"),
                    CustomArg("issue_id", str(issue_id)),
                    CustomArg("subscriber_id", str(sub["id"])),
                ]
                message.header = Header("List-Unsubscribe", f"<{unsub_url}>")
                resp = sg.send(message)
                mid = ""
                if resp and getattr(resp, "headers", None):
                    mid = resp.headers.get("X-Message-Id") or ""
                await conn.execute(
                    """
                    UPDATE newsletter_sends
                    SET status = 'sent', sent_at = NOW(), provider_message_id = $1
                    WHERE issue_id = $2 AND subscriber_id = $3
                    """,
                    mid,
                    issue_id,
                    sub["id"],
                )
                sent += 1
                if sub.get("phone_e164"):
                    ok_sms = await _send_dispatch_sms(
                        sub["phone_e164"], issue_d.get("slug") or ""
                    )
                    if ok_sms:
                        sms_sent += 1
            except Exception as e:
                logger.warning("newsletter send failed for %s: %s", sub["email"], e)
                await conn.execute(
                    """
                    UPDATE newsletter_sends SET status = 'failed'
                    WHERE issue_id = $1 AND subscriber_id = $2
                    """,
                    issue_id,
                    sub["id"],
                )

        await conn.execute(
            """
            UPDATE newsletter_issues
            SET status = 'sent', sent_at = NOW(), final_body = COALESCE(final_body, body_md),
                updated_at = NOW()
            WHERE id = $1
            """,
            issue_id,
        )
        await conn.execute(
            """
            INSERT INTO newsletter_library_stats (slug)
            VALUES ($1) ON CONFLICT (slug) DO NOTHING
            """,
            issue_d["slug"],
        )

    try:
        from app.services.newsletter_library_recall import crystallize_sent_issue

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM newsletter_issues WHERE id = $1", issue_id
            )
        if row:
            await crystallize_sent_issue(db_pool, dict(row))
    except Exception as e:
        logger.warning("post-send crystallize failed: %s", e)

    archive_meta = {}
    try:
        archive_meta = await _write_library_html(issue_d, db_pool=db_pool)
    except Exception as e:
        logger.warning("library html write failed: %s", e)

    if issue_d.get("topic"):
        try:
            from app.services.newsletter_signals import record_theme_signal

            await record_theme_signal(db_pool, issue_d["topic"], source="send")
        except Exception:
            pass

    return {
        "sent": sent,
        "sms_sent": sms_sent,
        "issue_id": str(issue_id),
        "slug": issue_d.get("slug"),
        "library_url": library_page_url(issue_d.get("slug") or ""),
        **archive_meta,
    }


async def _send_dispatch_sms(phone: str, slug: str) -> bool:
    if os.getenv("ENABLE_NEWSLETTER_SMS", "true").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return False
    body = (
        f"Little Nate Dispatch is ready: {library_page_url(slug)} "
        f"Reply STOP to opt out of SMS."
    )
    try:
        from twilio.rest import Client

        sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        from_num = os.getenv("TWILIO_FROM_NUMBER") or os.getenv("TWILIO_PHONE_NUMBER")
        if not (sid and token and from_num and phone):
            return False
        client = Client(sid, token)
        client.messages.create(to=phone, from_=from_num, body=body[:320])
        return True
    except Exception as e:
        logger.warning("dispatch SMS failed: %s", e)
        return False


async def _write_library_html(issue: Dict[str, Any], db_pool=None) -> Dict[str, Any]:
    """Write to DATA_DIR (rw) + R2/Azure via blob_storage; never dashboard/:ro."""
    slug = issue.get("slug") or "issue"
    html = render_library_html(issue)
    data_dir = Path(os.getenv("DATA_DIR", "/app/data"))
    root = data_dir / "newsletter_library"
    root.mkdir(parents=True, exist_ok=True)
    local_path = root / f"{slug}.html"
    local_path.write_text(html, encoding="utf-8")
    try:
        os.chmod(local_path, 0o644)
    except Exception:
        pass

    r2_key = f"newsletter_library/{slug}.html"
    storage_kind = "local"
    if os.getenv("NEWSLETTER_SKIP_CLOUD_ARCHIVE", "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        try:
            from app.services.blob_storage import upload_bytes

            kind, loc = upload_bytes(
                rel_path=f"newsletter_library/{slug}.html",
                content=html.encode("utf-8"),
                content_type="text/html; charset=utf-8",
            )
            storage_kind = kind
            r2_key = loc if kind != "local" else r2_key
        except Exception as e:
            logger.warning("blob archive failed: %s", e)
        try:
            from app.services import r2_storage

            key = f"newsletter_library/{slug}.html"
            await r2_storage.upload_bytes_async(
                key=key,
                content=html.encode("utf-8"),
                content_type="text/html; charset=utf-8",
            )
            r2_key = key
            storage_kind = "r2"
        except Exception as e:
            logger.debug("R2 library archive skip: %s", e)

    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE newsletter_issues
                    SET library_html_path = $1, library_r2_key = $2, updated_at = NOW()
                    WHERE slug = $3
                    """,
                    str(local_path),
                    r2_key,
                    slug,
                )
        except Exception as e:
            logger.warning("persist library paths: %s", e)

    # Best-effort host www sync marker (for scripts/sync_newsletter_library.sh)
    sync_flag = data_dir / "newsletter_library" / ".pending_sync"
    try:
        sync_flag.write_text(
            f"{slug}\n{datetime.now(timezone.utc).isoformat()}\n", encoding="utf-8"
        )
    except Exception:
        pass

    return {
        "library_html_path": str(local_path),
        "library_storage": storage_kind,
        "library_r2_key": r2_key,
    }


def json_escape(s: str) -> str:
    import json

    return json.dumps(s or "")
