"""
Fix 5 — Canned-stall suppression on high-acuity turns.

When post-flight audit fails on moderate+ bridge severity, replace the
transparent audit fallback with a content-aware acknowledgement instead of
the generic stall string.

Env: ENABLE_STALL_SUPPRESSION (default false)
"""
# QUANTUM-CRYSTAL-ARCH — Sensitive Bridge turn fix 5

from __future__ import annotations

import os
import re
from typing import Optional

ENABLE_STALL_SUPPRESSION: bool = os.getenv(
    "ENABLE_STALL_SUPPRESSION", "false"
).lower() in ("true", "1", "yes")

HIGH_ACUITY_SEVERITIES = frozenset({"moderate", "high", "critical", "emergency"})

_STALL_EXACT = (
    "I want to think about that more carefully — can you tell me which "
    "part of what you shared feels most important to you right now?"
)

_QUOTED_RX = re.compile(r'"([^"]{12,120})"|\'([^\']{12,120})\'')
_PROPER_NOUN_RX = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")
_TRAUMA_MARKER_RX = re.compile(
    r"\b("
    r"grandfather|grandmother|childhood|abuse|rape|assault|trauma|"
    r"crawling|underneath|hide|family pain|sexual|molest|violence"
    r")\b",
    re.IGNORECASE,
)


def is_stall_fallback(text: str) -> bool:
    return (text or "").strip() == _STALL_EXACT


def _extract_salient_phrase(user_text: str) -> Optional[str]:
    if not user_text or not user_text.strip():
        return None
    for m in _QUOTED_RX.finditer(user_text):
        chunk = m.group(1) or m.group(2) or ""
        if len(chunk.split()) >= 3:
            return chunk.strip()
    for m in _PROPER_NOUN_RX.finditer(user_text):
        phrase = m.group(1).strip()
        if phrase.lower() not in ("i", "the", "and", "but", "when", "what"):
            return phrase
    trauma = _TRAUMA_MARKER_RX.search(user_text)
    if trauma:
        start = max(0, trauma.start() - 40)
        end = min(len(user_text), trauma.end() + 60)
        snippet = user_text[start:end].strip()
        if len(snippet) > 20:
            return snippet[:160]
    sentences = re.split(r"(?<=[.!?])\s+", user_text.strip())
    for sent in sentences:
        if len(sent.split()) >= 6:
            return sent.strip()[:180]
    words = user_text.strip().split()
    if len(words) >= 8:
        return " ".join(words[:18])
    return user_text.strip()[:120] or None


def build_content_aware_fallback(user_text: str) -> str:
    """Heuristic acknowledgement — never emits the banned stall string."""
    phrase = _extract_salient_phrase(user_text or "")
    if phrase:
        return (
            f"I hear how much is in what you shared — especially around "
            f"{phrase}. What feels most alive in that for you right now?"
        )
    return (
        "I'm staying with what you just shared. What part of it feels "
        "most important to you right now?"
    )


def resolve_audit_fallback(
    *,
    user_text: str,
    bridge_event_severity: str,
    default_fallback: str,
) -> str:
    severity = (bridge_event_severity or "info").lower()
    if not ENABLE_STALL_SUPPRESSION:
        print(f">>> [STALL] not_applied reason=flag_off severity={severity}")
        return default_fallback
    if severity not in HIGH_ACUITY_SEVERITIES:
        print(f">>> [STALL] not_applied reason=low_acuity severity={severity}")
        return default_fallback
    if is_stall_fallback(default_fallback):
        out = build_content_aware_fallback(user_text)
        print(
            f">>> [STALL] suppressed turn_acuity={severity} "
            f"emitted content_aware_fallback={out[:80]!r}"
        )
        return out
    print(f">>> [STALL] not_applied reason=default_not_stall severity={severity}")
    return default_fallback
