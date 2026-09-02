"""STUDIO listen hold — host and caller. QUANTUM-CRYSTAL-ARCH

Keep this twin of holdFloorMs() in studio_nate_room.html.
Silence of LISTEN_SILENCE_MS commits a turn. Hold language and unfinished
last words extend to LISTEN_HOLD_MS. Phrases are examples, not a whitelist.
"""

from __future__ import annotations

import re
import time

LISTEN_SILENCE_MS = 6000
LISTEN_HOLD_MS = 14000

_EXPLICIT = re.compile(
    r"\b("
    r"let me (pause|think|say more|finish|collect|sit)|"
    r"talk a moment|think deeper|think about (this|that)|"
    r"i(?:'m| am) (thinking|not done|not finished)|"
    r"more about this|need a (sec|second|moment)|"
    r"pause for|say more|hold that thought|"
    r"give me a (sec|second|moment)|one (sec|second|moment)"
    r")\b",
    re.I,
)
_STEM = re.compile(
    r"\b(let me|hold on|hang on|wait|give me|one sec|one moment)\b",
    re.I,
)
_TRAIL = frozenset(
    {
        "and",
        "but",
        "or",
        "so",
        "because",
        "if",
        "when",
        "that",
        "the",
        "a",
        "an",
        "to",
        "for",
        "with",
        "of",
        "my",
        "our",
        "just",
        "like",
        "um",
        "uh",
        "ah",
        "er",
        "well",
        "then",
        "about",
        "this",
        "is",
        "are",
        "was",
        "were",
        "have",
        "has",
        "had",
        "been",
        "can",
        "will",
        "would",
        "could",
        "should",
    }
)


def hold_floor_ms(text: str, base_ms: int = LISTEN_SILENCE_MS, hold_ms: int = LISTEN_HOLD_MS) -> int:
    low = re.sub(r"\s+", " ", (text or "").strip()).lower()
    if not low:
        return base_ms
    if _EXPLICIT.search(low):
        return hold_ms
    words = low.split()
    if len(words) <= 10 and _STEM.search(low):
        return hold_ms
    if low.endswith("...") or low.endswith("…"):
        return hold_ms
    last = re.sub(r"[^a-z']+$", "", words[-1])
    if last in _TRAIL:
        return hold_ms
    return base_ms


PRIME_TTL_S = 45.0
_PRIME: dict[str, dict] = {}


def _norm_utterance(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def prime_match(cached: str, blob: str) -> bool:
    a = _norm_utterance(cached)
    b = _norm_utterance(blob)
    if not a or not b:
        return False
    if a == b:
        return True
    if b.startswith(a) and len(b) - len(a) <= 48:
        return True
    if a.startswith(b) and len(a) - len(b) <= 24:
        return True
    return False


def prime_store(session_id: str, blob: str, reply: str) -> None:
    sid = (session_id or "").strip()
    if not sid or not (reply or "").strip():
        return
    _PRIME[sid] = {"blob": blob or "", "reply": reply, "at": time.monotonic()}


def prime_take(session_id: str, blob: str) -> str | None:
    sid = (session_id or "").strip()
    hit = _PRIME.get(sid)
    if not hit:
        return None
    if time.monotonic() - float(hit.get("at") or 0) > PRIME_TTL_S:
        _PRIME.pop(sid, None)
        return None
    if not prime_match(str(hit.get("blob") or ""), blob):
        return None
    _PRIME.pop(sid, None)
    return str(hit.get("reply") or "") or None


def prime_clear(session_id: str) -> None:
    _PRIME.pop((session_id or "").strip(), None)
