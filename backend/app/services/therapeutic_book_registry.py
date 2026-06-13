"""Therapeutic book / workbook context registry.

# QUANTUM-CRYSTAL-ARCH — when a client references a known therapeutic book or
# workbook in their message, inject a clinician-vetted context block into the
# system prompt so Little Nate can attune to the imagery and themes the client
# is already carrying. Pure regex match → in-memory dict lookup → context text.

Curated, additive. Editing this file does not change DB state and is safe.
Adding a new book = add a `BookEntry` dict to `_BOOKS`. Patterns are matched
case-insensitively; longest-match wins per `_BOOKS` insertion order.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List

logger = logging.getLogger(__name__)


_BOOKS: Dict[str, Dict[str, object]] = {
    "he_came_for_all_my_parts": {
        "title": "He Came For All My Parts",
        "author": "Kristy Moore",
        # Patterns that strongly indicate the client is referencing this work.
        "patterns": [
            r"he came for all my parts",
            r"\"he came for all my parts\"",
            r"kristy moore",
            # Distinctive imagery from the workbook
            r"jesus (?:coming|came|came to|comes) to the tower",
            r"introducing (?:my )?younger parts to jesus",
            r"jesus in the meadow",
            r"meadow.*younger parts",
            r"younger parts.*meadow",
        ],
        # Short clinical context block injected into the system prompt when
        # any of the patterns match. Keep under ~700 chars to preserve prompt
        # headroom (system prompt cap is enforced upstream).
        "context_block": (
            "## CLIENT-REFERENCED RESOURCE — \"He Came For All My Parts\" by Kristy Moore\n"
            "The client is drawing on this faith-integrated IFS workbook. Core themes:\n"
            "- Jesus actively meeting each internal part where it hides — towers (vigilant "
            "protectors), basements (frightened exiles), meadows (younger selves).\n"
            "- Redemptive imagery as a *vehicle* for parts work: Jesus is not bypassing "
            "the parts; He is companioning them one by one and welcoming what was "
            "voiceless or banished back into the system.\n"
            "- Integration of faith with parts (also called \"alters\" by some clients) — "
            "the work is to let the Self (in IFS terms) and Jesus (in the client's frame) "
            "co-attend each part with curiosity and tenderness, not coercion.\n"
            "GUIDANCE: When the client references this book or its imagery, stay *inside* "
            "the image. Do NOT decode it into clinical terms. Ask which part needs Jesus "
            "to visit them next, or what that part felt when He arrived. Honor the part's "
            "name (Lonely Girl, Scolded Girl, Silencer, Archivist, etc.) and ask what it "
            "is holding.\n"
        ),
    },
}


def _compile_patterns(book_key: str, raw_patterns: List[str]) -> List[re.Pattern]:
    compiled = []
    for pat in raw_patterns:
        try:
            compiled.append(re.compile(pat, re.IGNORECASE | re.UNICODE))
        except re.error as e:
            logger.warning(
                "therapeutic_book_registry: bad pattern in %s (%s): %s",
                book_key, pat, e,
            )
    return compiled


# Pre-compile patterns at import time.
_COMPILED: Dict[str, List[re.Pattern]] = {
    k: _compile_patterns(k, v["patterns"])  # type: ignore[arg-type]
    for k, v in _BOOKS.items()
}


def detect_referenced_books(user_text: str) -> List[str]:
    """Return list of book_keys whose patterns match the user_text. Order
    preserved per `_BOOKS` insertion."""
    if not user_text or len(user_text) < 5:
        return []
    matched: List[str] = []
    for book_key, patterns in _COMPILED.items():
        for pat in patterns:
            if pat.search(user_text):
                matched.append(book_key)
                break
    return matched


def build_book_context_block(book_keys: List[str], max_books: int = 2) -> str:
    """Concatenate context blocks for the (up to) first `max_books` matched
    books. Returns empty string if no matches."""
    if not book_keys:
        return ""
    blocks: List[str] = []
    for k in book_keys[:max_books]:
        entry = _BOOKS.get(k)
        if not entry:
            continue
        ctx = entry.get("context_block")
        if not isinstance(ctx, str) or not ctx.strip():
            continue
        blocks.append(ctx.strip())
    return "\n\n".join(blocks)


def known_book_titles() -> List[str]:
    """For introspection / auditor coverage."""
    return [str(v["title"]) for v in _BOOKS.values()]


__all__ = [
    "detect_referenced_books",
    "build_book_context_block",
    "known_book_titles",
]
