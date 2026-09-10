"""Reconnect continuity + deferred close holding line.

QUANTUM-CRYSTAL-ARCH — clinical. SOVEREIGN-STANDARD.
CEO: Nathaniel James Nevedal. Risk: RED.
"""

from __future__ import annotations

from typing import List, Optional

from app.services.attunement import flags, store
from app.services.attunement.live_ring import is_reconnect
from app.services.attunement.tokens import last_clause
from app.services.attunement.turn_contract import is_high_affect

_TTL = 60 * 60 * 2


def _hold_k(uid: str) -> str:
    return store.key("deferred", uid)


def should_clear_live_on_login(uid: str) -> bool:
    if flags.reconnect() and is_reconnect(uid):
        return False
    return True


def reconnect_directive(uid: str) -> str:
    if flags.reconnect() and is_reconnect(uid):
        return (
            "CONTINUE MID-THOUGHT — no greeting, no recap, no 'welcome back'. "
            "Pick up the last unfinished thread."
        )
    return ""


def save_deferred(uid: str, live_turns: Optional[List[dict]]) -> bool:
    if not flags.deferred_close() or not uid:
        return False
    turns = live_turns or []
    if not turns:
        return False
    last_u = (turns[-1].get("user_text") or "").strip()
    if not is_high_affect(last_u):
        return False
    store.set_json(_hold_k(uid), {"holding": last_clause(last_u, 10)}, _TTL)
    return True


def consume_deferred(uid: str) -> str:
    if not flags.deferred_close() or not uid:
        return ""
    payload = store.get_json(_hold_k(uid)) or {}
    holding = (payload.get("holding") or "").strip()
    if not holding:
        return ""
    store.delete(_hold_k(uid))
    return f"DEFERRED HOLD (say once, then continue): holding {holding}."
