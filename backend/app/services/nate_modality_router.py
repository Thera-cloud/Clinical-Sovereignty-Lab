"""QUANTUM-CRYSTAL-ARCH — Therapeutic modality router for clinical coevolution.

Precedence (live): crisis > enrolled Sensitive Bridge framework lens > router.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

CRISIS_RE = re.compile(
    r"\b(suicid|kill myself|end my life|want to die|self[- ]?harm|"
    r"hurt myself|overdose|no reason to live)\b",
    re.I,
)
AMBIVALENCE_RE = re.compile(
    r"\b(i don'?t know if|maybe i should|part of me|on the (one|other) hand|"
    r"not sure (if|whether)|conflicted)\b",
    re.I,
)
CBT_RE = re.compile(
    r"\b(always|never|everyone|nobody|should|must|catastroph|"
    r"all[- ]or[- ]nothing|i'?m (a )?failure)\b",
    re.I,
)
ACT_RE = re.compile(
    r"\b(avoid|can'?t feel|numb|push(ing)? (it |them )?away|"
    r"won'?t think about|escape)\b",
    re.I,
)
DISTRESS_RE = re.compile(
    r"\b(overwhelm|panic|can'?t breathe|falling apart|meltdown|"
    r"out of control|too much)\b",
    re.I,
)


@dataclass
class ModalityDecision:
    modality: str
    tactic: str
    reason: str
    source: str  # crisis | framework_lens | router


def route_modality(
    user_text: str,
    *,
    profile: Optional[Mapping[str, Any]] = None,
    distress_hint: float = 0.0,
) -> ModalityDecision:
    text = (user_text or "").strip()
    profile = profile or {}

    if CRISIS_RE.search(text) or distress_hint >= 0.85:
        return ModalityDecision(
            modality="crisis_intervention",
            tactic="safety_first_then_dbt_distress_tolerance",
            reason="crisis_or_high_distress",
            source="crisis",
        )

    # Enrolled Sensitive Bridge framework lens
    pd = profile.get("profile_data") if isinstance(profile.get("profile_data"), dict) else profile
    if not isinstance(pd, dict):
        pd = {}
    sc = pd.get("sensitive_clinical") if isinstance(pd.get("sensitive_clinical"), dict) else {}
    lens_on = bool(sc.get("v1_4_framework_lens_enabled") or pd.get("v1_4_framework_lens_enabled"))
    framework = (
        sc.get("selected_framework")
        or pd.get("selected_framework")
        or pd.get("framework_lens")
        or ""
    )
    if lens_on and framework:
        fw = str(framework).strip().upper().replace(" ", "_")
        return ModalityDecision(
            modality=fw,
            tactic="stay_within_enrolled_framework",
            reason="enrolled_framework_lens",
            source="framework_lens",
        )

    if DISTRESS_RE.search(text) or distress_hint >= 0.6:
        return ModalityDecision(
            modality="DBT",
            tactic="distress_tolerance_then_emotion_regulation",
            reason="elevated_distress",
            source="router",
        )
    if AMBIVALENCE_RE.search(text):
        return ModalityDecision(
            modality="MI",
            tactic="elicit_change_talk_roll_with_resistance",
            reason="ambivalence",
            source="router",
        )
    if ACT_RE.search(text):
        return ModalityDecision(
            modality="ACT",
            tactic="defusion_values_committed_action",
            reason="experiential_avoidance",
            source="router",
        )
    if CBT_RE.search(text):
        return ModalityDecision(
            modality="CBT",
            tactic="thought_record_gentle_reframe",
            reason="rigid_thought_loops",
            source="router",
        )
    return ModalityDecision(
        modality="DBT",
        tactic="validate_then_skill_probe",
        reason="default_clinical",
        source="router",
    )


def modality_addendum(decision: ModalityDecision) -> str:
    return (
        f"\n[CLINICAL MODALITY — {decision.modality} via {decision.source}]\n"
        f"Primary tactic: {decision.tactic}. Reason: {decision.reason}. "
        f"Crisis/safety always overrides bakeoff incentives.\n"
    )
