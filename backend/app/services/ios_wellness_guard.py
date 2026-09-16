"""Native iOS wellness-only prompt and deterministic response guard."""

from __future__ import annotations

import re
from typing import List


IOS_WELLNESS_PROMPT = """
NATIVE iOS WELLNESS MODE — HIGHEST PRIORITY:
- You are a general wellness and coaching companion, not a clinician.
- Do not diagnose, assess symptoms, infer a disorder, prescribe, or recommend
  medication, treatment plans, dosages, or clinical interventions.
- Do not calculate, reveal, interpret, or reference biometric, emotional,
  diagnostic, risk, coherence, C_emo, or other health-related measurements.
- You may offer non-medical self-reflection, encouragement, journaling prompts,
  goal support, and general wellness conversation.
- For medical questions, state that you cannot determine health conditions and
  advise the user to seek a doctor's advice before making medical decisions.
- For imminent self-harm or violence, direct the user to 988/911 immediately.
These rules override any clinical, therapeutic, diagnostic, or treatment
instructions elsewhere in the prompt.
""".strip()


_UNSAFE_PATTERNS = (
    re.compile(
        r"\b(?:c[_ -]?emo|nevedal|coherence score|emotional coherence|"
        r"emotional score|mood score|stress level|anxiety level|risk (?:score|level|assessment)|"
        r"clinical score|biometric|voiceprint|facial geometry|health measurement)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:diagnos(?:e|ed|es|ing|is|tic)|ptsd|bipolar|schizophren\w*|ocd|"
        r"(?:anxiety|depress\w*|personality|eating|panic|trauma-related) disorder)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:take|start|stop|increase|decrease|change)\b.{0,60}\b"
        r"(?:medication|medicine|dose|dosage|prescription)\b|"
        r"\b(?:treatment plan|clinical intervention|exposure therapy|"
        r"cognitive behavioral therapy|dialectical behavior therapy|cbt|dbt|emdr)\b|"
        r"\byou should (?:see|consult|find)\b.{0,40}\b(?:psychiatrist|therapist)\b",
        re.IGNORECASE,
    ),
)

_SELF_HARM = re.compile(
    r"\b(?:kill myself|end my life|want to die|suicidal|self[- ]harm|"
    r"hurt myself|better off dead|do not want to live|don't want to live|"
    r"do not want to be alive|don't want to be alive)\b",
    re.IGNORECASE,
)
_VIOLENCE = re.compile(
    r"\b(?:kill|shoot|stab|seriously hurt)\s+(?:him|her|them|someone)\b",
    re.IGNORECASE,
)

_MEDICAL_BOUNDARY = (
    "I can help you reflect on what you're noticing, but I can't determine "
    "health conditions or tell you what medical care to follow. Seek a doctor's "
    "advice in addition to using this app and before making medical decisions. "
    "What part of this experience feels most important right now?"
)

_CRISIS_BOUNDARY = (
    "I'm glad you told me. If you may hurt yourself or someone else, call or "
    "text 988 now in the United States, or call 911 if there is immediate "
    "danger; outside the United States, contact your local emergency service. "
    "This app cannot provide emergency or medical care."
)


def find_ios_wellness_violations(
    user_text: str, response_text: str
) -> List[str]:
    """Return deterministic reasons an iOS response must be replaced."""
    if _SELF_HARM.search(user_text or "") or _VIOLENCE.search(user_text or ""):
        return ["crisis_safety_override"]
    return [
        f"unsafe_medical_output_{index}"
        for index, pattern in enumerate(_UNSAFE_PATTERNS, start=1)
        if pattern.search(response_text or "")
    ]


def enforce_ios_wellness_response(user_text: str, response_text: str) -> str:
    """Preserve safe wellness text; replace medical or crisis output."""
    violations = find_ios_wellness_violations(user_text, response_text)
    if not violations:
        return response_text
    if "crisis_safety_override" in violations:
        return _CRISIS_BOUNDARY
    return _MEDICAL_BOUNDARY
