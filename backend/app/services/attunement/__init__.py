"""Conversation attunement package — hold/steer contract.

QUANTUM-CRYSTAL-ARCH — clinical turn binding. SOVEREIGN-STANDARD.
CEO: Nathaniel James Nevedal. Risk: RED (PHI in live-ring Redis; TTL required).
"""

from app.services.attunement.flags import enabled
from app.services.attunement.hooks import (
    apply_context_rank,
    apply_postflight,
    format_critical_recall,
    merge_live_ring,
    on_last_socket,
    on_turn_committed,
    recall_timeout_fallback,
    should_clear_live_on_login,
    tempo_max_tokens,
)

__all__ = [
    "enabled",
    "apply_context_rank",
    "apply_postflight",
    "format_critical_recall",
    "merge_live_ring",
    "on_last_socket",
    "on_turn_committed",
    "recall_timeout_fallback",
    "should_clear_live_on_login",
    "tempo_max_tokens",
]
