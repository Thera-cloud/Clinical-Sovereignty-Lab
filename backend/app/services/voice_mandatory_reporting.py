"""
Therapeutic Identity Inference Engine — Phase 8b: Voice Mandatory Reporting.

Extends the existing MandatoryReportingService with voice-specific detection:
- Acoustic distress signals (elevated jitter + shimmer indicating crisis)
- Real-time transcript screening during voice calls
- Voice-specific escalation (Twilio conference bridge for live coaching)
- Minor-specific detection patterns for school/family environments
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.voice_mandatory_reporting")

VOICE_DISTRESS_PATTERNS = {
    "child_disclosure": [
        r"\b(?:he|she|they)\s+(?:touch(?:es|ed)?|hurt(?:s)?)\s+me\b",
        r"\bdon'?t\s+tell\s+(?:anyone|anybody|my\s+(?:mom|dad|parent))\b",
        r"\bhe\s+comes?\s+(?:into|in)\s+my\s+(?:room|bed)\b",
        r"\bsecret\s+(?:game|touch(?:ing)?)\b",
        r"\bscared\s+to\s+go\s+home\b",
    ],
    "active_suicidality": [
        r"\bi\s+have\s+(?:a\s+)?(?:plan|gun|pills|rope)\b",
        r"\btonight\s+(?:is|will\s+be)\s+(?:the|my)\s+last\b",
        r"\bi'?(?:m|ve)\s+(?:going\s+to|gonna)\s+(?:kill|end)\s+(?:myself|it|my\s+life)\b",
        r"\bwrote?\s+(?:a\s+)?(?:note|letter|goodbye)\b",
        r"\bgave?\s+away\s+(?:my|all)\b",
    ],
    "imminent_harm": [
        r"\bi'?(?:m|ll)\s+(?:going\s+to|gonna)\s+(?:hurt|kill|shoot|stab)\s+(?:him|her|them)\b",
        r"\bthey?\s+(?:won'?t|can'?t)\s+stop\s+me\b",
        r"\bi\s+know\s+where\s+(?:he|she|they)\s+(?:live|work|sleep)\b",
    ],
    "substance_overdose": [
        r"\bi\s+(?:took|swallowed|drank)\s+(?:too\s+many|all\s+(?:the|my))\b",
        r"\b(?:everything|room)\s+(?:is|feels?)\s+(?:spinning|fading|going\s+dark)\b",
        r"\bcan'?t\s+(?:feel|move)\s+my\b",
    ],
}

ACOUSTIC_DISTRESS_THRESHOLDS = {
    "jitter_critical": 0.025,
    "shimmer_critical": 0.08,
    "energy_collapse": 0.05,
    "pitch_variance_collapse": 5.0,
}


class VoiceMandatoryReportingDetector:
    """
    Real-time mandatory reporting detection for voice calls.

    Extends the base MandatoryReportingService with:
    1. Regex-based pattern matching on live transcripts (more nuanced than substring)
    2. Acoustic distress signal detection (jitter/shimmer/energy patterns)
    3. Contextual escalation appropriate for voice (mid-call coaching bridge)
    """

    def __init__(self, base_service=None, db_pool=None):
        self._base = base_service
        self._db = db_pool
        self._compiled_patterns = {}
        for category, patterns in VOICE_DISTRESS_PATTERNS.items():
            self._compiled_patterns[category] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]
        self._triggered_in_call: set = set()

    def screen_transcript(
        self,
        text: str,
        call_sid: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Screen a live transcript segment for mandatory reporting triggers.
        Returns detection info if triggered, None otherwise.
        Deduplicates within the same call.
        """
        lower = text.lower()

        for category, compiled in self._compiled_patterns.items():
            for pattern in compiled:
                if pattern.search(lower):
                    dedup_key = f"{call_sid}:{category}"
                    if dedup_key in self._triggered_in_call:
                        continue

                    self._triggered_in_call.add(dedup_key)
                    logger.warning(
                        "VoiceMandatoryReporting: %s detected in call %s",
                        category, call_sid,
                    )
                    return {
                        "category": category,
                        "call_sid": call_sid,
                        "pattern_matched": pattern.pattern,
                        "severity": self._severity_for(category),
                        "immediate_actions": self._actions_for(category),
                    }

        return None

    def check_acoustic_distress(
        self,
        jitter: float,
        shimmer: float,
        energy: float,
        pitch_variance: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Check acoustic features for physiological distress signals.
        High jitter + high shimmer + low energy = acute crisis.
        """
        distress_score = 0.0

        if jitter > ACOUSTIC_DISTRESS_THRESHOLDS["jitter_critical"]:
            distress_score += 0.3
        if shimmer > ACOUSTIC_DISTRESS_THRESHOLDS["shimmer_critical"]:
            distress_score += 0.3
        if energy < ACOUSTIC_DISTRESS_THRESHOLDS["energy_collapse"]:
            distress_score += 0.2
        if pitch_variance < ACOUSTIC_DISTRESS_THRESHOLDS["pitch_variance_collapse"]:
            distress_score += 0.2

        if distress_score >= 0.6:
            return {
                "type": "acoustic_distress",
                "score": distress_score,
                "indicators": {
                    "jitter": jitter,
                    "shimmer": shimmer,
                    "energy": energy,
                    "pitch_variance": pitch_variance,
                },
            }

        return None

    async def escalate_voice_call(
        self,
        call_sid: str,
        user_id: str,
        category: str,
        detection_source: str = "voice_ai",
    ) -> None:
        """
        Escalate a voice call detection to the base mandatory reporting service
        and log the voice-specific context.
        """
        if self._base:
            try:
                await self._base.screen_message(
                    user_id=user_id,
                    message=f"[VOICE DETECTION] {category} detected during live call {call_sid}",
                    session_id=call_sid,
                )
            except Exception as e:
                logger.error("Voice mandatory reporting escalation failed: %s", e)

        if self._db:
            try:
                await self._db.execute(
                    """INSERT INTO voice_mandatory_reporting_events
                       (call_sid, user_id, category, detection_source, detected_at)
                       VALUES ($1, $2, $3, $4, NOW())
                       ON CONFLICT DO NOTHING""",
                    call_sid, user_id, category, detection_source,
                )
            except Exception as e:
                logger.warning("Voice reporting event log failed: %s", e)

    def reset_for_call(self, call_sid: str) -> None:
        """Clear deduplication state for a new call."""
        self._triggered_in_call = {
            k for k in self._triggered_in_call
            if not k.startswith(f"{call_sid}:")
        }

    def _severity_for(self, category: str) -> str:
        return {
            "child_disclosure": "critical",
            "active_suicidality": "critical",
            "imminent_harm": "critical",
            "substance_overdose": "high",
        }.get(category, "high")

    def _actions_for(self, category: str) -> List[str]:
        return {
            "child_disclosure": [
                "Maintain calm, supportive presence",
                "Do NOT probe for details beyond what's disclosed",
                "Notify assigned coach IMMEDIATELY",
                "File CPS report within 24 hours",
                "Document disclosure verbatim",
            ],
            "active_suicidality": [
                "Provide 988 Suicide & Crisis Lifeline",
                "Assess for immediate means access",
                "Do NOT end the call until safety plan is confirmed",
                "Notify assigned coach IMMEDIATELY",
                "If imminent danger, guide caller to call 911",
            ],
            "imminent_harm": [
                "Tarasoff duty: identifiable potential victim must be warned",
                "Notify assigned coach IMMEDIATELY",
                "Notify clinical supervisor",
                "Document specific threat details",
            ],
            "substance_overdose": [
                "Assess consciousness and breathing",
                "Guide caller (or someone nearby) to call 911",
                "Provide SAMHSA helpline: 1-800-662-4357",
                "Stay on line until help arrives if possible",
            ],
        }.get(category, ["Notify assigned coach"])
