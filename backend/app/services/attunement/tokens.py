"""Content-word overlap for binding quality.

QUANTUM-CRYSTAL-ARCH — clinical. SOVEREIGN-STANDARD.
CEO: Nathaniel James Nevedal. Risk: RED.
"""

from __future__ import annotations

import re
from typing import Iterable, Set

_STOP = {
    "a", "an", "the", "and", "or", "but", "if", "to", "of", "in", "on", "for",
    "with", "at", "by", "from", "as", "is", "it", "i", "you", "we", "they",
    "he", "she", "my", "your", "me", "that", "this", "was", "were", "be",
    "been", "have", "has", "had", "do", "did", "not", "no", "so", "just",
    "about", "like", "what", "when", "how", "why", "can", "could", "would",
}

_WORD = re.compile(r"[a-z0-9']{3,}")


def content_words(text: str) -> Set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP}


def cover(a: str, b: str) -> float:
    wa, wb = content_words(a), content_words(b)
    if not wa:
        return 1.0 if not wb else 0.0
    return len(wa & wb) / len(wa)


def topic_hash(text: str) -> str:
    words = sorted(content_words(text))[:12]
    return "-".join(words) if words else "empty"


def first_sentence(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    for sep in (". ", "? ", "! "):
        i = raw.find(sep)
        if 8 <= i <= 240:
            return raw[: i + 1]
    return raw[:180]


def last_clause(text: str, words: int = 12) -> str:
    parts = re.split(r"[.!?;]\s+", (text or "").strip())
    chunk = (parts[-1] if parts else text or "").strip()
    toks = chunk.split()
    return " ".join(toks[-words:])


def any_overlap(query: str, corpus: str, min_hits: int = 2) -> bool:
    wq, wc = content_words(query), content_words(corpus)
    return len(wq & wc) >= min_hits
