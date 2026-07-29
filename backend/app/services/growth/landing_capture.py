"""Public landing capture → landing_captures + SendGrid product drip.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("nate.growth.landing")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ALLOWED = frozenset({"providers", "enterprise"})


async def capture_landing(
    db_pool,
    *,
    landing: str,
    email: str,
    name: Optional[str] = None,
    org: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    honeypot: str = "",
) -> Dict[str, Any]:
    if honeypot:
        return {"ok": True, "status": "ignored"}  # bot
    landing = (landing or "").strip().lower()
    if landing not in ALLOWED:
        raise ValueError("invalid landing")
    email_norm = (email or "").strip().lower()
    if not _EMAIL_RE.match(email_norm):
        raise ValueError("invalid email")

    async with db_pool.acquire() as conn:
        suppressed = await conn.fetchval(
            "SELECT 1 FROM outreach_suppression WHERE email_norm = $1", email_norm
        )
        if suppressed:
            return {"ok": True, "status": "suppressed"}
        row = await conn.fetchrow(
            """
            INSERT INTO landing_captures (landing, email_norm, name, org, meta, drip_status)
            VALUES ($1,$2,$3,$4,$5::jsonb,'pending')
            RETURNING id
            """,
            landing,
            email_norm,
            (name or "")[:120] or None,
            (org or "")[:200] or None,
            json.dumps(meta or {}),
        )
        capture_id = int(row["id"])

    drip = await _send_product_drip(
        email_norm, name=name or "", landing=landing, capture_id=capture_id
    )
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE landing_captures SET drip_status = $2 WHERE id = $1",
            capture_id,
            drip.get("status") or "error",
        )
        if drip.get("status") == "sent":
            await conn.execute(
                """
                INSERT INTO marketing_content (
                    content_type, platform, audience, title, draft_body,
                    status, generation_meta, created_by, published_at
                ) VALUES (
                    'email_drip', 'sendgrid', $1, $2, $3, 'published',
                    $4::jsonb, 'landing_capture', NOW()
                )
                """,
                landing,
                f"Landing drip — {landing}",
                drip.get("body") or "",
                json.dumps(
                    {
                        "capture_id": capture_id,
                        "email_norm": email_norm,
                        "provider": "sendgrid",
                    }
                ),
            )
    return {"ok": True, "capture_id": capture_id, "drip": drip}


async def _send_product_drip(
    email: str, *, name: str, landing: str, capture_id: int
) -> Dict[str, Any]:
    subject = (
        "Thanks for exploring Sovereign Sanctuary for providers"
        if landing == "providers"
        else "Thanks for exploring Sovereign Sanctuary for teams"
    )
    body = (
        f"Hi {name or 'there'},\n\n"
        f"Thanks for your interest via our {landing} page. "
        "A member of our team can walk you through Sanctuary when you're ready.\n\n"
        "— Sovereign Sanctuary\n"
        "This is a product email (SendGrid), not a cold outreach sequence."
    )
    html = f"<pre style='font-family:system-ui'>{body}</pre>"
    api_key = (os.getenv("SENDGRID_API_KEY") or "").strip()
    if not api_key:
        return {"status": "skipped", "reason": "SENDGRID_API_KEY unset", "body": body}
    from_email = os.getenv("FROM_EMAIL", "support@sovereignsanctuary.net")
    payload = {
        "personalizations": [{"to": [{"email": email}]}],
        "from": {"email": from_email, "name": "Sovereign Sanctuary"},
        "subject": subject,
        "content": [{"type": "text/html", "value": html}],
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if resp.status_code in (200, 202):
            return {"status": "sent", "body": body, "capture_id": capture_id}
        return {
            "status": "error",
            "error": f"sendgrid {resp.status_code}",
            "body": body,
        }
    except Exception as e:
        logger.warning("landing drip send failed: %s", e)
        return {"status": "error", "error": str(e)[:200], "body": body}
