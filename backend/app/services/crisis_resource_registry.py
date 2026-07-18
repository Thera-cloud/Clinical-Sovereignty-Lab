"""Population-aware crisis resource routing — QUANTUM-CRYSTAL-ARCH.

Veterans → Veterans Crisis Line (988 press 1 / text 838255)
First responders (LE) → Copline + 988
Fire/EMS → 988 + peer-oriented framing
General → 988 + Crisis Text Line 741741
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.population_profile import (
    POPULATION_FR_FIRE_EMS,
    POPULATION_FR_LE,
    POPULATION_MILITARY_FAMILY,
    POPULATION_VETERAN,
    get_population,
    population_resources_enabled,
    profile_data,
)

Resource = Dict[str, str]

_GENERIC: List[Resource] = [
    {"label": "988 Suicide & Crisis Lifeline", "action": "call_or_text", "value": "988"},
    {"label": "Crisis Text Line", "action": "text", "value": "Text HOME to 741741"},
    {"label": "Emergency", "action": "call", "value": "911"},
]

_VETERAN: List[Resource] = [
    {
        "label": "Veterans Crisis Line",
        "action": "call_or_text",
        "value": "988, press 1",
    },
    {
        "label": "Veterans Crisis Line (text)",
        "action": "text",
        "value": "Text 838255",
    },
    {"label": "Emergency", "action": "call", "value": "911"},
]

_FR_LE: List[Resource] = [
    {
        "label": "Copline (peer LE support)",
        "action": "call",
        "value": "1-800-267-5463",
    },
    {"label": "988 Suicide & Crisis Lifeline", "action": "call_or_text", "value": "988"},
    {"label": "Emergency", "action": "call", "value": "911"},
]

_FR_FIRE: List[Resource] = [
    {"label": "988 Suicide & Crisis Lifeline", "action": "call_or_text", "value": "988"},
    {
        "label": "Crisis Text Line",
        "action": "text",
        "value": "Text HOME to 741741",
    },
    {"label": "Emergency", "action": "call", "value": "911"},
]

_MIL_FAMILY: List[Resource] = [
    {
        "label": "Veterans Crisis Line (for the veteran in your life)",
        "action": "call_or_text",
        "value": "988, press 1",
    },
    {"label": "988 Suicide & Crisis Lifeline", "action": "call_or_text", "value": "988"},
    {"label": "Crisis Text Line", "action": "text", "value": "Text HOME to 741741"},
    {"label": "Emergency", "action": "call", "value": "911"},
]

_BY_POP = {
    POPULATION_VETERAN: _VETERAN,
    POPULATION_FR_LE: _FR_LE,
    POPULATION_FR_FIRE_EMS: _FR_FIRE,
    POPULATION_MILITARY_FAMILY: _MIL_FAMILY,
}

# Spoken / written blocks for post-LLM injection
_CRISIS_COPY = {
    POPULATION_VETERAN: (
        "I'm pausing our inner council work. What you shared matters. "
        "If you're in crisis, call or text the Veterans Crisis Line — 988, then press 1 "
        "(or text 838255). Staffed by people who get military life."
    ),
    POPULATION_FR_LE: (
        "I'm pausing our inner council work. What you shared matters. "
        "If you're in crisis, call Copline at 1-800-267-5463 (peer-staffed by retired LE), "
        "or call/text 988."
    ),
    POPULATION_FR_FIRE_EMS: (
        "I'm pausing our inner council work. What you shared matters. "
        "If you're in crisis, call or text 988, or text HOME to 741741."
    ),
    POPULATION_MILITARY_FAMILY: (
        "I'm pausing our inner council work. What you shared matters. "
        "If you're in crisis, call or text 988. For the veteran in your life: "
        "988, press 1 or text 838255."
    ),
}

_STABILIZATION_RESOURCES = {
    POPULATION_VETERAN: (
        "Please reach out now: Veterans Crisis Line — call or text 988, then press 1, "
        "or text 838255. Available 24/7, staffed by people trained for military populations."
    ),
    POPULATION_FR_LE: (
        "Please reach out now: Copline 1-800-267-5463 (peer LE support), "
        "or call/text 988 (Suicide & Crisis Lifeline)."
    ),
    POPULATION_FR_FIRE_EMS: (
        "Please reach out now for immediate support: Call or text 988 (Suicide & Crisis Lifeline), "
        "or text HOME to 741741 (Crisis Text Line)."
    ),
    POPULATION_MILITARY_FAMILY: (
        "Please reach out now: Call or text 988. Veterans Crisis Line for your service member: "
        "988, press 1 or text 838255."
    ),
}

_DOOR_OPEN = {
    POPULATION_VETERAN: (
        "And if things get heavier again — Veterans Crisis Line is there any time: "
        "988, press 1, or text 838255."
    ),
    POPULATION_FR_LE: (
        "And if things get heavier again — Copline (1-800-267-5463) or 988, any time."
    ),
    POPULATION_FR_FIRE_EMS: (
        "And if things get heavier again — 988 is there any time, day or night."
    ),
    POPULATION_MILITARY_FAMILY: (
        "And if things get heavier again — 988 (or 988 press 1 for Veterans Crisis Line)."
    ),
}

_GENERIC_CRISIS_COPY = (
    "I'm pausing our inner council work. What you shared matters. "
    "If you're in crisis, call or text 988 (US) or Crisis Text Line (text HOME to 741741)."
)

_GENERIC_STABILIZATION = (
    "Please reach out now for immediate support: Call or text 988 (Suicide & Crisis Lifeline), "
    "available 24/7. Or text HOME to 741741 (Crisis Text Line) for steady listening."
)

_GENERIC_DOOR = (
    "And if things get heavier again — 988 is there any time, day or night, no waiting."
)

_DETECT_PATTERNS = {
    POPULATION_VETERAN: re.compile(
        r"\b988\b.*press\s*1|\b838255\b|Veterans Crisis Line", re.I
    ),
    POPULATION_FR_LE: re.compile(
        r"\b988\b|1-800-267-5463|800-267-5463|Copline", re.I
    ),
    POPULATION_FR_FIRE_EMS: re.compile(r"\b988\b|741741", re.I),
    POPULATION_MILITARY_FAMILY: re.compile(
        r"\b988\b|838255|741741|Veterans Crisis Line", re.I
    ),
}

_GENERIC_DETECT = re.compile(r"\b988\b")
_GENERIC_741 = re.compile(r"\b741741\b|text HOME to 741741", re.I)


def get_crisis_resources(profile: Optional[Dict[str, Any]] = None) -> List[Resource]:
    if not population_resources_enabled():
        return list(_GENERIC)
    pop = get_population(profile)
    return list(_BY_POP.get(pop, _GENERIC))


def crisis_tier_copy(profile: Optional[Dict[str, Any]] = None) -> str:
    if not population_resources_enabled():
        return _GENERIC_CRISIS_COPY
    return _CRISIS_COPY.get(get_population(profile), _GENERIC_CRISIS_COPY)


def stabilization_resources_copy(profile: Optional[Dict[str, Any]] = None) -> str:
    if not population_resources_enabled():
        return _GENERIC_STABILIZATION
    return _STABILIZATION_RESOURCES.get(get_population(profile), _GENERIC_STABILIZATION)


def door_open_copy(profile: Optional[Dict[str, Any]] = None) -> str:
    if not population_resources_enabled():
        return _GENERIC_DOOR
    return _DOOR_OPEN.get(get_population(profile), _GENERIC_DOOR)


def has_crisis_resources_in_text(
    text: str,
    profile: Optional[Dict[str, Any]] = None,
) -> bool:
    body = text or ""
    if not population_resources_enabled():
        return bool(_GENERIC_DETECT.search(body) and _GENERIC_741.search(body))
    pop = get_population(profile)
    pat = _DETECT_PATTERNS.get(pop)
    if pat:
        return bool(pat.search(body))
    return bool(_GENERIC_DETECT.search(body) and _GENERIC_741.search(body))


def client_banner_message(profile: Optional[Dict[str, Any]] = None) -> str:
    pop = get_population(profile)
    if pop == POPULATION_VETERAN:
        return (
            "Your coach has been alerted. If you are in immediate danger, "
            "call or text the Veterans Crisis Line — 988, press 1, or text 838255."
        )
    if pop == POPULATION_FR_LE:
        return (
            "Your coach has been alerted. If you are in immediate danger, "
            "call Copline at 1-800-267-5463 or call/text 988."
        )
    return (
        "Your coach has been alerted. If you are in immediate danger, please reach out now."
    )


def ws_crisis_resources_payload(
    profile: Optional[Dict[str, Any]] = None,
    *,
    turn_id: str = "",
) -> Dict[str, Any]:
    return {
        "type": "crisis_resources",
        "turn_id": turn_id,
        "population": get_population(profile),
        "resources": get_crisis_resources(profile),
        "message": client_banner_message(profile),
    }


def append_missing_resources(
    text: str,
    profile: Optional[Dict[str, Any]] = None,
) -> str:
    body = (text or "").strip()
    if has_crisis_resources_in_text(body, profile):
        return body
    block = crisis_tier_copy(profile)
    if not body:
        return block
    return f"{block}\n\n{body}"


def population_label(profile: Optional[Dict[str, Any]] = None) -> str:
    return get_population(profile)


def confidentiality_disclosure_copy(profile: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """In-product confidentiality promise — architecturally accurate."""
    pd = profile_data(profile)
    shielded = bool(pd.get("population_shielded")) or get_population(profile) != "general"
    return {
        "headline": "Who can see what you tell Nate",
        "body": (
            "Nothing you tell Nate is shared with your employer, department, or command. "
            "There is no line from this platform to your agency or chain of command. "
            "Your assigned coach may receive a safety alert if you express intent to harm "
            "yourself or others — that alert goes to your coach only, never to an employer. "
            "Mandatory reporting applies only where the law requires it "
            "(e.g. imminent harm to a child or trafficking). "
            + (
                "Your account is employer-shielded: corporate sponsors cannot see your roster entry."
                if shielded
                else ""
            )
        ).strip(),
        "employer_line": "No line to employer, department, or command — ever.",
        "coach_line": "Assigned coach may receive safety alerts; they do not see every message.",
        "legal_line": "Mandatory reporting only when the law requires it.",
    }
