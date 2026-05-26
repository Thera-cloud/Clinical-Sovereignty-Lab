"""
Imported Transfer Crystal history recall — vault FTS for deep memory search.

Sections labeled IMPORTED PLATFORM HISTORY are from pre-Sanctuary AI exports
(Claude, ChatGPT, etc.), not conversations with Little Nate.
"""

from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

_IMPORTED_HEADER = "IMPORTED PLATFORM HISTORY"
_NATE_SECTION_MARKERS = (
    "CONVERSATION HISTORY MATCHES",
    "CRYSTAL MEMORY MATCHES",
    "THERAPEUTIC RECALL CONTEXT",
    "SEMANTIC MATCHES",
)


async def search_imported_transfer_history(
    db_pool,
    *,
    username: str,
    hardware_id: str,
    search_terms: str,
    max_results: int = 8,
) -> str:
    """FTS vault_items (transfer_conversation) for imported platform chat threads."""
    if not db_pool or not search_terms or not str(search_terms).strip():
        return ""

    member_ids: List[str] = []
    for mid in (username, hardware_id):
        if mid and mid not in member_ids:
            member_ids.append(mid)

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT display_name, extracted_text_preview, themes, uploaded_at,
                       ts_rank(
                           search_vector,
                           plainto_tsquery('english', $2)
                       ) AS rank
                FROM vault_items
                WHERE member_id = ANY($1::text[])
                  AND content_type = 'transfer_conversation'
                  AND search_vector @@ plainto_tsquery('english', $2)
                ORDER BY rank DESC, uploaded_at DESC
                LIMIT $3
                """,
                member_ids,
                search_terms,
                max_results,
            )
    except Exception as e:
        logger.warning("Imported transfer vault FTS failed: %s", e)
        return ""

    if not rows:
        return ""

    lines: List[str] = []
    for row in rows:
        themes = row["themes"] or []
        platform = _platform_from_themes(themes)
        ts = ""
        if row["uploaded_at"]:
            ts = row["uploaded_at"].strftime("%b %d %Y")
        name = (row["display_name"] or "Untitled")[:120]
        preview = (row["extracted_text_preview"] or "")[:400]
        header = f"[{platform.upper()} — {name}"
        if ts:
            header += f" — {ts}"
        header += "]"
        lines.append(f"{header}\n{preview}")

    block = (
        f"{_IMPORTED_HEADER} ({len(rows)} found — "
        f"from AI platforms BEFORE Sanctuary; Nate was NOT in these threads):\n"
        + "\n\n".join(lines)
    )
    print(f"[CHAT-DEEP-SEARCH] transfer_vault: {len(rows)} FTS hits")
    return block


def _platform_from_themes(themes: list) -> str:
    for t in themes or []:
        if t in ("chatgpt", "claude", "gemini", "replika"):
            return t
    return "imported"


def format_deep_memory_prompt_instruction(context: str) -> str:
    """Prompt suffix for deep memory injection — separates Nate vs imported history."""
    if not context:
        return ""

    has_imported = _IMPORTED_HEADER in context
    has_nate = any(m in context for m in _NATE_SECTION_MARKERS)

    parts: List[str] = [
        "DEEP MEMORY SEARCH RESULTS: The user is asking you to recall something from past conversations."
    ]

    if has_nate:
        parts.append(
            "Sections labeled CONVERSATION HISTORY, CRYSTAL MEMORY, THERAPEUTIC RECALL, or "
            "SEMANTIC MATCHES are from your shared Sanctuary history with this person. "
            "Reference them warmly — e.g. 'Yes, I remember when you told me...' or "
            "'I do recall our conversation about...'. Be specific; use dates and quotes when present."
        )

    if has_imported:
        parts.append(
            f"Sections labeled {_IMPORTED_HEADER} are from their exported chats on other AI "
            "platforms BEFORE they joined Sanctuary. You were NOT in those threads. "
            "Never say 'we talked' or 'when you told me' for imported content alone. "
            "Say instead: 'In your Claude history...' or 'From what you shared from ChatGPT...'. "
            "Quote the excerpt; do not invent assistant replies that are not in the excerpt."
        )

    if not has_nate and not has_imported:
        parts.append(
            "Use only what appears in the search results. If nothing matches their question, "
            "say you do not have a matching record — do not fabricate."
        )
    elif not has_nate and has_imported:
        parts.append(
            "If imported excerpts do not contain their topic, say you do not see that topic "
            "in their imported history — do not invent."
        )

    parts.append(
        "Making people feel truly remembered is important — but only from verified excerpts above."
    )
    return " ".join(parts)
