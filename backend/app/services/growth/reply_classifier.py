"""Rule-based Instantly/reply classification — never auto-sends.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import re
from typing import Dict


def classify_reply(body: str) -> Dict[str, str]:
    text = (body or "").strip().lower()
    if not text:
        return {"classification": "needs_review", "reason": "empty"}
    if re.search(r"\bunsubscribe\b|\bremove me\b|\bdo not contact\b", text):
        return {"classification": "unsubscribe", "reason": "opt_out"}
    if re.search(r"\bbounce\b|\bmailbox unavailable\b|\buser unknown\b", text):
        return {"classification": "bounce", "reason": "bounce"}
    if re.search(r"\bout of office\b|\booo\b|\bon vacation\b|\bautomatic reply\b", text):
        return {"classification": "ooo", "reason": "ooo"}
    if re.search(
        r"\bnot interested\b|\bno thanks\b|\bplease stop\b|\bwrong person\b", text
    ):
        return {"classification": "not_interested", "reason": "decline"}
    if re.search(
        r"\binterested\b|\btell me more\b|\bschedule\b|\bbook a call\b|\byes\b",
        text,
    ):
        return {"classification": "interested", "reason": "positive"}
    return {"classification": "needs_review", "reason": "ambiguous"}
