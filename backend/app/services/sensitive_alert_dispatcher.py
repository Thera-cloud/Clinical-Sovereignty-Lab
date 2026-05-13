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
    }

    redacted_context: Optional[str] = None
    if raw_context:
        try:
            from app.services.pii_redaction import redact_conversation_turns
            redacted = redact_conversation_turns(
                turns=[{"role": "system", "content": raw_context}],
                coach_username=coach_username or "",
                client_username=client_username,
            )
            redacted_context = redacted[0].get("content", raw_context) if redacted else raw_context
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

    if coach_username and receipt["event_id"]:
        try:
            from app.services.notifications_service import EmailService
            email_svc = EmailService()
            await email_svc.send_crisis_alert(
                coach_username=coach_username,
                client_username=client_username,
                risk_level=risk_level,
                reason=reason,
            )
            receipt["coach_notified"] = True
        except Exception as e:
            logger.warning("sensitive_alert_dispatcher: coach notification failed: %s", e)

    return receipt
