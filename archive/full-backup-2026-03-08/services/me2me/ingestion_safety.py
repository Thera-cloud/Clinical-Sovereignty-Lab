"""
Me-2-Me Platinum — Ingestion Safety
Crisis detection during Me-2-Me data ingestion.
Scans imprints for urgency red flags that need immediate attention.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("me2me.ingestion_safety")


# Crisis patterns to detect during imprint ingestion
CRISIS_PATTERNS = {
    "suicidal_ideation": [
        "want to die", "kill myself", "end it all", "no point living",
        "better off dead", "suicide plan", "can't go on",
    ],
    "self_harm": [
        "cutting myself", "hurting myself", "self-harm", "burning myself",
    ],
    "abuse_disclosure": [
        "being abused", "they hit me", "sexual abuse", "domestic violence",
        "hurt my child",
    ],
    "substance_crisis": [
        "overdose", "relapsed", "can't stop drinking", "withdrawal",
    ],
    "psychotic_features": [
        "hearing voices", "being watched", "they're following me",
        "the voices told me", "not real",
    ],
}


class IngestionSafetyService:
    """
    Scans Me-2-Me imprint content for crisis indicators.
    When detected, pauses ingestion and escalates to clinical team.
    """

    def __init__(self, notifications=None, mandatory_reporting=None):
        self._notifications = notifications
        self._reporting = mandatory_reporting

    async def scan_content(
        self,
        user_id: str,
        content: str,
        source: str = "",
    ) -> Dict[str, Any]:
        """
        Scan content for crisis indicators.
        Returns scan result with any detected flags.
        """
        result = {
            "user_id": user_id,
            "source": source,
            "safe": True,
            "flags": [],
            "severity": "none",
            "action_required": False,
        }

        lower = content.lower()

        for category, patterns in CRISIS_PATTERNS.items():
            for pattern in patterns:
                if pattern in lower:
                    result["safe"] = False
                    result["flags"].append({
                        "category": category,
                        "pattern": pattern,
                        "position": lower.index(pattern),
                    })

        if result["flags"]:
            # Determine severity
            categories = set(f["category"] for f in result["flags"])
            if "suicidal_ideation" in categories or "self_harm" in categories:
                result["severity"] = "critical"
                result["action_required"] = True
            elif "abuse_disclosure" in categories:
                result["severity"] = "high"
                result["action_required"] = True
            else:
                result["severity"] = "moderate"

            # Escalate if needed
            if result["action_required"]:
                await self._escalate(user_id, result)

            logger.warning(
                "Ingestion safety flag: user=%s severity=%s categories=%s",
                user_id, result["severity"], categories,
            )

        return result

    async def _escalate(self, user_id: str, scan_result: Dict[str, Any]) -> None:
        """Escalate a crisis detection to the clinical team."""
        if self._reporting:
            from app.models.governance import ReportingTrigger
            categories = set(f["category"] for f in scan_result["flags"])

            trigger_map = {
                "suicidal_ideation": ReportingTrigger.SELF_HARM,
                "self_harm": ReportingTrigger.SELF_HARM,
                "abuse_disclosure": ReportingTrigger.DOMESTIC_VIOLENCE,
            }

            for cat in categories:
                trigger = trigger_map.get(cat)
                if trigger:
                    try:
                        await self._reporting.screen_message(
                            user_id=user_id,
                            message=f"[Me-2-Me ingestion safety flag: {cat}]",
                        )
                    except Exception as e:
                        logger.error("Escalation failed: %s", e)

        if self._notifications:
            try:
                await self._notifications.send_notification(
                    user_id="supervisor",
                    notification_type="ingestion_safety_alert",
                    title="Me-2-Me Ingestion Safety Alert",
                    body=f"Crisis content detected during ingestion for user {user_id}. Severity: {scan_result['severity']}",
                    channel="urgent",
                )
            except Exception as e:
                logger.error("Safety notification failed: %s", e)
