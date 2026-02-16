"""
HIVE DEFENSE v4.3 — Family Session Guardian (Window 4)
Protects family sessions from manipulation and power dynamics.

Detects:
1. Fishing: one member trying to extract information about another
2. Minor pressure: adult applying inappropriate pressure to a minor
3. Power dynamics: one member dominating or controlling the session
4. Gaslighting patterns: denying another member's stated experience
"""

import logging
import re
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("family_session_guardian")

# ─── Detection Patterns ──────────────────────────────────────────────────────

FISHING_PATTERNS = [
    r"\bwhat\s+did\s+(?:he|she|they)\s+(?:say|tell|share)\b",
    r"\bwhat\s+does\s+(?:he|she|they)\s+think\s+about\b",
    r"\bdid\s+(?:he|she|they)\s+mention\b",
    r"\bwhat\s+happened\s+in\s+(?:his|her|their)\s+session\b",
    r"\btell\s+me\s+what\s+(?:he|she|they)\s+said\b",
    r"\bhas\s+(?:he|she|they)\s+been\s+talking\s+about\b",
]

MINOR_PRESSURE_PATTERNS = [
    r"\byou\s+(?:have|need)\s+to\s+tell\b",
    r"\bstop\s+(?:lying|crying|whining|complaining)\b",
    r"\bif\s+you\s+don'?t\b.{0,30}(?:consequence|trouble|punish)",
    r"\byou'?re\s+(?:making|being)\s+(?:difficult|impossible|dramatic)\b",
    r"\bgrow\s+up\b",
    r"\bact\s+your\s+age\b",
]

POWER_DYNAMICS = [
    r"\bshut\s+up\b",
    r"\byou\s+always\b.{0,30}\byou\s+never\b",
    r"\beveryone\s+(?:knows|agrees|thinks)\b",
    r"\byou'?re\s+the\s+(?:problem|reason|cause)\b",
    r"\bdon'?t\s+(?:interrupt|talk|speak)\b",
    r"\bi\s+(?:decide|control|say\s+what\s+happens)\b",
]

GASLIGHTING_PATTERNS = [
    r"\bthat\s+(?:never|didn'?t)\s+happen\b",
    r"\byou'?re\s+(?:imagining|making|exaggerating)\b",
    r"\byou'?re\s+(?:crazy|insane|paranoid|delusional)\b",
    r"\bi\s+never\s+said\s+that\b",
    r"\byou'?re\s+(?:too|being)\s+sensitive\b",
    r"\bthat'?s\s+not\s+(?:what|how)\s+(?:happened|it\s+was)\b",
]


class FamilySessionGuardian:
    """Monitors family sessions for manipulation and power dynamics."""

    def __init__(self, db_pool=None):
        self._db = db_pool
        self._session_alerts: Dict[str, List[Dict]] = {}

    def analyze_utterance(
        self, session_id: str, speaker_id: str, speaker_role: str,
        text: str, target_id: str = "", target_is_minor: bool = False,
    ) -> Dict[str, Any]:
        """
        Analyze a single utterance in a family session.
        Returns detected issues with severity.
        """
        issues = []

        # Fishing detection
        for pattern in FISHING_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                issues.append({
                    "type": "fishing",
                    "severity": "medium",
                    "speaker": speaker_id,
                    "pattern": pattern,
                })
                break

        # Minor pressure detection (only if target is a minor)
        if target_is_minor:
            for pattern in MINOR_PRESSURE_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    issues.append({
                        "type": "minor_pressure",
                        "severity": "high",
                        "speaker": speaker_id,
                        "target": target_id,
                        "pattern": pattern,
                    })
                    break

        # Power dynamics
        for pattern in POWER_DYNAMICS:
            if re.search(pattern, text, re.IGNORECASE):
                issues.append({
                    "type": "power_dynamics",
                    "severity": "medium",
                    "speaker": speaker_id,
                    "pattern": pattern,
                })
                break

        # Gaslighting
        for pattern in GASLIGHTING_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                issues.append({
                    "type": "gaslighting",
                    "severity": "high",
                    "speaker": speaker_id,
                    "pattern": pattern,
                })
                break

        # Track session-level alerts
        if issues:
            if session_id not in self._session_alerts:
                self._session_alerts[session_id] = []
            self._session_alerts[session_id].extend(issues)

            max_severity = max(i["severity"] for i in issues)
            if max_severity == "high":
                _logger.warning(
                    "FAMILY SESSION ALERT [%s]: %d issues (speaker=%s)",
                    session_id[:8], len(issues), speaker_id[:8],
                )

        return {
            "issues_found": len(issues),
            "issues": issues,
            "session_total_alerts": len(self._session_alerts.get(session_id, [])),
            "safe": len(issues) == 0,
        }

    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """Get a summary of all alerts for a family session."""
        alerts = self._session_alerts.get(session_id, [])

        if not alerts:
            return {"session_id": session_id, "total_alerts": 0, "safe": True}

        by_type = {}
        by_severity = {"high": 0, "medium": 0, "low": 0}
        by_speaker = {}

        for alert in alerts:
            alert_type = alert["type"]
            by_type[alert_type] = by_type.get(alert_type, 0) + 1
            by_severity[alert.get("severity", "low")] += 1
            speaker = alert.get("speaker", "unknown")
            by_speaker[speaker] = by_speaker.get(speaker, 0) + 1

        return {
            "session_id": session_id,
            "total_alerts": len(alerts),
            "by_type": by_type,
            "by_severity": by_severity,
            "by_speaker": by_speaker,
            "safe": len(alerts) == 0,
            "requires_intervention": by_severity.get("high", 0) >= 3,
        }

    def clear_session(self, session_id: str) -> None:
        """Clear tracking data for a finished session."""
        self._session_alerts.pop(session_id, None)
