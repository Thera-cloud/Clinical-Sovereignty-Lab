"""Boilerplate suppressor, register mirror, name cap, greeting strip.

QUANTUM-CRYSTAL-ARCH — clinical. SOVEREIGN-STANDARD.
CEO: Nathaniel James Nevedal. Risk: RED.
"""

from __future__ import annotations

import re
from typing import List, Optional

from app.services.attunement import flags

_BOILER = [
    re.compile(r"^i hear you[,.]?\s*", re.I),
    re.compile(r"^that sounds really hard[,.]?\s*", re.I),
    re.compile(r"^what'?s coming up for you\??\s*", re.I),
    re.compile(r"^tell me more[,.]?\s*", re.I),
]
_BOILER_ANY = re.compile(
    r"\b(i hear you|that sounds really hard|what'?s coming up for you|tell me more)\b",
    re.I,
)
_GREET = re.compile(
    r"^\s*(hi|hey|hello|welcome back|good (morning|afternoon|evening)|"
    r"it'?s good to (see|hear) you)\b[^.!?\n]*[.!?]?\s*",
    re.I,
)
_QUOTIENT_SPEAK = re.compile(r"\b(six quotients?|your (iq|eq|sq|mq|cq|aq)|quotient)\b", re.I)
_PROFANITY = re.compile(r"\b(fuck|shit|damn|asshole|hell)\b", re.I)
_FAITH = re.compile(r"\b(god|jesus|church|pray\w*|faith|lord)\b", re.I)
_HUMOR = re.compile(r"\b(lol|lmao|haha|joke|funny)\b", re.I)


def boilerplate_hits(text: str) -> int:
    return len(_BOILER_ANY.findall(text or ""))


def strip_leading_boilerplate(reply: str) -> str:
    out = reply or ""
    for pat in _BOILER:
        out = pat.sub("", out, count=1)
    return out.lstrip()


def suppress(reply: str, recent_ai: List[str]) -> str:
    if not flags.boilerplate():
        return reply
    hits = sum(boilerplate_hits(t) for t in (recent_ai or [])[-5:])
    out = reply or ""
    if hits >= 1:
        out = strip_leading_boilerplate(out)
    return out


def name_cap(reply: str, first_name: str, recent_ai: List[str]) -> str:
    if not flags.boilerplate() or not first_name or len(first_name) < 2:
        return reply
    name = first_name.strip().split()[0]
    pat = re.compile(rf"\b{re.escape(name)}\b", re.I)
    prior = sum(len(pat.findall(t or "")) for t in (recent_ai or [])[-3:])
    found = list(pat.finditer(reply or ""))
    if prior >= 1 and found:
        return pat.sub("you", reply, count=len(found))
    if len(found) > 1:
        keep = found[0].group(0)
        return pat.sub(lambda m: keep if m.start() == found[0].start() else "you", reply)
    return reply


def strip_greeting(reply: str) -> str:
    return _GREET.sub("", reply or "", count=1).lstrip()


def strip_spoken_quotients(reply: str) -> str:
    return _QUOTIENT_SPEAK.sub("that", reply or "")


def register_directive(recent_user: List[str]) -> str:
    if not flags.register_mirror():
        return ""
    blob = " ".join(recent_user or [])
    bits = []
    if _PROFANITY.search(blob):
        bits.append("Match their direct register; do not scold language.")
    if _FAITH.search(blob):
        bits.append("Honor faith language if they used it; do not preach.")
    if _HUMOR.search(blob):
        bits.append("Allow dry humor; do not flatten it into a lecture.")
    avg = 0
    if recent_user:
        avg = sum(len(t or "") for t in recent_user[-5:]) / max(1, len(recent_user[-5:]))
    if avg and avg < 50:
        bits.append("Stay short. They are terse.")
    bits.append("Never speak quotient names (IQ/EQ/SQ/MQ/CQ/AQ).")
    return "REGISTER: " + " ".join(bits)
