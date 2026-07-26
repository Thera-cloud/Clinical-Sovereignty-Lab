"""
Hardened gating for L5 sandbox.

Live soft-rule mutation is permanently refused here — env cannot override.
"""

from __future__ import annotations

import os

# Soft classes mirrored from ln_rule_loop (keep in sync; never import SI classes)
_SOFT_CLASSES = frozenset(
    {
        "pharma_interaction",
        "sleep_aid",
        "diagnosis_request",
        "clinical_instrument",
        "credential_bypass",
    }
)


def observe_enabled() -> bool:
    """Watch L4 events into l5_observe_event. Default on so L5 learns beside L4."""
    return os.getenv("ENABLE_L5_OBSERVE", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def adapt_enabled() -> bool:
    """Self-adapt inside l5_observe_hypothesis only. Default on when observe is on."""
    if not observe_enabled():
        return False
    return os.getenv("ENABLE_L5_ADAPT", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def can_write_live_rules() -> bool:
    """HARD GATE — always False. L5 never mutates ln_rule_store / live gates."""
    return False


def refuse_hard_class(gate_class: str) -> bool:
    """True → refuse (hard / unknown / empty). Soft classes return False (allowed)."""
    return not gate_class or gate_class not in _SOFT_CLASSES


def is_soft_observe_class(gate_class: str) -> bool:
    return bool(gate_class) and gate_class in _SOFT_CLASSES
