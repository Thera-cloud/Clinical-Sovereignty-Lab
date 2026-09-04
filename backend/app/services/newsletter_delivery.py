"""SendGrid + SMS delivery for Little Nate Dispatch.

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""
from __future__ import annotations

import hashlib
import html as html_mod
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote

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
TOKEN_SALT = os.getenv("NEWSLETTER_TOKEN_SALT", "nate-dispatch")


def rate_token_for_subscriber(issue_id: Union[str, Any], subscriber_id: Union[str, Any]) -> str:
    """Canonical per-subscriber rating token (must match newsletter_api /rate)."""
    return hashlib.sha256(
        f"{issue_id}:{subscriber_id}:rate:{TOKEN_SALT}".encode()
    ).hexdigest()[:32]


def library_rate_token(issue_id: Union[str, Any]) -> str:
    """Shared library-page rating token (anonymous, fingerprint added at API)."""
    return hashlib.sha256(
        f"{issue_id}:library_rate:{TOKEN_SALT}".encode()
    ).hexdigest()[:32]


def utm_library_url(slug: str, channel: str) -> str:
    """Public library page URL with share attribution query params."""
    base = library_page_url(slug)
    sep = "&" if "?" in base else "?"
    return (
        f"{base}{sep}utm_source=share&utm_medium={quote(channel[:32])}"
        f"&utm_campaign=dispatch&ref={quote(slug)}"
    )


def share_tracker_url(slug: str, channel: str) -> str:
    """API share endpoint — increments stats then 302s to network or library."""
    return f"{API_BASE}/api/newsletter/share?slug={quote(slug)}&channel={quote(channel[:32])}"


def share_intent_url(channel: str, library_utm_url: str, title: str = "") -> str:
    """Build native share-intent URL for a social network (or passthrough)."""
    enc = quote(library_utm_url, safe="")
    t = quote((title or "Little Nate Dispatch")[:120], safe="")
    ch = (channel or "link").lower()
    if ch in ("x", "twitter"):
        return f"https://twitter.com/intent/tweet?url={enc}&text={t}"
    if ch == "facebook":
        return f"https://www.facebook.com/sharer/sharer.php?u={enc}"
    if ch == "linkedin":
        return f"https://www.linkedin.com/sharing/share-offsite/?url={enc}"
    if ch == "whatsapp":
        return f"https://api.whatsapp.com/send?text={t}%20{enc}"
    if ch == "email":
        return f"mailto:?subject={t}&body={enc}"
    if ch == "sms":
        return f"sms:?&body={enc}"
    return library_utm_url


def _share_row_html(slug: str, title: str = "", *, style_inline: bool = True) -> str:
    """Tracked share links for email + library pages."""
    channels = (
        ("x", "X"),
        ("facebook", "Facebook"),
        ("linkedin", "LinkedIn"),
        ("whatsapp", "WhatsApp"),
        ("email", "Email"),
        ("sms", "Text"),
    )
    color = "#C9A962" if style_inline else "#4ECDC4"
    parts = []
    for ch, label in channels:
        href = share_tracker_url(slug, ch)
        parts.append(
            f'<a href="{href}" style="color:{color};margin-right:10px;">{label}</a>'
        )
    return (
        '<p style="margin:16px 0 8px;font-size:14px;">Share this Dispatch: '
        + " · ".join(parts)
        + "</p>"
    )


def _subscribe_cta_html(slug: str) -> str:
    sub = (
        f"{PUBLIC_BASE}/nate_story_library.html"
        f"?subscribe=1&utm_source=library&utm_medium=cta&ref={quote(slug)}"
    )
    return (
        f'<p style="margin:20px 0;padding:14px;border:1px solid #333;border-radius:4px;">'
        f'<strong style="color:#C9A962;">Get the next Dispatch</strong><br>'
        f'<span style="color:#8B7355;font-size:14px;">Weekly education from Little Nate — free.</span><br>'
        f'<a href="{sub}" style="color:#4ECDC4;">Subscribe</a></p>'
    )


def _inline_md(escaped_line: str) -> str:
    """Apply link/bold/italic on an already HTML-escaped line."""

    def _link(m: re.Match) -> str:
        label, url = m.group(1), m.group(2).strip()
        if not url.startswith(("http://", "https://", "mailto:")):
            return m.group(0)
        safe_url = html_mod.escape(url, quote=True)
        return f'<a href="{safe_url}">{label}</a>'

    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, escaped_line)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", s)
    return s


def md_body_to_html(md: str) -> str:
    """Minimal safe markdown → HTML for email + Story Library (no external lib)."""
    out: List[str] = []
    for line in (md or "").split("\n"):
        if line.startswith("### "):
            out.append(f"<h3 style=\"color:#C9A962;\">{_inline_md(html_mod.escape(line[4:]))}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2 style=\"color:#C9A962;\">{_inline_md(html_mod.escape(line[3:]))}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1 style=\"color:#C9A962;\">{_inline_md(html_mod.escape(line[2:]))}</h1>")
        elif not line.strip():
            out.append("<br>")
        else:
            out.append(_inline_md(html_mod.escape(line)) + "<br>")
    return "\n".join(out)


def _parse_citations(issue: Dict[str, Any]) -> List[Dict[str, Any]]:
    cites = issue.get("citations")
    if isinstance(cites, str):
        try:
            cites = json.loads(cites)
        except Exception:
            cites = []
    if not isinstance(cites, list):
        return []
    return [c for c in cites if isinstance(c, dict) and c.get("url")]


def _sources_html(issue: Dict[str, Any]) -> str:
    """Structured sources block when citations exist (clickable)."""
    cites = _parse_citations(issue)
    ext = (issue.get("external_link") or "").strip()
    if not cites and not ext:
        return ""
    body_lower = (issue.get("final_body") or issue.get("body_md") or "").lower()
    # Skip if body already has a Further reading section with a markdown link
    if "further reading" in body_lower and "](http" in body_lower:
        if not cites:
            return ""
    items = []
    seen = set()
    for c in cites[:8]:
        url = (c.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        name = html_mod.escape(str(c.get("source_name") or url)[:120])
        year = c.get("year")
        label = f"{name} ({year})" if year else name
        items.append(
            f'<li><a href="{html_mod.escape(url, quote=True)}" style="color:#4ECDC4;">{label}</a></li>'
        )
    if ext and ext not in seen:
        items.append(
            f'<li><a href="{html_mod.escape(ext, quote=True)}" style="color:#4ECDC4;">'
            f"{html_mod.escape(ext[:80])}</a></li>"
        )
    if not items:
        return ""
    return (
        '<div style="margin-top:28px;padding-top:16px;border-top:1px solid #333;">'
        '<p style="color:#8B7355;font-size:13px;margin:0 0 8px;">Sources</p>'
        f'<ul style="color:#E8D5A3;font-size:14px;padding-left:20px;">{"".join(items)}</ul></div>'
    )


def _library_rate_block(issue: Dict[str, Any]) -> str:
    """1–5 rating links for Story Library HTML pages."""
    issue_id = issue.get("id")
    slug = issue.get("slug") or ""
    if not issue_id or not slug:
        return ""
    tok = library_rate_token(issue_id)
    base = f"{API_BASE}/api/newsletter/rate?issue={quote(slug)}&t={tok}&via=library"
    links = " ".join(
        f'<a href="{base}&score={s}" style="color:#C9A962;margin-right:8px;">{s}</a>'
        for s in (5, 4, 3, 2, 1)
    )
    return (
        f'<p style="margin-top:24px;">Was this helpful? {links}</p>'
        '<p style="font-size:12px;color:#8B7355;">Your rating teaches Little Nate which themes to cover next.</p>'
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
    cache_bust: bool = False,
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
    if cache_bust:
        bust = issue.get("hero_image_generated_at") or ""
        if hasattr(bust, "isoformat"):
            bust = bust.isoformat()
        bust = str(bust).strip() or str(int(datetime.now(timezone.utc).timestamp()))
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}t={bust}"
    alt = (issue.get("topic") or issue.get("subject_line") or "Little Nate Dispatch").replace(
        '"', "'"
    )[:120]
    return (
        f'<img src="{url}" alt="{alt}" width="600" '
        f'style="max-width:{max_width};height:auto;border-radius:4px;margin:16px 0;display:block;" />'
    )


def _og_description(issue: Dict[str, Any]) -> str:
    raw = (issue.get("opener") or issue.get("final_body") or issue.get("body_md") or "")
    raw = re.sub(r"[#*_`\[\]]+", "", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return (raw[:180] + ("…" if len(raw) > 180 else "")) or "Little Nate's Story Library"


def render_library_html(issue: Dict[str, Any], *, admin_preview: bool = False) -> str:
    slug = issue.get("slug") or "issue"
    body = md_body_to_html(issue.get("final_body") or issue.get("body_md") or "")
    sources = _sources_html(issue)
    rate_block = "" if admin_preview else _library_rate_block(issue)
    hero = _hero_img_tag(issue, placeholder=admin_preview, cache_bust=admin_preview)
    share_row = "" if admin_preview else _share_row_html(
        slug, str(issue.get("subject_line") or ""), style_inline=False
    )
    subscribe = "" if admin_preview else _subscribe_cta_html(slug)
    og_image = ""
    if issue.get("hero_image_url") or issue.get("hero_image_r2_key"):
        og_url = issue.get("hero_image_url") or _hero_stable_url(slug)
        og_image = f'<meta property="og:image" content="{og_url}">'
    topic_esc = html_mod.escape(str(issue.get("topic") or ""))
    og_desc = html_mod.escape(_og_description(issue))
    title_esc = html_mod.escape(str(issue.get("subject_line") or "Little Nate Dispatch"))
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><title>{title_esc}</title>
<meta property="og:title" content="{title_esc}">
<meta property="og:description" content="{og_desc}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title_esc}">
<meta name="twitter:description" content="{og_desc}">
{og_image}
<link rel="canonical" href="{library_page_url(slug)}">
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"Article","headline":{json_escape(issue.get('subject_line') or '')},"author":{{"@type":"Organization","name":"Little Nate Dispatch"}}}}
</script>
<style>body{{background:#050505;color:#E8D5A3;font-family:Georgia,serif;max-width:720px;margin:40px auto;padding:0 16px;line-height:1.6}}
a{{color:#4ECDC4}} h1{{color:#C9A962}} img{{max-width:100%}}</style>
</head><body>
<h1>Little Nate Dispatch</h1>
<p>{topic_esc}</p>
{hero}
<article>{body}</article>
{sources}
{share_row}
{subscribe}
{rate_block}
<footer style="margin-top:48px;font-size:13px;color:#8B7355;">
Little Nate is an AI companion — education, not therapy or medical advice.
Crisis: <a href="https://988lifeline.org">988</a> · Veterans: 988 then press 1 ·
<a href="https://findahelpline.com">findahelpline.com</a>
 · <a href="{PUBLIC_BASE}/nate_story_library.html">Story Library</a>
</footer>
</body></html>"""


def _email_preheader(issue: Dict[str, Any]) -> str:
    """Distinct inbox preview — never reuse the subject line."""
    pre = (issue.get("preheader") or "").strip()
    subject = str(issue.get("subject_line") or "").strip()
    if pre and pre.lower() != subject.lower():
        return pre[:160]
    opener = (issue.get("opener") or "").strip()
    if opener:
        m = re.match(r"(.+?[.!?])(\s|$)", re.sub(r"\s+", " ", opener))
        hook = (m.group(1) if m else opener)[:160].strip()
        if hook and hook.lower() != subject.lower():
            return hook
    topic = str(issue.get("topic") or "").strip()
    if topic and f"Little Nate Dispatch: {topic}" != subject:
        return topic[:160]
    return "Skills practice with Little Nate — education, not therapy."


def _html_email(issue: Dict[str, Any], rate_base: str, unsub_url: str) -> str:
    body = md_body_to_html(issue.get("final_body") or issue.get("body_md") or "")
    sources = _sources_html(issue)
    slug = issue.get("slug") or ""
    library_url = library_page_url(slug)
    subject = str(issue.get("subject_line") or "Little Nate Dispatch")
    share_row = _share_row_html(slug, subject, style_inline=True)
    hero = _hero_img_tag(issue, max_width="560px")
    topic_esc = html_mod.escape(str(issue.get("topic") or "This week’s skills"))
    pre_esc = html_mod.escape(_email_preheader(issue))
    return f"""<!DOCTYPE html><html><body style="font-family:Georgia,serif;background:#050505;color:#E8D5A3;padding:24px;">
<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all;">{pre_esc}</div>
<h1 style="color:#C9A962;">Little Nate Dispatch</h1>
<p style="color:#8B7355;">{topic_esc}</p>
{hero}
<div style="color:#ddd;line-height:1.55;">{body}</div>
{sources}
<hr style="border-color:#333;">
<p><a href="{library_url}" style="color:#4ECDC4;">Read in Story Library</a></p>
<p>Was this helpful?
 <a href="{rate_base}&score=5" style="color:#C9A962;">5</a>
 <a href="{rate_base}&score=4" style="color:#C9A962;">4</a>
 <a href="{rate_base}&score=3" style="color:#C9A962;">3</a>
 <a href="{rate_base}&score=2" style="color:#C9A962;">2</a>
 <a href="{rate_base}&score=1" style="color:#C9A962;">1</a>
</p>
{share_row}
<p style="font-size:12px;color:#888;">{html_mod.escape(PHYSICAL_ADDRESS)}<br>
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
        already = await conn.fetchrow(
            "SELECT id, status, slug FROM newsletter_issues WHERE id = $1",
            issue_id,
        )
        if not already:
            return {"sent": 0, "error": "not_found"}
        if already["status"] == "sent":
            return {
                "sent": 0,
                "error": "already_sent",
                "slug": already["slug"],
                "issue_id": str(issue_id),
            }
        issue = await conn.fetchrow(
            "SELECT * FROM newsletter_issues WHERE id = $1 AND status = 'approved'",
            issue_id,
        )
        if not issue:
            return {"sent": 0, "error": "not_approved"}
        issue_d = dict(issue)
        # Block near-replicate of a recently sent issue (same content_hash)
        ch = issue_d.get("content_hash")
        if ch:
            twin = await conn.fetchval(
                """
                SELECT slug FROM newsletter_issues
                WHERE content_hash = $1 AND status = 'sent' AND id <> $2::uuid
                  AND sent_at > NOW() - INTERVAL '180 days'
                LIMIT 1
                """,
                ch,
                issue_id,
            )
            if twin:
                return {
                    "sent": 0,
                    "error": "duplicate_content",
                    "duplicate_of": twin,
                    "issue_id": str(issue_id),
                }

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
            rate_token = rate_token_for_subscriber(issue_id, sub["id"])
            rate_base = (
                f"{API_BASE}/api/newsletter/rate"
                f"?issue={issue_d['slug']}&sid={sub['id']}&t={rate_token}"
            )
            unsub_raw = hashlib.sha256(
                f"{TOKEN_SALT}:unsub:{sub['id']}".encode()
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
        from app.services.twilio_a2p import sms_create_kwargs

        kwargs = sms_create_kwargs(phone, body, max_len=320)
        if not (sid and token and kwargs):
            return False
        client = Client(sid, token)
        client.messages.create(**kwargs)
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
