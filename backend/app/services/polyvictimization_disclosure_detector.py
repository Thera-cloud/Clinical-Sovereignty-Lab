"""Polyvictimization Disclosure Detector.

Disambiguates a `past_tense`-classified trafficking signal (see
`trafficking_disclosure_classifier.py`) between two very different clinical
realities that share overlapping surface language:

1. A genuine historical trafficking/exploitation disclosure (survivor
   describing being trafficked, exploited, or sold in the past) — this
   should keep flowing through the existing `mandatory_reporting` /
   trafficking-specific tiers untouched.

2. A historical family-of-origin / childhood sexual or physical abuse
   disclosure that merely uses generic past-tense trauma language ("when I
   was young", "years ago when...") which the trafficking classifier's
   broad temporal patterns can over-fire on. Labeling this as a critical
   `mandatory_reporting` "trafficking" alert to the coach is clinically
   misleading and creates unnecessary triage confusion (see the LetsGoLisa
   incident, 2026-07).

This module NEVER downgrades `imminent_danger`, `active_situation`, or
`survivor_as_recruiter` — it is only consulted for the ambiguous
`past_tense` case, and only when no explicit trafficking/exploitation
language is present. It is deliberately conservative: any exploitation
marker short-circuits to `None` (defer to the existing trafficking path).

This is additive-only. It does not modify
`trafficking_disclosure_classifier.py` or the mandatory reporting screen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

__all__ = [
    "PolyvictimDisclosureSuggestion",
    "detect_historical_family_pattern",
]


@dataclass(frozen=True)
class PolyvictimDisclosureSuggestion:
    """Result of the disambiguation check.

    `layer_type` matches the CHECK constraint on
    `user_polyvictimization_layers.layer_type` (migration 206).
    """

    layer_type: str
    suggested_severity: str
    matched_relation: str
    matched_abuse_term: str
    has_childhood_context: bool


# Exploitation / trafficking-specific markers. Presence of ANY of these
# means the disclosure is NOT a candidate for downgrade — defer to the
# existing trafficking-tier routing in `_build_handoff_if_needed`.
_EXPLOITATION_MARKERS = re.compile(
    r"\b("
    r"traffick\w*"
    r"|pimp\w*"
    r"|john\b"
    r"|buyer\w*"
    r"|sold\s+(me|us|her|him)"
    r"|the\s+life\b"
    r"|escort\w*"
    r"|brothel\w*"
    r"|forced\s+labor"
    r"|smuggl\w*"
    r"|recruit\w*"
    r"|debt\s+bondage"
    r"|commercial\s+sex"
    r"|sex\s+work\w*"
    r"|exploit\w*"
    r"|quota\b"
    r"|made\s+me\s+(sleep\s+with|have\s+sex\s+with)"
    r"|forced\s+(me\s+)?to\s+have\s+sex"
    r"|took\s+my\s+(passport|id|documents)"
    r")\b",
    re.IGNORECASE,
)

# Family-of-origin relational terms. "step" may appear as its own word
# ("step father") or fused ("stepfather") — the optional group covers both.
_FAMILY_RELATION = re.compile(
    r"\bmy\s+(step[\s-]?)?(father|mother|dad|mom|uncle|aunt|grandfather|"
    r"grandmother|grandpa|grandma|brother|sister|cousin)\b",
    re.IGNORECASE,
)

# Abuse-describing verbs/nouns (non-exploitation framing).
_ABUSE_TERM = re.compile(
    r"\b(molest\w*|abus\w*|touch(ed|ing)?\s+me|rape\w*|assault\w*|"
    r"hit\s+me|beat\s+me|hurt\s+me)\b",
    re.IGNORECASE,
)

# Childhood temporal context — boosts confidence but is not required on
# its own (the classifier's own past-tense floor already requires some
# temporal marker to have fired).
_CHILDHOOD_CONTEXT = re.compile(
    r"\b(when\s+i\s+was\s+(a\s+)?(kid|little|young|child)|"
    r"as\s+a\s+(kid|child)|growing\s+up|my\s+childhood|"
    r"when\s+i\s+was\s+\d{1,2}\b)",
    re.IGNORECASE,
)


def detect_historical_family_pattern(
    message: str,
) -> Optional[PolyvictimDisclosureSuggestion]:
    """Return a suggestion when `message` reads as a historical
    family-of-origin abuse disclosure rather than a trafficking disclosure.

    Returns None when:
      - the message is empty, OR
      - any exploitation/trafficking marker is present (defer — do not
        downgrade a genuine trafficking signal), OR
      - no family-relation + abuse-term combination is found.
    """
    if not message or not message.strip():
        return None

    if _EXPLOITATION_MARKERS.search(message):
        return None

    relation_match = _FAMILY_RELATION.search(message)
    abuse_match = _ABUSE_TERM.search(message)
    if not relation_match or not abuse_match:
        return None

    has_childhood_context = bool(_CHILDHOOD_CONTEXT.search(message))

    return PolyvictimDisclosureSuggestion(
        layer_type="childhood_abuse",
        suggested_severity="high",
        matched_relation=relation_match.group(0).lower(),
        matched_abuse_term=abuse_match.group(0).lower(),
        has_childhood_context=has_childhood_context,
    )
