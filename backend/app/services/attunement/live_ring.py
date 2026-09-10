"""Hot live-turn ring. Redis TTL 30 min idle. Do not pop on second-socket flap.

QUANTUM-CRYSTAL-ARCH — clinical. SOVEREIGN-STANDARD.
CEO: Nathaniel James Nevedal. Risk: RED (PHI).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.services.attunement import flags, store

_TTL = 30 * 60
_LIMIT = 8
_RECONNECT_S = 10 * 60


def _k(uid: str) -> str:
    return store.key("ring", uid)


def _meta_k(uid: str) -> str:
    return store.key("ringmeta", uid)


def load(uid: str) -> List[Dict[str, Any]]:
    if not flags.live_ring() or not uid:
        return []
    raw = store.get_json(_k(uid)) or []
    return raw if isinstance(raw, list) else []


def append(uid: str, user_text: str, ai_text: str) -> List[Dict[str, Any]]:
    if not flags.live_ring() or not uid:
        return []
    turns = load(uid)
    turns.append({
        "user_text": (user_text or "")[:800],
        "ai_text": (ai_text or "")[:800],
        "ts": time.time(),
    })
    turns = turns[-_LIMIT:]
    store.set_json(_k(uid), turns, _TTL)
    store.set_json(_meta_k(uid), {"updated": time.time(), "n": len(turns)}, _TTL)
    return turns


def merge(uid: str, mem_turns: Optional[List[dict]]) -> List[dict]:
    ring = load(uid)
    if not ring:
        return list(mem_turns or [])
    if not mem_turns:
        return ring
    if len(ring) >= len(mem_turns):
        return ring
    return list(mem_turns)


def last_update(uid: str) -> float:
    meta = store.get_json(_meta_k(uid)) or {}
    try:
        return float(meta.get("updated") or 0)
    except Exception:
        return 0.0


def is_reconnect(uid: str, window_s: float = _RECONNECT_S) -> bool:
    if not flags.reconnect() or not uid:
        return False
    ts = last_update(uid)
    return bool(ts) and (time.time() - ts) <= window_s


def clear(uid: str) -> None:
    store.delete(_k(uid))
    store.delete(_meta_k(uid))
