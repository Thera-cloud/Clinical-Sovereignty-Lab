"""Gmail drafts.create only. Never users.messages.send."""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Dict, Optional

import aiohttp

from app.services.google_workspace_service import FlagOff, VaultBlocked, client_vault_sync

logger = logging.getLogger("gmail_draft_service")

GMAIL_DRAFTS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


def _rfc822(to_email: str, subject: str, body: str) -> str:
    to_email = (to_email or "").replace("\n", " ").strip()
    subject = (subject or "").replace("\n", " ").strip()
    return (
        f"To: {to_email}\r\n"
        f"Subject: {subject}\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        f"{body or ''}"
    )


def _raw_b64(rfc822: str) -> str:
    return base64.urlsafe_b64encode(rfc822.encode("utf-8")).decode("ascii").rstrip("=")


async def gmail_create_draft(access_token: str, to_email: str, subject: str, body: str) -> Optional[str]:
    """POST /users/me/drafts only. Returns Gmail draft id or None."""
    if not access_token:
        return None
    raw = _raw_b64(_rfc822(to_email, subject, body))
    async with aiohttp.ClientSession() as session:
        async with session.post(
            GMAIL_DRAFTS_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"message": {"raw": raw}},
        ) as resp:
            text = await resp.text()
            if resp.status not in (200, 201):
                logger.warning("Gmail drafts.create failed: %d %s", resp.status, text[:200])
                return None
            data = json.loads(text) if text else {}
            return data.get("id")


async def create_coach_draft(
    db_pool,
    coach_id: str,
    payload: Dict[str, Any],
    *,
    access_token: Optional[str] = None,
) -> Dict[str, Any]:
    if not _flag_on("ENABLE_WS_GMAIL_DRAFTS"):
        raise FlagOff("ENABLE_WS_GMAIL_DRAFTS")
    coach_id = (coach_id or "").strip()
    client_id = (payload.get("client_id") or "").strip() or None
    to_email = (payload.get("to") or payload.get("to_email") or "").strip()
    subject = (payload.get("subject") or "").strip()
    body = payload.get("body") or ""
    draft_type = (payload.get("draft_type") or "session_followup").strip()

    vault_ok = True
    if client_id:
        vault_ok = await client_vault_sync(db_pool, client_id)

    body_ciphertext = None
    if client_id and body and db_pool:
        from app.services.client_envelope_cipher import encrypt_for_client
        body_ciphertext = await encrypt_for_client(db_pool, client_id, body.encode())

    status = "blocked" if (client_id and not vault_ok) else "pending"
    gmail_id = None
    if vault_ok and access_token:
        gmail_id = await gmail_create_draft(access_token, to_email, subject, body)
        if gmail_id:
            status = "pushed"

    draft_id = None
    if db_pool:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO email_drafts
                  (coach_id, client_id, draft_type, gmail_draft_id, to_email,
                   subject, body_ciphertext, status, vault_blocked)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                RETURNING id
                """,
                coach_id, client_id, draft_type, gmail_id, to_email,
                subject, body_ciphertext, status, (not vault_ok),
            )
        draft_id = str(row["id"]) if row else None

    if client_id and not vault_ok:
        raise VaultBlocked("createDraft blocked: vault_sync=false")

    return {
        "ok": True,
        "id": draft_id,
        "gmail_draft_id": gmail_id,
        "encrypted": bool(body_ciphertext),
        "status": status,
    }
