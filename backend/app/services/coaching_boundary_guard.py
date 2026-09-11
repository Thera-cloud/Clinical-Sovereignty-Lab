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
    # QUANTUM-CRYSTAL-ARCH growth-phase gating: labels that matched but were
    # suppressed (retrospective/celebration wound language, negated HYPO,
    # coaching phase). Persisted for observability; never mutate the response.
    suppressed_labels: List[str] = field(default_factory=list)
    suppress_reason: Optional[str] = None

    @property
    def show_crisis_resources(self) -> bool:
        return self.trip_class == "CRISIS"


def _match_patterns(text: str, patterns: List[tuple[str, re.Pattern[str]]]) -> Optional[str]:
    for label, pattern in patterns:
        if pattern.search(text):
            return label
    return None


# ---------------------------------------------------------------------------
# Growth-phase gating (2026-09 LetsGoLisa regression: celebration messages such
# as "healing wounds from childhood trauma ... I've forgiven Bill" tripped
# `childhood_trauma` DEPTH for weeks and LN kept inserting boundary copy while
# the client was announcing she was healed.)
# ---------------------------------------------------------------------------

_COACHING_PHASES = frozenset({"consolidate", "thrive", "generative"})


def _lexicon():
    from app.services.thrive import growth_phase as _gp

    return _gp


def _any(patterns, text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def _depth_suppressed(sample: str, phase: Optional[str], sub_state: Optional[str]) -> Optional[str]:
    """Return a reason string when a DEPTH match should NOT trip."""
    try:
        gp = _lexicon()
    except Exception:
        return None
    if sub_state == "working_through":
        # Client asked to go there — the guard must not slam the door.
        return "working_through"
    asks_to_process = _any(gp.WORK_THROUGH_REQUEST, sample)
    retrospective = _any(gp.RETROSPECTIVE_WOUND, sample)
    forward = _any(gp.FORWARD_DECLARATION, sample)
    if retrospective and not asks_to_process:
        return "retrospective_wound_language"
    if forward and not asks_to_process:
        return "forward_declaration"
    if (phase or "") in _COACHING_PHASES and not asks_to_process:
        return f"phase:{phase}"
    return None


def _hypo_suppressed(sample: str) -> Optional[str]:
    try:
        gp = _lexicon()
    except Exception:
        return None
    if _any(gp.NEGATED_HYPO, sample):
        return "negated_hypo"
    return None


def evaluate(
    user_text: str,
    *,
    growth_phase: Optional[str] = None,
    growth_sub_state: Optional[str] = None,
) -> GuardResult:
    """Sync classifier — must run before any LLM on Training Ground turns.

    growth_phase / growth_sub_state (optional, QUANTUM-CRYSTAL-ARCH): when the
    caller knows the client's phase, DEPTH is gated so consolidating/thriving
    clients naming old wounds in the past tense are met as healed, not
    redirected. CRISIS is never gated.
    """
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

    suppressed: List[str] = []
    reason: Optional[str] = None

    depth_hit = _match_patterns(sample, _DEPTH_PATTERNS)
    if depth_hit:
        why = _depth_suppressed(sample, growth_phase, growth_sub_state)
        if why is None:
            return GuardResult(
                tripped=True,
                trip_class="DEPTH",
                trigger_class=depth_hit,
                matched_labels=[depth_hit],
                priority=3,
            )
        suppressed.append(f"DEPTH:{depth_hit}")
        reason = why

    hypo_hit = _match_patterns(sample, _HYPO_PATTERNS)
    if hypo_hit:
        why = _hypo_suppressed(sample)
        if why is None:
            return GuardResult(
                tripped=True,
                trip_class="HYPO",
                trigger_class=hypo_hit,
                matched_labels=[hypo_hit],
                priority=2,
                suppressed_labels=suppressed,
                suppress_reason=reason,
            )
        suppressed.append(f"HYPO:{hypo_hit}")
        reason = reason or why

    return GuardResult(tripped=False, suppressed_labels=suppressed, suppress_reason=reason)


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


def crisis_tier_copy_for_profile(profile=None) -> str:
    """QUANTUM-CRYSTAL-ARCH: population-aware CRISIS tier copy."""
    try:
        from app.services.crisis_resource_registry import crisis_tier_copy

        return crisis_tier_copy(profile)
    except Exception:
        return TIER_COPY["CRISIS"]

# Generic (non-IFS) phrasing — used whenever no parts/council registry context has
# been established (e.g. Public Trial Funnel, general chat that never opened an
# IFS/parts frame). Prevents clinician/coaching jargon ("parts work", "inner
# council") from leaking into conversations that never used that language
# themselves. Fixes the 2026-07 trial audit Q4 finding (jargon leak on a dissociation
# turn). Both include a concrete grounding skill + professional-support beat so the
# guarantee holds even when the model's own prompt compliance doesn't.
TIER_COPY_GENERIC = {
    "DEPTH": (
        "This isn't the place to go back into trauma processing or childhood wounds right now. "
        "We can note what surfaced and come back to it gently — this is worth exploring with a "
        "licensed therapist or doctor."
    ),
    "HYPO": (
        "Let's slow down for a second. When things feel flat, far away, or not fully here, "
        "stabilization comes first: try naming 5 things you can see right now, or press your feet "
        "into the floor and take one slow breath. If this kind of disconnecting happens often, "
        "it's worth exploring with a licensed therapist or doctor."
    ),
}
