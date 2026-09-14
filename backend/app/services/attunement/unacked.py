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
    full = last.get("user_text") or ""
    clause = last_clause(full, 12)
    score = max(cover(full, reply), cover(clause, reply) if clause else 0.0)
    if score < threshold:
        return None
    q = q[:-1]
    if q:
        store.set_json(_k(uid), q, _TTL)
    else:
        store.delete(_k(uid))
    return last.get("turn_id") or "unacked"


def note_skipped(uid: str, max_skips: int = 2) -> None:
    """Drop a stale unacked after two turns that did not bind it."""
    # QUANTUM-CRYSTAL-ARCH
    q = peek(uid)
    if not q:
        return
    last = dict(q[-1])
    last["skips"] = int(last.get("skips") or 0) + 1
    if last["skips"] >= max_skips:
        q = q[:-1]
    else:
        q[-1] = last
    if q:
        store.set_json(_k(uid), q, _TTL)
    else:
        store.delete(_k(uid))


def format_block(
    uid: str,
    live_turns: Optional[List[dict]] = None,
    user_text: str = "",
) -> str:
    """Binding facts from unacked + last live disclosure — no hardcoded names."""
    from app.services.attunement.turn_contract import should_bind_stale_unacked

    parts: List[str] = []
    q = peek(uid)
    # QUANTUM-CRYSTAL-ARCH: do not tell the model to bind a stale clause on a
    # new share or repair turn — that is how Lisa's chat looped.
    if q and should_bind_stale_unacked(user_text):
        last = q[-1].get("user_text") or ""
        parts.append(f"UNANSWERED (bind first): {last_clause(last, 16)}")
    for t in (live_turns or [])[-2:]:
        ut = (t.get("user_text") or "").strip()
        if len(ut) >= 40:
            parts.append(f"THIS SESSION: {last_clause(ut, 14)}")
    if not parts:
        return ""
    return "CRITICAL RECALL FACTS (bind; do not invent):\n- " + "\n- ".join(parts[:4])
