"""
Therapeutic Identity Inference Engine — Phases 8c/8d/8e.

Age-Aware Response Calibration: adjusts language complexity, technique
selection, and therapeutic approach based on caller age tier.

Corrections Environment Mode: monitored call awareness, present-focused
therapy, confidentiality disclosure.

Adolescent Voice Maturation: wider acceptance thresholds for voice
identity when the caller is 13-17 (vocal cords still developing).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.age_calibration")


@dataclass
class AgeCalibrationConfig:
    """Age-tier-specific therapeutic configuration."""
    age_tier: str  # child, adolescent, adult
    language_complexity: str  # simplified, moderate, full
    max_sentence_length: int = 20
    use_metaphors: bool = True
    use_clinical_terminology: bool = False
    confrontation_allowed: bool = False
    voice_identity_threshold_multiplier: float = 1.0
    techniques: list = field(default_factory=list)
    system_prompt_addendum: str = ""


CHILD_CONFIG = AgeCalibrationConfig(
    age_tier="child",
    language_complexity="simplified",
    max_sentence_length=12,
    use_metaphors=True,
    use_clinical_terminology=False,
    confrontation_allowed=False,
    voice_identity_threshold_multiplier=1.5,
    techniques=["play_therapy_narrative", "feelings_vocabulary", "scaling_simple", "storytelling"],
    system_prompt_addendum=(
        "You are speaking with a child (under 13). "
        "Use simple, warm language. Avoid clinical terms. "
        "Use stories, metaphors, and feelings words they can understand. "
        "Never confront or interpret — just listen and reflect. "
        "Keep responses to 1-2 short sentences."
    ),
)

ADOLESCENT_CONFIG = AgeCalibrationConfig(
    age_tier="adolescent",
    language_complexity="moderate",
    max_sentence_length=16,
    use_metaphors=True,
    use_clinical_terminology=False,
    confrontation_allowed=False,
    voice_identity_threshold_multiplier=1.3,
    techniques=["motivational_interviewing", "cbt_simplified", "narrative_therapy", "strengths_based"],
    system_prompt_addendum=(
        "You are speaking with an adolescent (13-17). "
        "Be authentic and direct without being clinical. "
        "Avoid sounding like a parent or authority figure. "
        "Use their language when appropriate. "
        "Respect their autonomy — suggest, don't prescribe. "
        "Keep responses to 2-3 sentences."
    ),
)

ADULT_CONFIG = AgeCalibrationConfig(
    age_tier="adult",
    language_complexity="full",
    max_sentence_length=25,
    use_metaphors=True,
    use_clinical_terminology=True,
    confrontation_allowed=True,
    voice_identity_threshold_multiplier=1.0,
    techniques=["full_range"],
    system_prompt_addendum="",
)

AGE_CONFIGS = {
    "child": CHILD_CONFIG,
    "adolescent": ADOLESCENT_CONFIG,
    "adult": ADULT_CONFIG,
}


@dataclass
class CorrectionsConfig:
    """Configuration for corrections (prison) environment."""
    monitored: bool = True
    present_focused: bool = True
    confidentiality_disclosure: str = (
        "I want to be upfront with you — this call may be monitored as part "
        "of facility policy. What we talk about is still between us therapeutically, "
        "but I want you to know the environment so you can share at whatever "
        "level feels right."
    )
    avoid_topics: list = field(default_factory=lambda: [
        "escape plans", "security vulnerabilities", "facility layout",
    ])
    system_prompt_addendum: str = (
        "CORRECTIONS ENVIRONMENT — PRESENT-FOCUSED THERAPY:\n"
        "- You are speaking with someone in a correctional facility.\n"
        "- Focus on present coping, emotional regulation, and future planning.\n"
        "- Do NOT explore past criminal activity in detail — focus on the emotional impact.\n"
        "- Be aware that calls may be monitored. Do not ask the caller to share anything\n"
        "  they wouldn't want overheard.\n"
        "- The caller may have surveillance awareness (SAI) — they may test or withhold.\n"
        "  Meet this with patience, not suspicion.\n"
        "- Confidentiality has limits in this setting. If asked, be honest about them.\n"
        "- Reverb and background noise are normal. Do not interpret audio artifacts\n"
        "  as emotional signals."
    )


class AgeAppropriateCalibrator:
    """
    Selects and applies age-appropriate therapeutic configuration.
    Handles child, adolescent, and adult tiers with environment overlays.
    """

    def __init__(self):
        self._corrections_config = CorrectionsConfig()

    def get_config(
        self,
        user_age: Optional[int] = None,
        deployment_context: str = "default",
    ) -> AgeCalibrationConfig:
        if user_age is None or user_age >= 18:
            return ADULT_CONFIG
        if user_age >= 13:
            return ADOLESCENT_CONFIG
        return CHILD_CONFIG

    def get_system_prompt_overlay(
        self,
        user_age: Optional[int] = None,
        deployment_context: str = "default",
    ) -> str:
        """
        Build system prompt additions for age and environment.
        Returns empty string for default adult context.
        """
        parts = []

        config = self.get_config(user_age, deployment_context)
        if config.system_prompt_addendum:
            parts.append(config.system_prompt_addendum)

        if deployment_context == "prison":
            parts.append(self._corrections_config.system_prompt_addendum)

        return "\n\n".join(parts)

    def get_voice_identity_threshold_multiplier(
        self,
        user_age: Optional[int] = None,
    ) -> float:
        """
        Returns a multiplier for voice identity thresholds.
        Adolescents get wider thresholds (1.3x) due to vocal maturation.
        Children get even wider (1.5x).
        """
        config = self.get_config(user_age)
        return config.voice_identity_threshold_multiplier

    def get_corrections_disclosure(self) -> str:
        return self._corrections_config.confidentiality_disclosure

    def should_disclose_monitoring(self, deployment_context: str) -> bool:
        return deployment_context == "prison"
