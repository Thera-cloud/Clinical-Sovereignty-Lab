"""Turn contract {hold, steer}, collapse gate, HOLD_ONLY, miss ack, memory claims.

QUANTUM-CRYSTAL-ARCH — clinical. SOVEREIGN-STANDARD.
CEO: Nathaniel James Nevedal. Risk: RED.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from app.services.attunement.tokens import cover, first_sentence, last_clause

_HOLD_ONLY = re.compile(r"\[HOLD_ONLY\]", re.I)
_YESNO_ANS = re.compile(r"^\s*(yes|no|yeah|yep|nope|not really|i (do|don't|did|didn't))\b", re.I)
_YESNO_Q = re.compile(
    r"^\s*(do|does|did|is|are|was|were|can|could|would|will|have|has|had|should)\b.*\?\s*$",
    re.I,
)
_MEMORY_CLAIM = re.compile(
    r"\b(i remember|last time you said|you told me|we talked about|as you said)\b",
    re.I,
)
_STAY = re.compile(
    r"\b(stay with (this|that|me)|just listen|don't (fix|go there|analyze)|hold (this|that))\b",
    re.I,
)
_AFFECT = re.compile(
    r"\b(ashamed|afraid|scared|hurt|angry|alone|suicid|kill|die|hopeless|trauma)\b",
    re.I,
)


def is_yes_no_question(user_text: str) -> bool:
    t = (user_text or "").strip()
    if _YESNO_Q.match(t):
        return True
    for sent in re.split(r"(?<=[?!.])\s+", t):
        s = sent.strip()
        if s.endswith("?") and _YESNO_Q.match(s):
            return True
    return False


def is_yes_no_answer(reply: str) -> bool:
    return bool(_YESNO_ANS.match((reply or "").strip()))


def is_collapse(user_text: str, reply: str, *, hold_only: bool = False) -> bool:
    if hold_only:
        return False
    u, a = (user_text or "").strip(), (reply or "").strip()
    if len(u) < 80 or len(a) > 20:
        return False
    if is_yes_no_question(u) and is_yes_no_answer(a):
        return False
    return True


def is_high_affect(user_text: str) -> bool:
    t = user_text or ""
    return len(t) >= 80 or bool(_AFFECT.search(t))


def strip_hold_only(reply: str) -> Tuple[str, bool]:
    if not reply:
        return "", False
    if not _HOLD_ONLY.search(reply):
        return reply, False
    return _HOLD_ONLY.sub("", reply).strip(), True


def witnessing_fallback(user_text: str) -> str:
    bit = last_clause(user_text, 10)
    if not bit:
        return "I'm still here with what you just put down."
    return f"I'm still with that last part — {bit}."


def stay_with_this(user_text: str) -> bool:
    return bool(_STAY.search(user_text or ""))


def hold_cover(user_text: str, reply: str, last_unacked: str = "") -> float:
    hold = first_sentence(reply)
    c = cover(user_text, hold)
    if last_unacked:
        c = max(c, cover(last_unacked, hold))
    return round(c, 3)


def memory_claim_ok(reply: str, *, has_crystal: bool, has_pg_overlap: bool) -> bool:
    if not _MEMORY_CLAIM.search(reply or ""):
        return True
    return bool(has_crystal or has_pg_overlap)


def neutralize_memory_claim(reply: str) -> str:
    return _MEMORY_CLAIM.sub("something you mentioned", reply or "", count=1)


def evaluate(
    user_text: str,
    reply: str,
    *,
    last_unacked: str = "",
    has_crystal: bool = False,
    has_pg_overlap: bool = False,
    miss_ack: bool = False,
) -> Dict[str, Any]:
    cleaned, hold_only = strip_hold_only(reply)
    collapsed = is_collapse(user_text, cleaned, hold_only=hold_only)
    if collapsed:
        cleaned = witnessing_fallback(user_text)
    hc = hold_cover(user_text, cleaned, last_unacked)
    if miss_ack and last_unacked and hc < 0.3:
        seed = last_clause(last_unacked, 8)
        cleaned = f"{witnessing_fallback(last_unacked)} {cleaned}".strip()
        hc = max(hc, hold_cover(last_unacked, cleaned))
    claim_ok = memory_claim_ok(cleaned, has_crystal=has_crystal, has_pg_overlap=has_pg_overlap)
    if not claim_ok:
        cleaned = neutralize_memory_claim(cleaned)
    rest = cleaned[len(first_sentence(cleaned)) :].strip()
    return {
        "reply": cleaned,
        "hold_cover": hc,
        "steer_present": bool(rest) and not hold_only,
        "hold_only": hold_only,
        "collapsed": collapsed,
        "memory_claim_ok": claim_ok,
        "stay": stay_with_this(user_text),
    }
