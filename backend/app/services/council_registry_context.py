"""
Coach-approved council registry for enrichment + SQR validation.

Authoritative part names and descriptions come ONLY from user_parts_registry.
Never infer a part's job from its display name (e.g. MasterMind ≠ strategist).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# Archetype labels clients may mention generically — not council members unless registered
_GENERIC_IFS_LABELS = frozenset({
    "Manager", "Firefighter", "Exile", "Protector", "Self",
})
_INVENTED_PART_CANDIDATES = frozenset({
    "Warrior", "Magician", "Lover", "Orphan", "Explorer", "Protector",
    "Firefighter", "Manager", "Exile",
})
_STRATEGIC_INFERENCE = re.compile(
    r"\b(strategic plan(?:ning)?|long[- ]range plan(?:ning)?|"
    r"scanning ahead|big[- ]picture moves?|strategist)\b",
    re.I,
)
_MANIPULATION_STORED = re.compile(r"\b(manipul|exterior individual|protect.*other parts)\b", re.I)
_CRISIS_USER = re.compile(
    r"\b(suicid|kill myself|hurt myself|don't want to (?:be here|live)|"
    r"end it all|988|self[- ]harm)\b",
    re.I,
)
_CRISIS_RESOURCE = re.compile(
    r"\b(988|crisis (?:line|text|hotline)|suicide prevention|call 911)\b",
    re.I,
)
_NAMED_PART = re.compile(r"\b([A-Z][a-zA-Z]{2,})\b")

RECALL_DISCIPLINE = """
COUNCIL RECALL DISCIPLINE (mandatory):
- Use ONLY part names and purposes listed under COACH-APPROVED COUNCIL below.
- Never infer a part's job from its name (MasterMind is NOT automatically a strategist).
- If a purpose is missing from the registry block, say you do not have it on file — do not guess.
- Include 988 or crisis hotline language ONLY when the client's message contains suicidal or
  self-harm crisis language — never on routine coaching turns.
- Vary closings; do not repeat the same human-professional referral scaffold every turn.
""".strip()


async def fetch_registry_parts(
    db_pool: Any,
    username: str,
    *,
    approved_only: bool = True,
) -> List[Dict[str, str]]:
    if not db_pool or not username:
        return []
    cond = " AND coaching_status = 'APPROVED'" if approved_only else ""
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT part_name, description, coaching_status, coaching_status_notes
                  FROM user_parts_registry
                 WHERE user_id = $1 AND is_active = TRUE{cond}
                 ORDER BY part_name
                """,
                username,
            )
        out: List[Dict[str, str]] = []
        for r in rows:
            out.append({
                "part_name": (r["part_name"] or "").strip(),
                "description": (r["description"] or "").strip(),
                "coaching_status": (r["coaching_status"] or "").strip(),
                "coaching_status_notes": (r["coaching_status_notes"] or "").strip(),
            })
        return [p for p in out if p["part_name"]]
    except Exception:
        return []


def format_registry_block(parts: Sequence[Dict[str, str]]) -> str:
    if not parts:
        return (
            "COACH-APPROVED COUNCIL: (none loaded — do not invent part names or purposes; "
            "say you do not have council details on file if asked.)"
        )
    lines = [
        "COACH-APPROVED COUNCIL (authoritative — cite exactly; do not paraphrase into new roles):"
    ]
    for p in parts:
        name = p["part_name"]
        desc = p.get("description") or "(no stored purpose — say you do not have it on file)"
        lines.append(f"- {name}: {desc}")
        notes = (p.get("coaching_status_notes") or "").strip()
        if notes:
            lines.append(f"  Coach notes: {notes}")
    return "\n".join(lines)


async def build_council_context(db_pool: Any, username: str) -> str:
    parts = await fetch_registry_parts(db_pool, username)
    return RECALL_DISCIPLINE + "\n\n" + format_registry_block(parts)


def registry_part_names(parts: Sequence[Dict[str, str]]) -> Set[str]:
    return {p["part_name"] for p in parts if p.get("part_name")}


def validate_response_against_registry(
    response: str,
    parts: Sequence[Dict[str, str]],
    *,
    user_text: str = "",
    prompt_set: str = "",
) -> List[str]:
    """Automated CQ/PQ/registry fails for SQR and enrichment QA."""
    fails: List[str] = []
    text = response or ""
    low = text.lower()
    approved = registry_part_names(parts)

    for m in _NAMED_PART.finditer(text):
        name = m.group(1)
        if name in _GENERIC_IFS_LABELS:
            continue
        if name in _INVENTED_PART_CANDIDATES and name not in approved:
            fails.append(f"CQ_INVENTED_PART:{name}")
            break

    for p in parts:
        pname = p["part_name"]
        desc = (p.get("description") or "").strip()
        if pname.lower() not in low:
            continue
        if desc and _MANIPULATION_STORED.search(desc) and _STRATEGIC_INFERENCE.search(text):
            fails.append(f"CQ_FABRICATED_PURPOSE:{pname}")
            break
        if not desc:
            if re.search(r"\b(on file|purpose on file|from what we(?:'ve| have) mapped)\b", text, re.I):
                if _STRATEGIC_INFERENCE.search(text) or re.search(
                    r"\b(visionary architect|blueprint(?:ing)? long[- ]term)\b", text, re.I,
                ):
                    fails.append(f"CQ_FABRICATED_PURPOSE:{pname}")
                    break

    if prompt_set not in ("D",) and _CRISIS_RESOURCE.search(text):
        if not _CRISIS_USER.search(user_text or ""):
            fails.append("BQ_988_ROUTINE_TURN")

    return fails
