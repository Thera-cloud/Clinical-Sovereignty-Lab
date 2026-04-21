"""
SendGrid Inbound Parse Webhook
==============================

Receives parsed email replies sent to ``*@reply.sovereignsanctuary.net``
and dispatches them to the correct subsystem:

1. **Strategy proposal replies** (APPROVE / HOLD / REJECT / MODIFY) →
   :class:`ApprovalProtocolService.handle_inbound_reply` — closes the
   approval loop the proposal email opened.

2. **Daily check-in replies** (free-text responses to Little Nate's
   check-ins, sent to ``checkin@reply.sovereignsanctuary.net``) →
   ``checkin_wisdom`` table for context injection.

DNS:    MX on ``reply.sovereignsanctuary.net`` → ``mx.sendgrid.net`` (10)
SendGrid: Inbound Parse hostname ``reply.sovereignsanctuary.net``
Webhook URL: ``POST /api/webhooks/sendgrid/inbound``

Routing rules (most specific first):
    * Recipient local-part ``approve`` (``approve@reply…``) → approval pipeline.
    * First non-blank line starts with ``APPROVE/REJECT/HOLD/MODIFY`` (or
      synonym) AND a proposal id can be recovered from the subject
      ``[#shortid]`` token / body — approval pipeline.
    * Otherwise → check-in pipeline (legacy behavior).
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Request, Response

logger = logging.getLogger("nate.sendgrid_inbound")

router = APIRouter(prefix="/api/webhooks/sendgrid", tags=["webhooks"])

SENDGRID_INBOUND_SECRET = os.getenv("SENDGRID_INBOUND_SECRET", "")

# Mirror of ``twilio_webhook.APPROVAL_PREFIXES`` / ``APPROVAL_SYNONYMS`` so
# the email path recognizes the exact same vocabulary as SMS.
_APPROVAL_PREFIXES: Tuple[str, ...] = ("APPROVE", "REJECT", "HOLD", "MODIFY")
_APPROVAL_SYNONYMS = {
    "YES", "GO", "DO IT", "SHIP IT", "APPROVED",
    "WAIT", "DEFER", "LATER", "PAUSE",
    "NO", "NOPE", "DENIED", "CANCEL",
}

# "approve", "approve+anything", "approval" all route to the approval pipeline.
_APPROVAL_LOCAL_PARTS = re.compile(r"^(approve|approval)(\+[^@]*)?$", re.IGNORECASE)

_QUOTED_REPLY_PATTERNS = [
    re.compile(r"^On .+ wrote:$", re.MULTILINE),
    re.compile(r"^-{3,}\s*Original Message\s*-{3,}$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^>{1,2}\s", re.MULTILINE),
    re.compile(r"^From:\s", re.MULTILINE),
]

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


def _strip_quoted_reply(text: str) -> str:
    """Remove quoted reply text below separator lines."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if any(p.match(line.strip()) for p in _QUOTED_REPLY_PATTERNS[:2]):
            break
        if line.strip().startswith(">"):
            continue
        cleaned.append(line)
    result = "\n".join(cleaned).strip()
    return result if result else text.strip()


def _first_meaningful_line(text: str) -> str:
    """Return the first non-blank, non-quoted line — what the operator typed."""
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(">"):
            return stripped
    return ""


def _matches_approval_keyword(line: str) -> bool:
    """``True`` if ``line`` looks like an APPROVE / REJECT / HOLD / MODIFY reply."""
    if not line:
        return False
    upper = line.upper().strip()
    if upper.startswith(_APPROVAL_PREFIXES):
        return True
    # Strip trailing punctuation so "YES." / "GO!" still match.
    bare = re.sub(r"[^\w ]+$", "", upper).strip()
    return bare in _APPROVAL_SYNONYMS


def _extract_local_part(address: str) -> str:
    """Pull the ``local`` out of ``local@host`` or ``Name <local@host>``."""
    if not address:
        return ""
    m = _EMAIL_RE.search(address)
    email = m.group(0) if m else address
    return email.split("@", 1)[0].strip().lower()


async def _route_proposal_reply(
    db_pool,
    sender_email: str,
    subject: str,
    cleaned_body: str,
) -> Optional[dict]:
    """Hand an approval reply off to ``ApprovalProtocolService``.

    Returns the service's result dict on success, ``None`` on failure
    (lets the caller decide whether to fall through to check-in routing).
    """
    if not db_pool:
        logger.warning("SendGrid inbound: no db_pool — cannot process approval reply")
        return None

    try:
        from app.services.approval_protocol import ApprovalProtocolService
    except Exception as e:  # pragma: no cover — import errors are fatal
        logger.warning("SendGrid inbound: failed to import ApprovalProtocolService: %s", e)
        return None

    service = ApprovalProtocolService(db_pool)

    short_id = ApprovalProtocolService.extract_proposal_id_from_text(subject, cleaned_body)
    full_uuid: Optional[UUID] = None
    if short_id:
        try:
            full_uuid = await service._resolve_short_proposal_id(short_id)
        except Exception as e:
            logger.warning("SendGrid inbound: short-id lookup failed for %s: %s", short_id, e)

    # Final fallback: if no id was recoverable, the service still resolves
    # to the most-recent pending proposal — the same behavior SMS gets.
    try:
        result = await service.handle_inbound_reply(
            raw_message=cleaned_body or "",
            channel="email",
            proposal_id=full_uuid,
            approver_identity=sender_email,
        )
    except Exception as e:
        logger.warning("SendGrid inbound: handle_inbound_reply raised: %s", e)
        return None

    logger.info(
        "SendGrid inbound: proposal reply '%s' from %s → %s for %s",
        result.get("decision"),
        sender_email,
        result.get("proposal_id"),
        short_id or "(most-recent-pending)",
    )
    return result


async def _route_checkin_reply(
    db_pool,
    sender_email: str,
    cleaned_text: str,
) -> None:
    """Original behavior: store the reply against the user's most recent check-in."""
    if not db_pool:
        logger.warning("SendGrid inbound: no db_pool available")
        return

    try:
        async with db_pool.acquire() as conn:
            user_row = await conn.fetchrow(
                "SELECT username, role FROM users WHERE LOWER(profile_data->>'email') = LOWER($1)",
                sender_email,
            )
            if not user_row:
                logger.info("SendGrid inbound: no user found for email %s", sender_email)
                return

            username = user_row["username"]
            role = user_row["role"]

            checkin_row = await conn.fetchrow("""
                SELECT id FROM nate_checkins
                WHERE user_id = $1 AND status = 'sent'
                  AND created_at > NOW() - INTERVAL '7 days'
                ORDER BY created_at DESC LIMIT 1
            """, username)

            checkin_id = checkin_row["id"] if checkin_row else None

            if checkin_row:
                await conn.execute("""
                    UPDATE nate_checkins SET status = 'responded', responded_at = NOW()
                    WHERE id = $1
                """, checkin_id)

            await conn.execute("""
                INSERT INTO checkin_wisdom (user_id, role, checkin_id, channel, response_text)
                VALUES ($1, $2, $3, 'email', $4)
            """, username, role, checkin_id, cleaned_text[:5000])

            logger.info(
                "SendGrid inbound: stored check-in reply from %s (checkin=%s)",
                username,
                str(checkin_id)[:8] if checkin_id else "none",
            )
    except Exception as e:
        logger.warning("SendGrid inbound: DB error: %s", e)


@router.post("/inbound")
async def handle_sendgrid_inbound(request: Request):
    """Receive parsed email from SendGrid Inbound Parse and dispatch."""

    if SENDGRID_INBOUND_SECRET:
        secret_param = request.query_params.get("secret", "")
        if secret_param != SENDGRID_INBOUND_SECRET:
            logger.warning("SendGrid inbound: invalid secret")
            return Response(status_code=403)

    try:
        form_data = await request.form()
    except Exception as e:
        logger.warning("SendGrid inbound: failed to parse form data: %s", e)
        return Response(status_code=400)

    sender_email_raw = (form_data.get("from") or "").strip()
    recipient_raw = (form_data.get("to") or "").strip()
    subject = (form_data.get("subject") or "").strip()
    text_body = form_data.get("text") or form_data.get("html") or ""

    if not sender_email_raw or not text_body:
        logger.info("SendGrid inbound: empty sender or body")
        return Response(status_code=200)

    email_match = _EMAIL_RE.search(sender_email_raw)
    if not email_match:
        logger.info(
            "SendGrid inbound: could not extract email from '%s'",
            sender_email_raw[:50],
        )
        return Response(status_code=200)

    sender_email = email_match.group(0).lower()
    cleaned_text = _strip_quoted_reply(str(text_body))

    if len(cleaned_text) < 1:
        logger.info("SendGrid inbound: reply empty after stripping")
        return Response(status_code=200)

    db_pool = getattr(router, "_db_pool", None)

    # ─── FIX 1: dispatch on recipient + keyword ──────────────────────────
    recipient_local = _extract_local_part(recipient_raw)
    first_line = _first_meaningful_line(cleaned_text)
    keyword_hit = _matches_approval_keyword(first_line)
    routed_to_approval = False

    if _APPROVAL_LOCAL_PARTS.match(recipient_local) or keyword_hit:
        result = await _route_proposal_reply(
            db_pool=db_pool,
            sender_email=sender_email,
            subject=subject,
            cleaned_body=cleaned_text,
        )
        if result and "error" not in result:
            routed_to_approval = True
        else:
            # If the reply LOOKED like an approval (recipient was approve@…)
            # but no pending proposal could be matched, do not silently
            # double-route to check-in — leave a log breadcrumb instead.
            if _APPROVAL_LOCAL_PARTS.match(recipient_local):
                logger.info(
                    "SendGrid inbound: approve@ reply from %s could not be "
                    "matched to a pending proposal (subject=%r)",
                    sender_email,
                    subject[:80],
                )
                return Response(status_code=200)

    if routed_to_approval:
        return Response(status_code=200)

    # ─── Legacy: free-text reply → daily check-in pipeline ───────────────
    if len(cleaned_text) < 3:
        logger.info("SendGrid inbound: reply too short for check-in routing")
        return Response(status_code=200)

    await _route_checkin_reply(db_pool, sender_email, cleaned_text)
    return Response(status_code=200)
