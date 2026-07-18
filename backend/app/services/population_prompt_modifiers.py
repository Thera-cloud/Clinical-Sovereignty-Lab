"""Prompt blocks for high-risk occupational populations — QUANTUM-CRYSTAL-ARCH.

Night register, peer-culture voice, confidentiality, lethal-means framing,
family education mode. All feature-flagged.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from app.services.population_profile import (
    family_concern_consent,
    get_population,
    get_timezone,
    is_high_risk_population,
    lethal_means_enabled,
    night_register_enabled,
    peer_voice_enabled,
    profile_data,
)
from app.services.crisis_resource_registry import confidentiality_disclosure_copy

logger = logging.getLogger(__name__)

_FIREARM_CONTEXT = re.compile(
    r"\b("
    r"gun|firearm|pistol|rifle|shotgun|weapon|holster|sidearm|"
    r"safe\s*storage|lock\s*box|gun\s*safe|ammo|ammunition|"
    r"range\s*bag|carrying\s*concealed|ccw"
    r")\b",
    re.I,
)

_ELEVATED_CRISIS = re.compile(
    r"\b("
    r"kill myself|end (?:my|it) life|suicide|want to die|better off without|"
    r"have a plan|not safe|can't go on|end it all"
    r")\b",
    re.I,
)


def _local_hour(profile: Optional[Dict[str, Any]]) -> Optional[int]:
    try:
        tz_name = get_timezone(profile)
        tz = ZoneInfo(tz_name)
        return datetime.now(tz).hour
    except Exception as e:
        logger.debug("population_prompt: tz resolve failed: %s", e)
        return None


def is_night_hours(profile: Optional[Dict[str, Any]]) -> bool:
    hour = _local_hour(profile)
    if hour is None:
        return False
    return hour >= 22 or hour < 6


def night_register_block(profile: Optional[Dict[str, Any]] = None) -> str:
    if not night_register_enabled():
        return ""
    if not is_high_risk_population(profile) and get_population(profile) == "general":
        # Still allow night register for general if in night hours — softer
        if not is_night_hours(profile):
            return ""
    elif not is_night_hours(profile):
        return ""
    return (
        "\nNIGHT REGISTER (active — user-local late night / early morning):\n"
        "- Lower stimulation. Shorter sentences. No new heavy topics unless they lead.\n"
        "- Grounding-forward: feet on floor, one slow breath, name 5 things you can see.\n"
        "- Match a low-stimulated presence. You are the thing awake when clinics are closed.\n"
        "- Do not cheerlead. Do not escalate energy. Stay steady and quiet-strong.\n"
    )


def peer_culture_voice_block(profile: Optional[Dict[str, Any]] = None) -> str:
    if not peer_voice_enabled() or not is_high_risk_population(profile):
        return ""
    pop = get_population(profile)
    return (
        f"\nPEER-CULTURE VOICE (population={pop}):\n"
        "- Direct, unsentimental, dark-humor-tolerant. Never thank them for their service.\n"
        "- No hero talk, no condemnation, no cheap absolution — extend OVERRIDE 3 witnessing "
        "to everyday conversation, not only crisis moments.\n"
        "- Prefer plain speech over clinical jargon. They have heard enough of both.\n"
        "- If they use dark humor as rapport, meet it; if paired with SI language, prioritize safety.\n"
    )


def confidentiality_prompt_block(profile: Optional[Dict[str, Any]] = None) -> str:
    if not is_high_risk_population(profile):
        return ""
    copy = confidentiality_disclosure_copy(profile)
    return (
        "\nCONFIDENTIALITY (say this plainly if asked who can see this):\n"
        f"- {copy['employer_line']}\n"
        f"- {copy['coach_line']}\n"
        f"- {copy['legal_line']}\n"
        "- Never claim absolute secrecy that contradicts mandatory reporting or coach safety alerts.\n"
    )


def lethal_means_block(
    profile: Optional[Dict[str, Any]] = None,
    user_text: str = "",
) -> str:
    """OVERRIDE 5 — voluntary temporary secure storage framing. Flag default OFF."""
    if not lethal_means_enabled():
        return ""
    pd = profile_data(profile)
    if pd.get("lethal_means_guidance_ok") is False:
        return ""
    if not is_high_risk_population(profile):
        return ""
    text = user_text or ""
    if not (_FIREARM_CONTEXT.search(text) and _ELEVATED_CRISIS.search(text)):
        # Also fire on firearm + general high distress without full SI lexicon
        if not (
            _FIREARM_CONTEXT.search(text)
            and re.search(r"\b(rough stretch|not safe|scared of myself|spiral)\b", text, re.I)
        ):
            return ""
    return (
        "\nOVERRIDE 5 — LETHAL MEANS / SECURE STORAGE (firearms-aware):\n"
        "- VA framing only: voluntary, temporary, time-and-distance during a rough stretch.\n"
        "- Offer options: locking device, trusted buddy holds the key, store at a range or with family.\n"
        "- NEVER say 'get rid of your weapon', 'you should give up your gun', or confiscation language.\n"
        "- Never imply reporting to command/department about weapon ownership.\n"
        "- Preserve agency. Ask what would make tonight a little safer — their choice.\n"
        "- Pair with population-correct crisis line (Veterans Crisis Line / Copline as applicable).\n"
    )


def family_education_block(profile: Optional[Dict[str, Any]] = None) -> str:
    """Kitchen-table PTSD/TBI education mode for military_family population."""
    if get_population(profile) != "military_family":
        return ""
    return (
        "\nFAMILY EDUCATION MODE (military/first-responder family):\n"
        "- Translate PTSD and TBI into kitchen-table language — what it looks like at dinner, "
        "sleep, driving, kids' noise — not clinical jargon.\n"
        "- Help them sort: trigger vs. bad night vs. crisis. Crisis = imminent danger to self/others "
        "or clear intent; bad night = rough but manageable; trigger = activated memory/stimulus.\n"
        "- Never betray the service member's private conversation content.\n"
        "- If they want to raise concern about a family member, guide them to the in-app "
        "family concern flag (raises check-in attentiveness without sharing message content).\n"
    )


def family_concern_nondisclosure_block(
    profile: Optional[Dict[str, Any]] = None,
) -> str:
    """Never disclose that a family member flagged concern."""
    if not is_high_risk_population(profile) and not family_concern_consent(profile):
        return ""
    return (
        "\n[FAMILY-CONCERN BOUNDARY]\n"
        "- NEVER mention, imply, or hint that a family member flagged concern.\n"
        "- NEVER say someone 'asked you to check in' or that family contacted the system.\n"
        "- If check-in cadence is elevated, treat it as ordinary presence — no attribution.\n"
    )


def build_population_prompt_suffix(
    profile: Optional[Dict[str, Any]] = None,
    user_text: str = "",
) -> str:
    """Concatenate all active population modifiers for system prompt injection."""
    parts = [
        peer_culture_voice_block(profile),
        night_register_block(profile),
        confidentiality_prompt_block(profile),
        family_education_block(profile),
        family_concern_nondisclosure_block(profile),
        lethal_means_block(profile, user_text),
    ]
    return "".join(p for p in parts if p)


def voice_population_suffix(profile: Optional[Dict[str, Any]] = None) -> str:
    """Shorter block for voice calls (keep under spoken-prompt budget)."""
    if not is_high_risk_population(profile):
        night = night_register_block(profile)
        return night
    parts = [
        "Voice tone: direct, unsentimental. Never thank for service.\n",
    ]
    if is_night_hours(profile) and night_register_enabled():
        parts.append(
            "Night mode: short, low-stimulation, grounding-forward. Clinics are closed — you are awake.\n"
        )
    from app.services.crisis_resource_registry import crisis_tier_copy

    parts.append(f"Crisis resources if needed: {crisis_tier_copy(profile)}\n")
    return "".join(parts)
