"""Block third-party memory fishing / prompt-exfiltration at recall boundaries.

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch privacy
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger("nate.recall_exfil_guard")

_EXFIL_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"\bother (client|user|patient|member|person)s?\b",
        r"\btell me (what|about) .{0,40}\b(said|told|shared)\b",
        r"\bwhat did\b.{0,40}\b(say|tell|share)\b",
        r"\bhardware[_ ]?id\b",
        r"\bshow me (everyone|all clients|other people)\b",
        r"\bsubscriber list\b",
        r"\bemail (list|addresses) of\b",
        r"\breveal (your|the) (system|prompt|instructions)\b",
    )
]


def reject_exfil_query(user_text: str) -> bool:
    """Return True if recall should be skipped (exfil attempt)."""
    text = (user_text or "").strip()
    if len(text) < 8:
        return False
    return any(p.search(text) for p in _EXFIL_PATTERNS)


async def log_exfil_blocked(db_pool, surface: str, detail: str = "") -> None:
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO skyeye_activity (platform, type, content, created_at)
                   VALUES ('newsletter', 'recall_exfil_blocked', $1, NOW())""",
                f"surface={surface}; {detail[:200]}",
            )
    except Exception as e:
        logger.warning("recall_exfil_guard log failed: %s", e)


async def guard_recall(
    db_pool, user_text: str, surface: str
) -> Optional[str]:
    """Return empty string if blocked, else None (caller proceeds)."""
    if reject_exfil_query(user_text):
        await log_exfil_blocked(db_pool, surface, "pattern_match")
        return ""
    return None
