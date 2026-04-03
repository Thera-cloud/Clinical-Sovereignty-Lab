"""
Therapeutic Identity Inference Engine — Phase 6: Gentle Investigation.

When identity confidence is below HIGH, Nate performs a therapeutic
investigation — not interrogation. Five pre-checks gate whether
investigation is appropriate, and the approach uses clinical skill
rather than security protocol.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.gentle_investigation")

INVESTIGATION_QUESTIONS = {
    "calibration_check": [
        "I want to make sure I'm giving you the best support — is this {name} I'm speaking with?",
        "Just checking in — I want to make sure my memory is calibrated to the right person. Is this {name}?",
    ],
    "context_probe": [
        "Last time we talked about something that really stayed with me. Do you remember what that was?",
        "I've been thinking about what you shared in our last conversation. Want to pick up where we left off?",
    ],
    "relationship_verification": [
        "You mentioned someone important to you — your {relationship}. How are things going there?",
    ],
    "gentle_redirect": [
        "I'm noticing your voice sounds a little different today. Everything okay?",
        "You sound different than I remember — is everything alright?",
    ],
    "open_invitation": [
        "What's bringing you to call today?",
        "What's on your mind right now?",
    ],
}


@dataclass
class InvestigationPlan:
    """Plan for a gentle identity investigation."""
    should_investigate: bool = False
    reason: str = ""
    urgency: str = "low"  # low, medium, high
    approach: str = "calibration_check"
    question_template: str = ""
    pre_check_results: Dict[str, bool] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_investigate": self.should_investigate,
            "reason": self.reason,
            "urgency": self.urgency,
            "approach": self.approach,
            "question_template": self.question_template,
            "pre_checks": self.pre_check_results,
        }


class GentleInvestigationEngine:
    """
    Manages the therapeutic identity investigation process.

    Five pre-checks must pass before investigation is triggered:
    1. Arousal check — is the caller in crisis? (never investigate during crisis)
    2. Network check — is the QoS degraded? (wider tolerance)
    3. Role-play check — is the caller in a therapeutic exercise?
    4. Calibration check — does the enrollment profile have enough data?
    5. Genetic proximity — are the top candidates family members?
    """

    def __init__(self):
        self._investigations: Dict[str, List[InvestigationPlan]] = {}
        self._cooldown_s = 300.0
        self._last_investigation: Dict[str, float] = {}

    def evaluate(
        self,
        call_sid: str,
        identity_confidence: float,
        identity_candidates: List[Dict[str, Any]],
        crisis_active: bool = False,
        qos_degraded: bool = False,
        roleplay_active: bool = False,
        enrollment_tier: str = "NONE",
        candidates_are_family: bool = False,
        expected_user: Optional[str] = None,
    ) -> InvestigationPlan:
        """
        Run the 5 pre-checks and determine if/how to investigate.
        """
        plan = InvestigationPlan()

        pre_checks = {
            "arousal_safe": not crisis_active,
            "network_adequate": not qos_degraded,
            "not_roleplay": not roleplay_active,
            "enrollment_sufficient": enrollment_tier in ("LOW", "MEDIUM", "HIGH"),
            "genetic_proximity_clear": not candidates_are_family,
        }
        plan.pre_check_results = pre_checks

        if crisis_active:
            plan.should_investigate = False
            plan.reason = "crisis_active — identity investigation deferred"
            return plan

        if roleplay_active:
            plan.should_investigate = False
            plan.reason = "roleplay_active — identity paused"
            return plan

        now = time.time()
        last = self._last_investigation.get(call_sid, 0)
        if now - last < self._cooldown_s:
            plan.should_investigate = False
            plan.reason = "cooldown_active"
            return plan

        if identity_confidence >= 0.75:
            plan.should_investigate = False
            plan.reason = "confidence_high"
            return plan

        plan.should_investigate = True

        if candidates_are_family:
            plan.approach = "gentle_redirect"
            plan.urgency = "medium"
            plan.reason = "family_member_ambiguity"
            questions = INVESTIGATION_QUESTIONS["gentle_redirect"]
        elif identity_confidence < 0.30:
            plan.approach = "calibration_check"
            plan.urgency = "high"
            plan.reason = "very_low_confidence"
            questions = INVESTIGATION_QUESTIONS["calibration_check"]
        elif identity_confidence < 0.50:
            plan.approach = "context_probe"
            plan.urgency = "medium"
            plan.reason = "moderate_confidence"
            questions = INVESTIGATION_QUESTIONS["context_probe"]
        else:
            plan.approach = "open_invitation"
            plan.urgency = "low"
            plan.reason = "slightly_below_threshold"
            questions = INVESTIGATION_QUESTIONS["open_invitation"]

        plan.question_template = questions[0] if questions else ""

        if expected_user:
            plan.context["expected_user"] = expected_user
            plan.question_template = plan.question_template.replace("{name}", expected_user)

        if qos_degraded:
            plan.urgency = "low"

        self._last_investigation[call_sid] = now
        return plan

    def format_investigation_prompt(self, plan: InvestigationPlan) -> str:
        """
        Generate a system prompt injection for the identity investigation.
        Nate asks therapeutically, never interrogatively.
        """
        if not plan.should_investigate:
            return ""

        lines = [
            "\nIDENTITY CALIBRATION (handle naturally — NOT as interrogation):",
            f"- Reason: {plan.reason}",
            f"- Approach: Use a {plan.approach} question.",
        ]

        if plan.question_template:
            lines.append(f"- Suggested question: \"{plan.question_template}\"")

        lines.extend([
            "- Weave the question into natural conversation flow.",
            "- If the caller confirms their identity, continue normally.",
            "- If the caller indicates they are someone else, warmly acknowledge",
            "  and adjust your context: 'Oh, I'm so glad you called! Let me make",
            "  sure I have the right context for you.'",
            "- NEVER accuse, interrogate, or make the caller feel unwelcome.",
        ])

        return "\n".join(lines)
