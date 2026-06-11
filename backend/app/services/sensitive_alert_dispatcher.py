"""Canonical Sensitive Bridge v1.4+ alert dispatch (Gap 6).

This is the ONLY module the orchestrator imports for crisis/addiction/trafficking
alerts. It composes: pii_redaction, crisis_events_writer, notifications_service.

Orchestrator code MUST NOT import notify_coach, crisis_events_writer, or
pii_redaction directly — they flow through this dispatcher.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def dispatch_sensitive_alert(
    *,
    db_pool: Any,
    client_username: str,
    coach_username: Optional[str],
    risk_level: str,
    reason: str,
    keywords: Optional[List[str]] = None,
    session_id: Optional[str] = None,
    family_id: Optional[str] = None,
    raw_context: Optional[str] = None,
    alert_type: str = "addiction_escalation",
    suppress_voice: bool = False,
) -> Dict[str, Any]:
    """Dispatch a sensitive clinical alert through the canonical pipeline.

    Steps:
        1. PII-redact raw_context (if provided)
        2. Write crisis_events row
        3. Notify coach via notifications_service (crisis_alert template)
        4. Return receipt dict with event_id and delivery status

    Returns dict with keys: event_id (int), coach_notified (bool), redacted (bool)
    """
    receipt: Dict[str, Any] = {
        "event_id": 0,
        "coach_notified": False,
        "redacted": False,
        "alert_type": alert_type,
        "notification_id": 0,
        "email_sent": False,
    }

    redacted_context: Optional[str] = None
    if raw_context:
        try:
            from app.services.pii_redaction import redact_pii

            redacted = redact_pii(
                [{"role": "system", "content": raw_context}],
                coach_username=coach_username or "",
                client_username=client_username,
            )
            redacted_context = (
                redacted[0].get("content", raw_context) if redacted else raw_context
            )
            receipt["redacted"] = True
        except Exception as e:
            logger.warning("sensitive_alert_dispatcher: PII redaction failed: %s", e)
            redacted_context = "[redaction_failed]"

    try:
        from app.services.crisis_events_writer import write_crisis_event
        event_id = await write_crisis_event(
            pool=db_pool,
            client_username=client_username,
            user_display_name=client_username,
            risk_level=risk_level,
            reason=reason,
            keywords=keywords,
            session_id=session_id,
            family_id=family_id,
            bridge_row_notes=redacted_context,
        )
        receipt["event_id"] = event_id
    except Exception as e:
        logger.error("sensitive_alert_dispatcher: crisis event write failed: %s", e)

    coach_email: Optional[str] = None
    if db_pool and coach_username:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT profile_data->>'email' AS email
                      FROM users
                     WHERE username = $1 AND role IN ('COACH', 'ADMIN')
                    """,
                    coach_username,
                )
            if row and row["email"]:
                coach_email = str(row["email"]).strip() or None
        except Exception as e:
            logger.warning("sensitive_alert_dispatcher: coach email lookup failed: %s", e)

    details_body = reason
    if redacted_context:
        details_body = f"{reason}\n\n{redacted_context}"
    if alert_type == "client_initiated_handoff" and not suppress_voice:
        details_body += (
            "\n\nThe client has been notified that you were contacted "
            "by email and phone."
        )

    if coach_username and receipt["event_id"]:
        try:
            from app.services.coach_notifications import notify_coach

            handoff = alert_type == "client_initiated_handoff"
            urg = (
                "critical" if risk_level in ("emergency", "critical") else "high"
            )
            if handoff:
                notif_subject = "Sovereign Sanctuary · Client requested coach contact"
                msg = reason
                if redacted_context:
                    msg += f"\n\nConversation context:\n{redacted_context}"
                msg = (
                    f"{msg}\n\n(This is a client-initiated coach handoff, not a crisis alert.)"
                )
                if not suppress_voice:
                    msg += (
                        "\n\nThe client has been notified that you were contacted "
                        "by email and phone."
                    )
            else:
                notif_subject = f"Sovereign Sanctuary · {alert_type}"
                msg = f"[{alert_type}] client={client_username}\n{reason}"
                if redacted_context:
                    msg += f"\n\nContext:\n{redacted_context}"
            notif = await notify_coach(
                db_pool,
                coach_username,
                {
                    "urgency": urg,
                    "subject": notif_subject,
                    "message": msg[:4000],
                    "payload": {
                        "alert_type": alert_type,
                        "event_id": receipt["event_id"],
                        "risk_level": risk_level,
                        "session_id": session_id,
                        "suppress_voice": suppress_voice,
                    },
                },
            )
            nid = int(notif.get("notification_id") or notif.get("id") or 0)
            receipt["notification_id"] = nid
            receipt["coach_notified"] = nid > 0 or bool(
                (notif.get("sent") or {}).get("in_app")
            )
        except Exception as e:
            logger.warning("sensitive_alert_dispatcher: coach notify_coach failed: %s", e)

        if coach_email:
            try:
                from app.services.notifications_service import EmailService

                email_svc = EmailService()
                if alert_type == "client_initiated_handoff":
                    ok = await email_svc.send_coach_handoff_request(
                        coach_email,
                        client_username,
                        details_body[:7500],
                    )
                else:
                    ok = await email_svc.send_crisis_alert(
                        coach_email,
                        client_username,
                        alert_type,
                        details_body[:7500],
                    )
                receipt["email_sent"] = bool(ok)
            except Exception as e:
                logger.warning("sensitive_alert_dispatcher: coach email failed: %s", e)

    return receipt


async def emit_addiction_alert(**kwargs: Any) -> Dict[str, Any]:
    return await dispatch_sensitive_alert(alert_type="addiction_escalation", **kwargs)


async def emit_trafficking_alert(**kwargs: Any) -> Dict[str, Any]:
    return await dispatch_sensitive_alert(alert_type="trafficking_escalation", **kwargs)


async def emit_codeword_disclosure_alert(**kwargs: Any) -> Dict[str, Any]:
    return await dispatch_sensitive_alert(alert_type="codeword_disclosure", **kwargs)
