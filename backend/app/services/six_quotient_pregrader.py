"""
Six-Quotient Pre-Grader — mechanical rubric flags only (never scores).

Attaches attention flags for external human/model scorers. Reuses the same
anti-pattern lexicon as SixQuotientGrowthEngine / linguistic-discipline crystals.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# Shared anti-patterns (keep aligned with six_quotient_growth_engine)
_ANTIPATTERNS = {
    "banned_word": re.compile(
        r"\b(liminal|threshold|holding space|sit with that|honor your journey|"
        r"in-between space|tender|sacred ground|aching|tender place)\b",
        re.I,
    ),
    "metaphor_decode": re.compile(
        r"\b(represents?|symboliz\w+|stands for|is (really|actually) about|inner world)\b",
        re.I,
    ),
    "solution_offering": re.compile(
        r"\b(try (this|to)|consider|breathing exercise|grounding technique|coping strateg\w+|"
        r"have you tried|one thing you could|let me suggest)\b",
        re.I,
    ),
    "accommodation": re.compile(
        r"\b(absolutely|of course|let's focus on|i can give you|actionable steps|"
        r"here are some|practical approach|let me help you with)\b",
        re.I,
    ),
    "intellectualization_trap": re.compile(
        r"\b(that's a (great|excellent|interesting) (observation|insight|analysis)|"
        r"from a clinical perspective|diagnostically)\b",
        re.I,
    ),
    "generic_validation": re.compile(
        r"\b(i hear you|that must be|that sounds|i can imagine|how (brave|courageous))\b",
        re.I,
    ),
    "chatbot_cliche": re.compile(
        r"\b(as an ai|i'm here for you|thank you for sharing|it's okay to feel|"
        r"you are not alone|reach out to (a )?(hotline|professional))\b",
        re.I,
    ),
}

# Section-specific attention hints for the external scorer
_SECTION_HINTS = {
    "SQ": ["accommodation", "solution_offering"],
    "CQ": ["metaphor_decode"],
    "AQ": ["solution_offering", "chatbot_cliche", "generic_validation"],
    "IQ": ["intellectualization_trap"],
    "EQ": ["generic_validation"],
    "MQ": ["generic_validation", "solution_offering"],
}


def pregrade_response(
    *,
    scenario_id: str,
    section: str,
    client_says: str,
    response: str,
    duration_seconds: float = 0.0,
    provider: str = "",
    odpe_signal: str = "",
) -> Dict[str, Any]:
    """Return mechanical flags + attention areas. Never includes numeric scores."""
    text = response or ""
    flags: List[str] = []
    for name, pattern in _ANTIPATTERNS.items():
        if pattern.search(text):
            flags.append(name)

    empty = not text.strip()
    if empty:
        flags.append("empty_response")

    attention = [f for f in _SECTION_HINTS.get(section.upper(), []) if f in flags]
    # Always surface section-relevant patterns that fired
    for hint in _SECTION_HINTS.get(section.upper(), []):
        if hint in flags and hint not in attention:
            attention.append(hint)

    return {
        "scenario_id": scenario_id,
        "section": section,
        "duration_seconds": round(float(duration_seconds or 0), 2),
        "provider": provider or "",
        "odpe_signal": odpe_signal or "",
        "flags": flags,
        "attention_areas": attention,
        "empty_response": empty,
        "response_chars": len(text),
        "scoring_authority": "external_only",
        "note": "Pre-grader flags only — do not treat as a score",
    }


def pregrade_battery(
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Pre-grade a list of battery result dicts (mutates copies)."""
    out: List[Dict[str, Any]] = []
    for r in results:
        pg = pregrade_response(
            scenario_id=r.get("scenario_id") or r.get("id") or "",
            section=r.get("section") or "",
            client_says=r.get("client_says") or "",
            response=r.get("response") or "",
            duration_seconds=float(r.get("duration_seconds") or 0),
            provider=r.get("provider") or "",
            odpe_signal=r.get("odpe_signal") or "",
        )
        row = dict(r)
        row["pregrade"] = pg
        out.append(row)
    return out
