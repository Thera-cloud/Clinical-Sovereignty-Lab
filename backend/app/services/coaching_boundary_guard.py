"""Training Ground pre-LLM coaching boundary guard — QUANTUM-CRYSTAL-ARCH."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.services.suicide_ideation_lexicon import match_user_text

TripClass = str  # CRISIS | DEPTH | HYPO

_DEPTH_PATTERNS: List[tuple[str, re.Pattern[str]]] = [
    ("unburden_exile", re.compile(r"\bunburden(?:ing)?\b.*\bexile\b|\bexile\b.*\bunburden", re.I)),
    ("childhood_trauma", re.compile(r"\b(childhood|early)\b.*\b(trauma|abuse|wound)", re.I)),
    ("shadow_excavation", re.compile(r"\b(shadow|inner child)\b.*\b(process|excavat|dig)", re.I)),
    ("trauma_processing", re.compile(r"\b(process|go back to)\b.*\b(trauma|abuse|childhood)", re.I)),
]

_HYPO_PATTERNS: List[tuple[str, re.Pattern[str]]] = [
    ("numb_flat", re.compile(r"\b(numb|flattened|empty inside|nothing matters)\b", re.I)),
    ("collapse", re.compile(r"\b(can't feel|cannot feel|shut down completely|gone blank)\b", re.I)),
    ("dissociation_hint", re.compile(r"\b(not really here|floating away|watching myself)\b", re.I)),
]


@dataclass
class GuardResult:
    tripped: bool = False
    trip_class: Optional[TripClass] = None
    trigger_class: Optional[str] = None
    matched_labels: List[str] = field(default_factory=list)
    priority: int = 3

    @property
    def show_crisis_resources(self) -> bool:
        return self.trip_class == "CRISIS"


def _match_patterns(text: str, patterns: List[tuple[str, re.Pattern[str]]]) -> Optional[str]:
    for label, pattern in patterns:
        if pattern.search(text):
            return label
    return None


def evaluate(user_text: str) -> GuardResult:
    """Sync classifier — must run before any LLM on Training Ground turns."""
    if not user_text or not str(user_text).strip():
        return GuardResult(tripped=False)

    sample = str(user_text)
    crisis_hits = match_user_text(sample)
    if crisis_hits:
        return GuardResult(
            tripped=True,
            trip_class="CRISIS",
            trigger_class=crisis_hits[0],
            matched_labels=list(crisis_hits),
            priority=1,
        )

    depth_hit = _match_patterns(sample, _DEPTH_PATTERNS)
    if depth_hit:
        return GuardResult(
            tripped=True,
            trip_class="DEPTH",
            trigger_class=depth_hit,
            matched_labels=[depth_hit],
            priority=3,
        )

    hypo_hit = _match_patterns(sample, _HYPO_PATTERNS)
    if hypo_hit:
        return GuardResult(
            tripped=True,
            trip_class="HYPO",
            trigger_class=hypo_hit,
            matched_labels=[hypo_hit],
            priority=2,
        )

    return GuardResult(tripped=False)


TIER_COPY = {
    "CRISIS": (
        "I'm pausing our inner council work. What you shared matters. "
        "If you're in crisis, call or text 988 (US) or Crisis Text Line (text HOME to 741741)."
    ),
    "DEPTH": (
        "This inner mapping space isn't the place for trauma processing or exile healing work. "
        "We can note what surfaced and return to naming parts and dialogue skills."
    ),
    "HYPO": (
        "Let's slow down. When things feel flat or far away, stabilization comes first — "
        "not pushing deeper into parts work."
    ),
}
