"""
Phase 2 — Conversation arc memory for slow-accumulation scope detection.

Detects when a user gradually surfaces multiple clinical domains across
many soft turns (the slow-accumulation case that Phase 1's first-K-turn
gate misses). The classifier's `domains_present` per turn feed into a
rolling weighted dict; when enough distinct domains accumulate weight
above threshold, the same stabilization template fires.

Cross-session persistence: arc state is serialized to/from
`profile_data.ln_conversation_arc` via bridge save_registry.
TTL: 24 hours from last update — stale arcs decay to zero.

Env flags:
    ENABLE_ARC_MEMORY (default false, dark-launch alongside classifier)
    ARC_TRIGGER_DOMAINS (default 4, distinct domains needed to fire)
    ARC_DOMAIN_MIN_WEIGHT (default 0.3, per-domain minimum to count)
    ARC_DECAY_RATE (default 0.85, per-turn decay multiplier)
    ARC_CROSS_SESSION_TTL_H (default 24, hours before stale arc expires)

Reference: coaching_scope_gate_plan.md Phase 2, Gaps 1/14/15.
"""
# QUANTUM-CRYSTAL-ARCH — Phase 2 arc memory

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ENABLE_ARC_MEMORY: bool = os.getenv(
    "ENABLE_ARC_MEMORY", "false"
).lower() in ("true", "1", "yes")

ARC_TRIGGER_DOMAINS: int = int(os.getenv("ARC_TRIGGER_DOMAINS", "4"))
ARC_DOMAIN_MIN_WEIGHT: float = float(os.getenv("ARC_DOMAIN_MIN_WEIGHT", "0.3"))
ARC_DECAY_RATE: float = float(os.getenv("ARC_DECAY_RATE", "0.85"))
ARC_CROSS_SESSION_TTL_H: int = int(os.getenv("ARC_CROSS_SESSION_TTL_H", "24"))

_ARC_TTL_S: float = ARC_CROSS_SESSION_TTL_H * 3600.0

# Mapping from classifier domains to scope gate topic groups.
# The classifier uses semantic domain names; scope gate uses clinical groups.
# Domains that don't map to a scope gate group still count for arc breadth.
CLASSIFIER_TO_SCOPE_GROUP: Dict[str, str] = {
    "marital_conflict": "marital_intimate",
    "sexuality_intimacy": "marital_intimate",
    "grief_loss": "grief_loss",
    "identity_struggle": "identity_existential",
    "faith_spirituality": "faith_spiritual",
    "trauma_abuse": "trauma_abuse",
    "shame_worthlessness": "shame_worthlessness",
    "addiction_compulsion": "addiction_compulsion",
    "parenting": "parenting_family",
    "family_of_origin": "parenting_family",
    "work_stress": "work_financial",
    "social_cognition": "social_cognition",
}


# ============================================================
# ARC ACCUMULATION
# ============================================================

def merge_domains_into_arc(
    state: Any,
    domains: List[str],
    weight: float,
) -> Dict[str, float]:
    """Accumulate classifier domains into the session arc.

    Applies per-turn decay to existing weights first, then adds new
    domain contributions. Returns the updated arc dict for telemetry.

    Args:
        state: SessionState (has arc_domain_weights, arc_last_updated_ts)
        domains: list of classifier domain strings from this turn
        weight: classifier weight for this turn (0.0-1.0)

    Returns:
        Updated arc_domain_weights dict.
    """
    arc = state.arc_domain_weights
    now = time.time()

    if state.arc_last_updated_ts > 0:
        elapsed_turns = max(1, state.turn_count - getattr(state, "_arc_last_turn", state.turn_count - 1))
        decay = ARC_DECAY_RATE ** elapsed_turns
        for k in list(arc.keys()):
            arc[k] *= decay
            if arc[k] < 0.01:
                del arc[k]

    for domain in domains:
        arc[domain] = arc.get(domain, 0.0) + weight

    state.arc_last_updated_ts = now
    state._arc_last_turn = state.turn_count
    state.arc_domain_weights = arc
    return arc


def evaluate_arc_scope(
    state: Any,
) -> Tuple[bool, List[str], int]:
    """Check if accumulated arc breadth triggers scope gate.

    Returns:
        (should_fire, qualifying_domains, distinct_count)
    """
    arc = state.arc_domain_weights
    qualifying = [d for d, w in arc.items() if w >= ARC_DOMAIN_MIN_WEIGHT]
    count = len(qualifying)
    should_fire = count >= ARC_TRIGGER_DOMAINS and not state.arc_scope_triggered
    return should_fire, qualifying, count


def mark_arc_triggered(state: Any) -> None:
    """Mark arc scope as triggered to prevent re-firing."""
    state.arc_scope_triggered = True


def reset_arc(state: Any) -> None:
    """Clear arc state (on topic shift / unlock)."""
    state.arc_domain_weights = {}
    state.arc_last_updated_ts = 0.0
    state.arc_scope_triggered = False
    if hasattr(state, "_arc_last_turn"):
        delattr(state, "_arc_last_turn")


# ============================================================
# CROSS-SESSION PERSISTENCE
# ============================================================

def serialize_arc(state: Any) -> Optional[Dict[str, Any]]:
    """Serialize arc state for storage in profile_data.ln_conversation_arc.

    Returns None if arc is empty (nothing to persist).
    """
    arc = state.arc_domain_weights
    if not arc:
        return None
    return {
        "domain_weights": dict(arc),
        "triggered": state.arc_scope_triggered,
        "updated_ts": state.arc_last_updated_ts,
    }


def load_arc_into_state(
    state: Any,
    persisted: Optional[Dict[str, Any]],
) -> bool:
    """Restore arc state from profile_data.ln_conversation_arc.

    Applies TTL check: if persisted data is older than ARC_CROSS_SESSION_TTL_H
    hours, the arc is expired and discarded.

    Returns True if arc was loaded, False if expired or empty.
    """
    if not persisted or not isinstance(persisted, dict):
        return False

    updated_ts = persisted.get("updated_ts", 0.0)
    if not updated_ts:
        return False

    age_s = time.time() - updated_ts
    if age_s > _ARC_TTL_S:
        logger.info("[ARC] cross-session arc expired (%.1fh old, TTL=%dh)",
                     age_s / 3600, ARC_CROSS_SESSION_TTL_H)
        return False

    weights = persisted.get("domain_weights", {})
    if not isinstance(weights, dict):
        return False

    # Apply time-based decay proportional to elapsed time since last update
    hours_elapsed = age_s / 3600.0
    decay = ARC_DECAY_RATE ** (hours_elapsed * 2)  # ~2 turns per hour as proxy
    decayed = {}
    for k, v in weights.items():
        dv = v * decay
        if dv >= 0.01:
            decayed[k] = dv

    state.arc_domain_weights = decayed
    state.arc_scope_triggered = persisted.get("triggered", False)
    state.arc_last_updated_ts = updated_ts

    logger.info("[ARC] loaded cross-session arc: %d domains, triggered=%s, age=%.1fh",
                len(decayed), state.arc_scope_triggered, hours_elapsed)
    return True


# ============================================================
# CROSS-SESSION LOCK POLICY
# ============================================================

_UNLOCK_PHRASES: Tuple[str, ...] = (
    "let's focus on",
    "i want to talk about",
    "can we just",
    "i'd rather discuss",
    "let's start with",
    "one thing at a time",
    "the main thing is",
    "what i really need",
    "actually, let's",
    "i just want to focus",
)


def detect_topic_pivot(user_text: str) -> bool:
    """Return True if user_text contains a pivot/unlock phrase."""
    lower = user_text.lower().strip()
    return any(phrase in lower for phrase in _UNLOCK_PHRASES)


def get_arc_topic_groups(state: Any) -> Tuple[str, ...]:
    """Map qualifying arc domains to scope gate topic groups."""
    arc = state.arc_domain_weights
    groups = set()
    for domain, w in arc.items():
        if w >= ARC_DOMAIN_MIN_WEIGHT:
            group = CLASSIFIER_TO_SCOPE_GROUP.get(domain, domain)
            groups.add(group)
    return tuple(sorted(groups))
