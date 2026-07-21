"""
Imported Transfer Crystal history recall — vault FTS for deep memory search.

Sections labeled IMPORTED PLATFORM HISTORY are from pre-Sanctuary AI exports
(Claude, ChatGPT, etc.), not conversations with Little Nate.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

_IMPORTED_HEADER = "IMPORTED PLATFORM HISTORY"
_NATE_SECTION_MARKERS = (
    "CONVERSATION HISTORY MATCHES",
    "CRYSTAL MEMORY MATCHES",
    "THERAPEUTIC RECALL CONTEXT",
    "SEMANTIC MATCHES",
)

# Soft trigger: single-category import intent (bridge uses this to bypass 2-gate)
_IMPORT_SOFT_PATTERNS = [
    re.compile(r"\b(claude|chatgpt|gemini|replika)\b", re.I),
    re.compile(r"\b(google\s+(ai|gemini)|ai\s+mode|myactivity)\b", re.I),
    re.compile(r"\b(imported|transfer(red)?)\s+(history|chat|conversations?)\b", re.I),
    re.compile(
        r"\b(from my export|transfer crystal|my (chatgpt|claude|gemini|google) (history|export|chats?))\b",
        re.I,
    ),
    re.compile(r"\b(before (i )?(came|joined|switching)|prior (ai|chat) (history|conversations?))\b", re.I),
    re.compile(r"\b(downloaded?\s+(my\s+)?(ai|chat|gemini)|from\s+(my\s+)?google)\b", re.I),
]

_PREVIEW_CHARS = int(os.environ.get("TRANSFER_RECALL_PREVIEW_CHARS", "4000"))
_MAX_TOTAL_CHARS = int(os.environ.get("TRANSFER_RECALL_MAX_CHARS", "12000"))


def should_search_imported_history(text: str) -> bool:
    """True when the user is clearly asking about pre-Sanctuary AI exports."""
    if not text or len(text) < 6:
        return False
    return any(p.search(text) for p in _IMPORT_SOFT_PATTERNS)


async def fetch_transfer_crystal_summary(
    db_pool,
    *,
    username: str = "",
    hardware_id: str = "",
    max_chars: int = 2000,
) -> str:
    """Always-on continuity block from transfer_crystals (9-section or stub)."""
    if not db_pool:
        return ""
    if os.environ.get("ENABLE_TRANSFER_FULL_RECALL", "true").lower() in ("0", "false", "no"):
        return ""

    member_ids: List[str] = []
    for mid in (username, hardware_id):
        if mid and mid not in member_ids:
            member_ids.append(mid)
    if not member_ids:
        return ""

    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT source_platform, crystal, created_at
                FROM transfer_crystals
                WHERE member_id = ANY($1::text[])
                ORDER BY created_at DESC
                LIMIT 1
                """,
                member_ids,
            )
    except Exception as e:
        logger.warning("Transfer crystal summary fetch failed: %s", e)
        return ""

    if not row:
        return ""

    crystal = row["crystal"]
    if isinstance(crystal, str):
        try:
            crystal = json.loads(crystal)
        except Exception:
            crystal = {}
    if not isinstance(crystal, dict):
        return ""

    platform = (row["source_platform"] or "imported").upper()
    parts = [
        f"TRANSFER CRYSTAL SUMMARY (from {platform} import — pre-Sanctuary continuity profile):"
    ]
    for key in (
        "core_identity_summary",
        "relationship_map",
        "active_therapeutic_themes",
        "historical_themes",
        "communication_profile",
        "unresolved_work",
        "strengths_and_resources",
        "clinical_considerations",
        "first_session_guidance",
    ):
        val = (crystal.get(key) or "").strip()
        if val:
            parts.append(f"- {key.replace('_', ' ').title()}: {val}")

    block = "\n".join(parts)
    if len(block) > max_chars:
        block = block[:max_chars] + "\n[Transfer Crystal summary truncated.]"
    parts_note = (
        "\nNote: This is a therapeutic summary of their imported history. "
        "For specific quotes, use IMPORTED PLATFORM HISTORY from deep memory search. "
        "Never claim you were in those prior AI threads."
    )
    return block + parts_note


async def search_imported_transfer_history(
    db_pool,
    *,
    username: str,
    hardware_id: str,
    search_terms: str,
    max_results: int = 8,
) -> str:
    """FTS vault_items (transfer_conversation + AI Mode upload docs) for imports."""
    if not db_pool or not search_terms or not str(search_terms).strip():
        return ""

    member_ids: List[str] = []
    for mid in (username, hardware_id):
        if mid and mid not in member_ids:
            member_ids.append(mid)

    preview_n = max(400, min(_PREVIEW_CHARS, 20000))
    term0 = search_terms.split()[0] if search_terms.split() else search_terms
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT display_name, extracted_text_preview, themes, uploaded_at,
                       content_type,
                       ts_rank(
                           search_vector,
                           plainto_tsquery('english', $2)
                       ) AS rank
                FROM vault_items
                WHERE member_id = ANY($1::text[])
                  AND (
                      content_type = 'transfer_conversation'
                      OR (
                          content_type = 'upload_document'
                          AND (
                              display_name ILIKE '%MyActivity%'
                              OR display_name ILIKE '%AI Mode%'
                              OR extracted_text_preview ILIKE '%Your prompt:%'
                          )
                      )
                  )
                  AND search_vector @@ plainto_tsquery('english', $2)
                ORDER BY rank DESC, uploaded_at DESC
                LIMIT $3
                """,
                member_ids,
                search_terms,
                max_results,
            )
            # Fallback: ILIKE when FTS misses proper nouns / short terms
            if not rows:
                rows = await conn.fetch(
                    """
                    SELECT display_name, extracted_text_preview, themes, uploaded_at,
                           content_type,
                           0.0::float AS rank
                    FROM vault_items
                    WHERE member_id = ANY($1::text[])
                      AND (
                          content_type = 'transfer_conversation'
                          OR (
                              content_type = 'upload_document'
                              AND (
                                  display_name ILIKE '%MyActivity%'
                                  OR display_name ILIKE '%AI Mode%'
                                  OR extracted_text_preview ILIKE '%Your prompt:%'
                              )
                          )
                      )
                      AND (
                          extracted_text_preview ILIKE '%' || $2 || '%'
                          OR display_name ILIKE '%' || $2 || '%'
                      )
                    ORDER BY uploaded_at DESC
                    LIMIT $3
                    """,
                    member_ids,
                    term0,
                    max_results,
                )
    except Exception as e:
        logger.warning("Imported transfer vault FTS failed: %s", e)
        return ""

    if not rows:
        return ""

    lines: List[str] = []
    total = 0
    for row in rows:
        themes = row["themes"] or []
        platform = _platform_from_themes(themes, row["display_name"], row["content_type"])
        ts = ""
        if row["uploaded_at"]:
            ts = row["uploaded_at"].strftime("%b %d %Y")
        name = (row["display_name"] or "Untitled")[:120]
        preview = (row["extracted_text_preview"] or "")[:preview_n]
        if total + len(preview) > _MAX_TOTAL_CHARS:
            remain = _MAX_TOTAL_CHARS - total
            if remain < 200:
                break
            preview = preview[:remain] + "\n[truncated for context budget]"
        header = f"[{platform.upper()} — {name}"
        if ts:
            header += f" — {ts}"
        header += "]"
        lines.append(f"{header}\n{preview}")
        total += len(preview)

    block = (
        f"{_IMPORTED_HEADER} ({len(lines)} found — "
        f"from AI platforms BEFORE Sanctuary; Nate was NOT in these threads):\n"
        + "\n\n".join(lines)
    )
    print(f"[CHAT-DEEP-SEARCH] transfer_vault: {len(lines)} FTS/ILIKE hits ({total} chars)")
    return block


def _platform_from_themes(
    themes: list,
    display_name: Optional[str] = None,
    content_type: Optional[str] = None,
) -> str:
    for t in themes or []:
        if t in ("chatgpt", "claude", "gemini", "replika", "google_ai_mode"):
            return "google_ai_mode" if t == "google_ai_mode" else t
    name = (display_name or "").lower()
    if "myactivity" in name or "ai mode" in name:
        return "google_ai_mode"
    if content_type == "upload_document" and ("gemini" in name or "google" in name):
        return "gemini"
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
            "Say instead: 'In your Claude history...' or 'From what you shared from ChatGPT...' "
            "or 'In your Google AI Mode / Gemini export...'. "
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
