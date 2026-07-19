"""SendGrid delivery for Little Nate Dispatch.

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.newsletter_delivery")

PUBLIC_BASE = os.getenv(
    "NEWSLETTER_PUBLIC_BASE", "https://app.sovereignsanctuary.net"
).rstrip("/")
PHYSICAL_ADDRESS = os.getenv(
    "NEWSLETTER_PHYSICAL_ADDRESS",
    "Sovereign Sanctuary, Stafford, TX 77477",
)


def _html_email(issue: Dict[str, Any], rate_base: str, unsub_url: str) -> str:
    body = (issue.get("final_body") or issue.get("body_md") or "").replace("\n", "<br>\n")
    slug = issue.get("slug") or ""
    library_url = f"{PUBLIC_BASE}/library/{slug}.html"
    return f"""<!DOCTYPE html><html><body style="font-family:Georgia,serif;background:#050505;color:#E8D5A3;padding:24px;">
<h1 style="color:#C9A962;">Little Nate Dispatch</h1>
<p style="color:#8B7355;">{issue.get('subject_line') or ''}</p>
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
<p><a href="mailto:?subject=Little%20Nate%20Dispatch&body={library_url}">Share by email</a>
 · <a href="sms:?&body={library_url}">Share by text</a></p>
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

    async with db_pool.acquire() as conn:
        issue = await conn.fetchrow(
            "SELECT * FROM newsletter_issues WHERE id = $1 AND status = 'approved'",
            issue_id,
        )
        if not issue:
            return {"sent": 0, "error": "not_approved"}
        issue_d = dict(issue)
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
            # Prefer API host for rate/unsub endpoints
            api_base = os.getenv(
                "API_PUBLIC_BASE", "https://api.sovereignsanctuary.net"
            ).rstrip("/")
            rate_base = (
                f"{api_base}/api/newsletter/rate"
                f"?issue={issue_d['slug']}&sid={sub['id']}&t={rate_token}"
            )
            # Deterministic raw unsub token (never put hash in URL)
            salt = os.getenv("NEWSLETTER_TOKEN_SALT", "nate-dispatch")
            unsub_raw = hashlib.sha256(
                f"{salt}:unsub:{sub['id']}".encode()
            ).hexdigest()[:40]
            unsub_url = (
                f"{api_base}/api/newsletter/unsubscribe"
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
        # Static library page marker + stats
        await conn.execute(
            """
            INSERT INTO newsletter_library_stats (slug)
            VALUES ($1) ON CONFLICT (slug) DO NOTHING
            """,
            issue_d["slug"],
        )

    # Crystallize after send
    try:
        from app.services.newsletter_library_recall import crystallize_sent_issue

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM newsletter_issues WHERE id = $1", issue_id)
        if row:
            await crystallize_sent_issue(db_pool, dict(row))
    except Exception as e:
        logger.warning("post-send crystallize failed: %s", e)

    # Write static HTML locally for deploy
    try:
        await _write_library_html(issue_d)
    except Exception as e:
        logger.warning("library html write failed: %s", e)

    return {"sent": sent, "issue_id": str(issue_id), "slug": issue_d.get("slug")}


async def _write_library_html(issue: Dict[str, Any]) -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "dashboard" / "library"
    root.mkdir(parents=True, exist_ok=True)
    slug = issue.get("slug") or "issue"
    body = (issue.get("final_body") or issue.get("body_md") or "").replace("\n", "<br>\n")
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><title>{issue.get('subject_line') or 'Little Nate Dispatch'}</title>
<meta property="og:title" content="{issue.get('subject_line') or 'Little Nate Dispatch'}">
<meta property="og:description" content="Little Nate's Story Library">
<link rel="canonical" href="{PUBLIC_BASE}/library/{slug}.html">
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"Article","headline":{json_escape(issue.get('subject_line') or '')},"author":{{"@type":"Organization","name":"Little Nate Dispatch"}}}}
</script>
<style>body{{background:#050505;color:#E8D5A3;font-family:Georgia,serif;max-width:720px;margin:40px auto;padding:0 16px;line-height:1.6}}
a{{color:#4ECDC4}} h1{{color:#C9A962}}</style>
</head><body>
<h1>Little Nate Dispatch</h1>
<p>{issue.get('topic') or ''}</p>
<article>{body}</article>
<footer style="margin-top:48px;font-size:13px;color:#8B7355;">
Little Nate is an AI companion — education, not therapy or medical advice.
Crisis: <a href="https://988lifeline.org">988</a> · <a href="https://findahelpline.com">findahelpline.com</a>
</footer>
</body></html>"""
    (root / f"{slug}.html").write_text(html, encoding="utf-8")


def json_escape(s: str) -> str:
    import json

    return json.dumps(s or "")
