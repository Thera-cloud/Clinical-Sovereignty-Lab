"""Little Nate Dispatch — auto opt-in for platform accounts.

Account holders are subscribed as status=active (can unsubscribe anytime).
Never reactivates unsubscribed or suppressed rows.

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.newsletter_opt_in")

TOKEN_SALT = os.getenv("NEWSLETTER_TOKEN_SALT", "nate-dispatch")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _hash_token(raw: str) -> str:
    return hashlib.sha256(f"{TOKEN_SALT}:{raw}".encode()).hexdigest()


def normalize_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(email and _EMAIL_RE.match(email) and len(email) <= 254)


async def ensure_active_subscriber(
    db_pool,
    email: str,
    *,
    source: str = "account_signup",
    username: str = "",
) -> Dict[str, Any]:
    """Upsert newsletter_subscribers as active for a platform account email.

    Returns {ok, action, email, skipped_reason?}.
    """
    email_n = normalize_email(email)
    if not is_valid_email(email_n):
        return {"ok": False, "action": "skip", "email": email_n, "skipped_reason": "invalid_email"}
    if not db_pool:
        return {"ok": False, "action": "skip", "email": email_n, "skipped_reason": "no_db"}

    unsub_hash = _hash_token(secrets.token_urlsafe(24))
    src = (source or "account_signup")[:80]
    meta_note = (username or "")[:80]

    try:
        async with db_pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id, status FROM newsletter_subscribers WHERE LOWER(email) = $1",
                email_n,
            )
            if existing and existing["status"] in ("unsubscribed", "suppressed"):
                return {
                    "ok": True,
                    "action": "preserved",
                    "email": email_n,
                    "skipped_reason": existing["status"],
                }

            await conn.execute(
                """
                INSERT INTO newsletter_subscribers (
                    email, status, unsubscribe_token_hash,
                    consent_delivery_at, consent_scope, source
                ) VALUES ($1, 'active', $2, NOW(), 'delivery', $3)
                ON CONFLICT (email) DO UPDATE SET
                    status = CASE
                        WHEN newsletter_subscribers.status IN ('unsubscribed', 'suppressed')
                            THEN newsletter_subscribers.status
                        ELSE 'active'
                    END,
                    unsubscribe_token_hash = COALESCE(
                        newsletter_subscribers.unsubscribe_token_hash,
                        EXCLUDED.unsubscribe_token_hash
                    ),
                    consent_delivery_at = CASE
                        WHEN newsletter_subscribers.status IN ('unsubscribed', 'suppressed')
                            THEN newsletter_subscribers.consent_delivery_at
                        ELSE COALESCE(
                            newsletter_subscribers.consent_delivery_at,
                            EXCLUDED.consent_delivery_at
                        )
                    END,
                    source = CASE
                        WHEN newsletter_subscribers.status IN ('unsubscribed', 'suppressed')
                            THEN newsletter_subscribers.source
                        WHEN newsletter_subscribers.source IS NULL
                            OR btrim(newsletter_subscribers.source) = ''
                            THEN EXCLUDED.source
                        ELSE newsletter_subscribers.source
                    END,
                    updated_at = NOW()
                """,
                email_n,
                unsub_hash,
                src if not meta_note else f"{src}:{meta_note}"[:80],
            )
            action = "updated" if existing else "inserted"
            return {"ok": True, "action": action, "email": email_n}
    except Exception as e:
        logger.warning("newsletter opt-in failed for %s: %s", email_n, e)
        return {"ok": False, "action": "error", "email": email_n, "skipped_reason": str(e)[:200]}


async def opt_in_all_platform_users(db_pool) -> Dict[str, Any]:
    """Backfill: every users.profile_data email → active subscriber (respect unsub)."""
    if not db_pool:
        return {"ok": False, "error": "no_db"}

    inserted = updated = preserved = skipped = 0
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT username, LOWER(TRIM(profile_data->>'email')) AS email
            FROM users
            WHERE profile_data->>'email' IS NOT NULL
              AND TRIM(profile_data->>'email') LIKE '%@%'
            """
        )
    seen: set[str] = set()
    for row in rows:
        email_n = normalize_email(row["email"])
        if not email_n or email_n in seen:
            skipped += 1
            continue
        seen.add(email_n)
        result = await ensure_active_subscriber(
            db_pool,
            email_n,
            source="account_backfill",
            username=str(row["username"] or ""),
        )
        if result.get("action") == "inserted":
            inserted += 1
        elif result.get("action") == "updated":
            updated += 1
        elif result.get("action") == "preserved":
            preserved += 1
        else:
            skipped += 1

    return {
        "ok": True,
        "emails_considered": len(seen),
        "inserted": inserted,
        "updated": updated,
        "preserved_unsub_or_suppressed": preserved,
        "skipped": skipped,
    }


def schedule_account_opt_in(db_pool, email: str, username: str = "", source: str = "account_signup") -> None:
    """Fire-and-forget from registration paths (never blocks signup)."""
    import asyncio

    if not db_pool or not normalize_email(email):
        return

    async def _run():
        await ensure_active_subscriber(
            db_pool, email, source=source, username=username
        )

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        pass
