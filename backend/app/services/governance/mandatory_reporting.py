"""
SOVEREIGN SWARM — Mandatory Reporting Protocol
Handles detection and escalation of mandatory reporting situations.

Operational Specifications §5.2 — Mandatory Reporting.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.governance import MandatoryReportingProtocol, ReportingTrigger

logger = logging.getLogger("governance.mandatory_reporting")


# =============================================================================
# DETECTION PATTERNS
# =============================================================================

TRIGGER_PATTERNS = {
    ReportingTrigger.CHILD_ABUSE: [
        "hitting my child", "hit my kid", "beat my child", "hurting my child",
        "child abuse", "my child has bruises", "someone is hurting my child",
    ],
    ReportingTrigger.ELDER_ABUSE: [
        "neglecting my parent", "elder abuse", "taking their money",
        "not feeding them", "locking them in",
    ],
    ReportingTrigger.SELF_HARM: [
        "kill myself", "suicide", "want to die", "end my life",
        "self harm", "cut myself", "hurt myself", "don't want to be alive",
        "better off dead", "plan to die",
    ],
    ReportingTrigger.HARM_TO_OTHERS: [
        "kill someone", "going to hurt", "want to harm",
        "plan to attack", "going to shoot",
    ],
    ReportingTrigger.DOMESTIC_VIOLENCE: [
        "partner hits me", "spouse beat me", "domestic violence",
        "being abused", "they choked me", "afraid to go home",
    ],
    ReportingTrigger.SUBSTANCE_CRISIS: [
        "overdose", "od'd", "can't stop using", "need a fix",
        "withdrawal symptoms", "relapsed", "shooting up",
        "drinking myself to death", "blacked out",
        "mixing drugs", "fentanyl", "took too many pills",
    ],
}


class MandatoryReportingService:
    """
    Detects mandatory reporting triggers and manages the
    escalation chain.
    """

    def __init__(self, db_pool=None, notifications=None):
        self._db = db_pool
        self._notifications = notifications

    async def screen_message(
        self,
        user_id: str,
        message: str,
        session_id: Optional[str] = None,
        coach_id: Optional[str] = None,
    ) -> Optional[MandatoryReportingProtocol]:
        """Screen a message for mandatory reporting triggers."""
        lower = message.lower()

        for trigger, patterns in TRIGGER_PATTERNS.items():
            for pattern in patterns:
                if pattern in lower:
                    protocol = await self._create_protocol(
                        trigger=trigger,
                        user_id=user_id,
                        session_id=session_id,
                        coach_id=coach_id,
                        detection_source="ai_detection",
                    )
                    await self._execute_escalation(protocol)
                    return protocol

        return None

    async def coach_report(
        self,
        trigger: ReportingTrigger,
        user_id: str,
        coach_id: str,
        session_id: Optional[str] = None,
        details: str = "",
    ) -> MandatoryReportingProtocol:
        """Process a mandatory report filed by a coach."""
        protocol = await self._create_protocol(
            trigger=trigger,
            user_id=user_id,
            session_id=session_id,
            coach_id=coach_id,
            detection_source="coach_flag",
        )
        await self._execute_escalation(protocol)
        return protocol

    async def _create_protocol(
        self,
        trigger: ReportingTrigger,
        user_id: str,
        session_id: Optional[str],
        coach_id: Optional[str],
        detection_source: str,
    ) -> MandatoryReportingProtocol:
        """Create and persist a mandatory reporting protocol."""
        # Determine severity
        severity = "critical" if trigger in (
            ReportingTrigger.SELF_HARM,
            ReportingTrigger.HARM_TO_OTHERS,
            ReportingTrigger.CHILD_ABUSE,
        ) else "high"

        protocol = MandatoryReportingProtocol(
            trigger=trigger,
            detection_source=detection_source,
            user_id=user_id,
            session_id=session_id,
            coach_id=coach_id,
            severity=severity,
            immediate_actions=self._get_immediate_actions(trigger),
            escalation_chain=self._get_escalation_chain(trigger),
        )

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO mandatory_reporting_protocols
                        (protocol_id, trigger, detection_source, user_id, session_id, coach_id, severity)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        protocol.protocol_id, trigger.value, detection_source,
                        user_id, session_id, coach_id, severity,
                    )
            except Exception as e:
                logger.error("Protocol persistence failed: %s", e)

        logger.warning(
            "Mandatory reporting protocol created: trigger=%s user=%s severity=%s",
            trigger.value, user_id, severity,
        )
        return protocol

    async def _execute_escalation(
        self, protocol: MandatoryReportingProtocol
    ) -> None:
        """Execute the escalation chain for a protocol."""
        # Step 1: Notify assigned coach immediately
        if protocol.coach_id and self._notifications:
            try:
                await self._notifications.send_notification(
                    user_id=protocol.coach_id,
                    notification_type="mandatory_reporting_alert",
                    title=f"MANDATORY REPORTING: {protocol.trigger.value.upper()}",
                    body=(
                        f"A {protocol.trigger.value} concern has been detected for your client. "
                        f"Immediate review required."
                    ),
                    channel="urgent",
                )
                protocol.coach_notified = True
                protocol.coach_notified_at = datetime.utcnow()
            except Exception as e:
                logger.error("Coach notification failed: %s", e)

        # Step 2: Notify supervisor
        if self._notifications:
            try:
                await self._notifications.send_notification(
                    user_id="supervisor",
                    notification_type="mandatory_reporting_supervisor",
                    title=f"Mandatory Report: {protocol.trigger.value}",
                    body=f"User: {protocol.user_id}, Coach: {protocol.coach_id}, Severity: {protocol.severity}",
                    channel="urgent",
                )
                protocol.supervisor_notified = True
            except Exception as e:
                logger.error("Supervisor notification failed: %s", e)

    def _get_immediate_actions(self, trigger: ReportingTrigger) -> List[str]:
        """Get immediate actions for a trigger type."""
        actions = {
            ReportingTrigger.SELF_HARM: [
                "Provide crisis line: 988 Suicide & Crisis Lifeline",
                "Notify assigned coach immediately",
                "Assess for immediate safety plan",
                "Do not end session without safety confirmation",
            ],
            ReportingTrigger.HARM_TO_OTHERS: [
                "Notify assigned coach immediately",
                "Assess specific threat details",
                "Tarasoff duty: warn identifiable potential victims",
            ],
            ReportingTrigger.CHILD_ABUSE: [
                "Notify assigned coach immediately",
                "File CPS report within 24 hours",
                "Document all disclosed information",
            ],
            ReportingTrigger.ELDER_ABUSE: [
                "Notify assigned coach immediately",
                "File APS report",
                "Document all disclosed information",
            ],
            ReportingTrigger.DOMESTIC_VIOLENCE: [
                "Assess immediate safety",
                "Provide DV hotline: 1-800-799-7233",
                "Notify assigned coach",
                "Create safety plan if not already in place",
            ],
            ReportingTrigger.SUBSTANCE_CRISIS: [
                "Provide SAMHSA helpline: 1-800-662-4357",
                "Assess for overdose risk",
                "Notify assigned coach immediately",
                "Connect with crisis intervention if active overdose",
            ],
        }
        return actions.get(trigger, ["Notify assigned coach"])

    def _get_escalation_chain(self, trigger: ReportingTrigger) -> List[str]:
        """Get the escalation chain for a trigger type."""
        return [
            "assigned_coach",
            "clinical_supervisor",
            "platform_administrator",
        ]
