"""Warm-lead mining + invite emails + social contact capture for Dispatch.

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""
from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.newsletter_warm_leads")

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


async def process_warm_leads(db_pool, app_state=None) -> Dict[str, Any]:
    if not db_pool:
        return {"invited": 0}
    mined = 0
    mined += await _mine_trial_leads(db_pool)
    mined += await _mine_users_without_dispatch(db_pool)
    invited = await _send_pending_invites(db_pool)
    return {"mined": mined, "invited": invited}


async def _mine_trial_leads(db_pool) -> int:
    invited = 0
    try:
        async with db_pool.acquire() as conn:
            exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'public_trial_leads'
                )
                """
            )
            if not exists:
                return 0
            rows = await conn.fetch(
                """
                SELECT email FROM public_trial_leads
                WHERE email IS NOT NULL AND email != ''
                LIMIT 50
                """
            )
            for r in rows:
                email = (r["email"] or "").strip().lower()
                if not email or "@" not in email:
                    continue
                sub = await conn.fetchval(
                    "SELECT id FROM newsletter_subscribers WHERE LOWER(email) = $1",
                    email,
                )
                if sub:
                    continue
                exists_wl = await conn.fetchval(
                    "SELECT id FROM newsletter_warm_leads WHERE LOWER(email) = $1",
                    email,
                )
                if exists_wl:
                    continue
                await conn.execute(
                    """
                    INSERT INTO newsletter_warm_leads (email, contact_type, source, status)
                    VALUES ($1, 'email', 'trial_lead', 'pending')
                    """,
                    email,
                )
                invited += 1
    except Exception as e:
        logger.warning("mine trial leads: %s", e)
    return invited


async def _mine_users_without_dispatch(db_pool) -> int:
    invited = 0
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT username, profile_data->>'email' AS email
                FROM users
                WHERE role IN ('CLIENT', 'COACH')
                  AND profile_data->>'email' IS NOT NULL
                  AND profile_data->>'email' != ''
                LIMIT 100
                """
            )
            for r in rows:
                email = (r["email"] or "").strip().lower()
                if not email:
                    continue
                sub = await conn.fetchval(
                    "SELECT id FROM newsletter_subscribers WHERE LOWER(email) = $1 AND status = 'active'",
                    email,
                )
                if sub:
                    continue
                exists_wl = await conn.fetchval(
                    "SELECT id FROM newsletter_warm_leads WHERE LOWER(email) = $1",
                    email,
                )
                if exists_wl:
                    continue
                import json as _json

                await conn.execute(
                    """
                    INSERT INTO newsletter_warm_leads
                        (email, contact_type, source, status, metadata)
                    VALUES ($1, 'email', 'sanctuary_user', 'pending', $2::jsonb)
                    """,
                    email,
                    _json.dumps({"username": r["username"]}),
                )
                invited += 1
    except Exception as e:
        logger.warning("mine sanctuary users: %s", e)
    return invited


async def _send_pending_invites(db_pool) -> int:
    """Double opt-in invite only — never activate without confirm."""
    api_key = os.getenv("SENDGRID_API_KEY", "").strip()
    if not api_key:
        return 0
    from_email = os.getenv("SENDGRID_FROM_EMAIL", "support@sovereignsanctuary.net")
    api_base = os.getenv(
        "API_PUBLIC_BASE", "https://api.sovereignsanctuary.net"
    ).rstrip("/")
    invited = 0
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email, To, Content
    except ImportError:
        return 0

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, email FROM newsletter_warm_leads
                WHERE status = 'pending'
                  AND email IS NOT NULL
                  AND (last_invited_at IS NULL OR last_invited_at < NOW() - INTERVAL '7 days')
                ORDER BY created_at ASC
                LIMIT 25
                """
            )
            sg = SendGridAPIClient(api_key)
            for r in rows:
                email = (r["email"] or "").strip().lower()
                if not email:
                    continue
                # Create pending subscriber with confirm token
                raw_confirm = secrets.token_urlsafe(32)
                import hashlib

                salt = os.getenv("NEWSLETTER_TOKEN_SALT", "nate-dispatch")
                confirm_hash = hashlib.sha256(f"{salt}:{raw_confirm}".encode()).hexdigest()
                expires = datetime.now(timezone.utc) + timedelta(hours=72)
                await conn.execute(
                    """
                    INSERT INTO newsletter_subscribers (
                        email, status, confirm_token_hash, confirm_token_expires_at, source
                    ) VALUES ($1, 'pending', $2, $3, 'warm_lead_invite')
                    ON CONFLICT (email) DO UPDATE SET
                        confirm_token_hash = EXCLUDED.confirm_token_hash,
                        confirm_token_expires_at = EXCLUDED.confirm_token_expires_at,
                        updated_at = NOW()
                    WHERE newsletter_subscribers.status = 'pending'
                    """,
                    email,
                    confirm_hash,
                    expires,
                )
                url = f"{api_base}/api/newsletter/confirm?t={raw_confirm}"
                html = (
                    "<p>Little Nate here — I write a short weekly Dispatch on steadiness, "
                    "asking for help, and small steps that restore agency.</p>"
                    f"<p><a href=\"{url}\">Confirm to receive Little Nate Dispatch</a></p>"
                    "<p>If this wasn't for you, ignore this email.</p>"
                )
                try:
                    msg = Mail(
                        from_email=Email(from_email, "Little Nate Dispatch"),
                        to_emails=To(email),
                        subject="You're invited: Little Nate Dispatch",
                        html_content=Content("text/html", html),
                    )
                    sg.send(msg)
                    await conn.execute(
                        """
                        UPDATE newsletter_warm_leads
                        SET status = 'invited', last_invited_at = NOW(), updated_at = NOW()
                        WHERE id = $1
                        """,
                        r["id"],
                    )
                    invited += 1
                except Exception as e:
                    logger.warning("warm invite send failed %s: %s", email, e)
        if invited:
            from app.services.newsletter_signals import bump_growth_ledger

            await bump_growth_ledger(
                db_pool, "warm_lead_invite", invites_sent=invited
            )
    except Exception as e:
        logger.warning("send pending invites: %s", e)
    return invited


async def capture_social_contact(
    db_pool,
    *,
    platform: str,
    handle: Optional[str] = None,
    email: Optional[str] = None,
    platform_user_id: Optional[str] = None,
    source_note: str = "",
) -> bool:
    """Store warm lead from SkyEye engagers. Never auto-activates subscribers."""
    if not db_pool:
        return False
    email_n = (email or "").strip().lower() or None
    if email_n and not _EMAIL_RE.fullmatch(email_n):
        m = _EMAIL_RE.search(email_n)
        email_n = m.group(0).lower() if m else None
    contact_type = "email" if email_n else "handle"
    if contact_type == "handle" and not handle:
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO newsletter_warm_leads
                    (email, platform, handle, platform_user_id, contact_type, source, status, consent_notes)
                VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7)
                ON CONFLICT DO NOTHING
                """,
                email_n,
                platform,
                handle,
                platform_user_id,
                contact_type,
                f"social_{platform}",
                source_note[:500],
            )
        return True
    except Exception as e:
        logger.warning("capture_social_contact: %s", e)
        return False


async def extract_email_from_dm_text(db_pool, platform: str, handle: str, text: str) -> bool:
    m = _EMAIL_RE.search(text or "")
    if not m:
        return False
    return await capture_social_contact(
        db_pool,
        platform=platform,
        handle=handle,
        email=m.group(0),
        source_note="user_provided_in_dm",
    )
