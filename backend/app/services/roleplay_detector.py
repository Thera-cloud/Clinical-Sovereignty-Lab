"""
Therapeutic Identity Inference Engine — Phase 4d: Role-Play Detector.

Distinguishes therapeutic role-play (intentional) from identity masking
(deceptive). Critical for schools and prisons where clients may adopt
another persona to avoid surveillance or test the system.

Surveillance Awareness Index (SAI): estimates whether the caller is
modifying their behavior due to perceived monitoring.
"""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.roleplay_detector")

ROLEPLAY_CUES = [
    "pretend i'm", "let's say i'm", "imagine i'm", "role play",
    "act like", "what if i was", "speaking as", "in character",
    "let me be", "as if i were", "playing the part",
]

MASKING_INDICATORS = [
    "this isn't me", "i'm someone else", "don't tell them",
    "they're listening", "off the record", "between us",
    "can they hear", "is this recorded", "who's watching",
    "i'm not really", "fake name",
]

SURVEILLANCE_CUES = [
    "are you recording", "is this confidential", "who can see this",
    "is anyone listening", "is this private", "can my counselor see",
    "will this be reported", "is this monitored", "off the record",
    "between you and me", "don't tell my", "keep this secret",
]

THIRD_PERSON_PATTERNS = [
    re.compile(r"\b(my friend|someone i know|this person|a guy i know)\b", re.I),
    re.compile(r"\bhypothetically\b", re.I),
    re.compile(r"\basking for a friend\b", re.I),
]


@dataclass
class RolePlayAssessment:
    """Assessment of whether current speech is role-play, masking, or authentic."""
    mode: str = "authentic"  # authentic, therapeutic_roleplay, masking, uncertain
    confidence: float = 0.5
    roleplay_cues_detected: List[str] = field(default_factory=list)
    masking_cues_detected: List[str] = field(default_factory=list)
    surveillance_awareness_index: float = 0.0
    third_person_deflection: bool = False
    identity_exclusion_active: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "confidence": round(self.confidence, 3),
            "roleplay_cues": self.roleplay_cues_detected,
            "masking_cues": self.masking_cues_detected,
            "sai": round(self.surveillance_awareness_index, 3),
            "third_person": self.third_person_deflection,
            "identity_excluded": self.identity_exclusion_active,
        }


class RolePlayDetector:
    """
    Detects and distinguishes therapeutic role-play from identity masking.

    Therapeutic role-play (DOJO scenarios, EFT exercises) is legitimate and
    should be excluded from identity inference. Identity masking (pretending
    to be someone else to avoid accountability) should trigger investigation.

    The Surveillance Awareness Index (SAI) tracks how much the caller's
    behavior suggests they believe they're being monitored — important for
    corrections and school environments where trust is conditional.
    """

    def __init__(self, deployment_context: str = "default"):
        self._context = deployment_context
        self._roleplay_cue_count = 0
        self._masking_cue_count = 0
        self._surveillance_cue_count = 0
        self._total_turns = 0
        self._third_person_count = 0
        self._active_roleplay = False
        self._history = deque(maxlen=50)

    def analyze_turn(self, text: str) -> RolePlayAssessment:
        """Analyze a conversation turn for role-play and masking signals."""
        text_lower = text.lower()
        self._total_turns += 1
        assessment = RolePlayAssessment()

        for cue in ROLEPLAY_CUES:
            if cue in text_lower:
                assessment.roleplay_cues_detected.append(cue)
                self._roleplay_cue_count += 1

        for indicator in MASKING_INDICATORS:
            if indicator in text_lower:
                assessment.masking_cues_detected.append(indicator)
                self._masking_cue_count += 1

        surv_hits = 0
        for cue in SURVEILLANCE_CUES:
            if cue in text_lower:
                surv_hits += 1
                self._surveillance_cue_count += 1

        for pat in THIRD_PERSON_PATTERNS:
            if pat.search(text):
                assessment.third_person_deflection = True
                self._third_person_count += 1
                break

        if self._total_turns > 0:
            assessment.surveillance_awareness_index = min(
                1.0, self._surveillance_cue_count / max(self._total_turns, 1) * 5
            )

        if assessment.roleplay_cues_detected:
            assessment.mode = "therapeutic_roleplay"
            assessment.confidence = 0.8
            assessment.identity_exclusion_active = True
            self._active_roleplay = True
        elif assessment.masking_cues_detected:
            assessment.mode = "masking"
            assessment.confidence = 0.7
        elif self._active_roleplay and not self._is_roleplay_exit(text_lower):
            assessment.mode = "therapeutic_roleplay"
            assessment.confidence = 0.6
            assessment.identity_exclusion_active = True
        elif assessment.third_person_deflection:
            assessment.mode = "uncertain"
            assessment.confidence = 0.4
        else:
            assessment.mode = "authentic"
            assessment.confidence = 0.85
            if self._active_roleplay and self._is_roleplay_exit(text_lower):
                self._active_roleplay = False

        self._history.append(assessment)
        return assessment

    def _is_roleplay_exit(self, text_lower: str) -> bool:
        exit_cues = [
            "back to me", "that's enough", "ok me again",
            "stop the roleplay", "end the exercise", "as myself",
            "i'm me again", "drop the character",
        ]
        return any(cue in text_lower for cue in exit_cues)

    @property
    def identity_inference_excluded(self) -> bool:
        """True when identity inference should be paused (active role-play)."""
        return self._active_roleplay

    @property
    def sai(self) -> float:
        if self._total_turns == 0:
            return 0.0
        return min(1.0, self._surveillance_cue_count / max(self._total_turns, 1) * 5)

    def get_identity_weight_adjustment(self) -> Dict[str, float]:
        """
        Returns weight adjustments for the identity inference engine
        based on detected role-play/masking state.
        """
        if self._active_roleplay:
            return {"voice": 0.0, "linguistic": 0.0, "narrative": 0.0}

        sai = self.sai
        if sai > 0.5:
            return {"voice": 1.0, "linguistic": 0.7, "narrative": 0.5}

        return {"voice": 1.0, "linguistic": 1.0, "narrative": 1.0}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_turns": self._total_turns,
            "roleplay_cues": self._roleplay_cue_count,
            "masking_cues": self._masking_cue_count,
            "surveillance_cues": self._surveillance_cue_count,
            "third_person_count": self._third_person_count,
            "active_roleplay": self._active_roleplay,
            "sai": round(self.sai, 3),
            "deployment_context": self._context,
        }
