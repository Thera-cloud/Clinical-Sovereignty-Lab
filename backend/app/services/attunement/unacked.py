"""Unanswered-turn queue (replaces hardcoded critical-recall phrases).

QUANTUM-CRYSTAL-ARCH — clinical. SOVEREIGN-STANDARD.
CEO: Nathaniel James Nevedal. Risk: RED.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.attunement import flags, store
from app.services.attunement.tokens import cover, last_clause

_TTL = 60 * 60 * 6
_MAX = 3


def _k(uid: str) -> str:
    return store.key("unacked", uid)


def peek(uid: str) -> List[Dict[str, Any]]:
    if not flags.unacked_queue():
        return []
    raw = store.get_json(_k(uid)) or []
    return raw if isinstance(raw, list) else []


def push(uid: str, user_text: str, turn_id: str = "") -> None:
    if not flags.unacked_queue() or not uid or len(user_text or "") < 40:
        return
    q = peek(uid)
    item = {"user_text": (user_text or "")[:800], "turn_id": turn_id or ""}
    q = [x for x in q if (x.get("user_text") or "")[:80] != item["user_text"][:80]]
    q.append(item)
    store.set_json(_k(uid), q[-_MAX:], _TTL)


def ack_if_covered(uid: str, reply: str, threshold: float = 0.3) -> Optional[str]:
    q = peek(uid)
    if not q:
        return None
    last = q[-1]
    if cover(last.get("user_text") or "", reply) < threshold:
        return None
    q = q[:-1]
    if q:
        store.set_json(_k(uid), q, _TTL)
    else:
        store.delete(_k(uid))
    return last.get("turn_id") or "unacked"


def format_block(uid: str, live_turns: Optional[List[dict]] = None) -> str:
    """Binding facts from unacked + last live disclosure — no hardcoded names."""
    parts: List[str] = []
    q = peek(uid)
    if q:
        last = q[-1].get("user_text") or ""
        parts.append(f"UNANSWERED (bind first): {last_clause(last, 16)}")
    for t in (live_turns or [])[-2:]:
        ut = (t.get("user_text") or "").strip()
        if len(ut) >= 40:
            parts.append(f"THIS SESSION: {last_clause(ut, 14)}")
    if not parts:
        return ""
    return "CRITICAL RECALL FACTS (bind; do not invent):\n- " + "\n- ".join(parts[:4])
