"""Warm-lead mining + social contact capture for Dispatch opt-in.

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.newsletter_warm_leads")

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


async def process_warm_leads(db_pool, app_state=None) -> Dict[str, Any]:
    if not db_pool:
        return {"invited": 0}
    invited = 0
    invited += await _mine_trial_leads(db_pool)
    invited += await _mine_users_without_dispatch(db_pool)
    return {"invited": invited}


async def _mine_trial_leads(db_pool) -> int:
    """Import trial lead emails not already subscribed."""
    invited = 0
    try:
        async with db_pool.acquire() as conn:
            # trial_leads table may vary — try common shapes
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
        # extract if buried in text
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
