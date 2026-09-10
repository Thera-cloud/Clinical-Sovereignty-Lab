"""Feature flags for conversation attunement.

QUANTUM-CRYSTAL-ARCH — clinical. SOVEREIGN-STANDARD.
CEO: Nathaniel James Nevedal. Risk: RED.
"""

from __future__ import annotations

import os

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


def _flag(name: str, default: str = "true") -> bool:
    raw = (os.getenv(name, default) or default).strip().lower()
    if raw in _FALSE:
        return False
    return raw in _TRUE or default.lower() in _TRUE


def enabled(name: str, default: str = "true") -> bool:
    return _flag(name, default)


def turn_contract() -> bool:
    return _flag("ENABLE_TURN_CONTRACT", "true")


def unacked_queue() -> bool:
    return _flag("ENABLE_UNACKED_QUEUE", "true")


def live_ring() -> bool:
    return _flag("ENABLE_LIVE_RING_REDIS", "true")


def recall_cache() -> bool:
    return _flag("BRIDGE_RECALL_FALLBACK_CACHE", "true")


def pg_full_turns() -> bool:
    return _flag("BRIDGE_PG_HISTORY_FULL_TURNS", "true")


def context_rank() -> bool:
    return _flag("ENABLE_CONTEXT_RANK_V2", "true")


def tempo() -> bool:
    return _flag("ENABLE_TEMPO_MATCH", "true")


def boilerplate() -> bool:
    return _flag("ENABLE_BOILERPLATE_SUPPRESSOR", "true")


def register_mirror() -> bool:
    return _flag("ENABLE_REGISTER_MIRROR", "true")


def reconnect() -> bool:
    return _flag("ENABLE_RECONNECT_CONTINUITY", "true")


def memory_claim() -> bool:
    return _flag("ENABLE_MEMORY_CLAIM_GUARD", "true")


def deferred_close() -> bool:
    return _flag("ENABLE_DEFERRED_CLOSE", "true")


def commitments() -> bool:
    return _flag("ENABLE_COMMITMENT_SURFACING", "true")


def agenda_gate() -> bool:
    return _flag("ENABLE_AGENDA_GATE", "true")


def conjecture() -> bool:
    return _flag("ENABLE_CONJECTURE_BUDGET", "true")
