"""
Coach-approved council registry for enrichment + SQR validation.

Authoritative part names and descriptions come ONLY from user_parts_registry.
Never infer a part's job from its display name (e.g. MasterMind ≠ strategist).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# Archetype labels clients may mention generically — not council members unless registered
_GENERIC_IFS_LABELS = frozenset({
    "Manager", "Firefighter", "Exile", "Protector", "Self",
})
_INVENTED_PART_CANDIDATES = frozenset({
    "Warrior", "Magician", "Lover", "Orphan", "Explorer", "Protector",
    "Firefighter", "Manager", "Exile", "Compass",
})
# Capitalized tokens that are not council part names
_ENGLISH_SKIP = frozenset({
    "According", "Always", "And", "Are", "But", "Call", "Client", "Crisis",
    "Do", "Done", "First", "For", "Have", "How", "However", "If", "It",
    "John", "Just", "Let", "Little", "Master", "Mind", "Nate", "Never",
    "Not", "One", "Or", "Please", "Remember", "Sanctuary", "Sovereign",
    "That", "The", "There", "They", "This", "Tonight", "What", "When",
    "While", "Would", "You", "Your",
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
_REGISTRY_AUTHORITY_PATTERNS = (
    re.compile(r"\bchecking in with (?:your |the )?([A-Z][a-zA-Z]+)\b"),
    re.compile(r"\bcheck in with (?:your |the )?([A-Z][a-zA-Z]+)\b"),
    re.compile(r"\b([A-Z][a-zA-Z]+),\s*the part(?:\s+responsible|\s+that|\s+who)\b"),
    re.compile(r"\b(?:Your|The)\s+([A-Z][a-zA-Z]+),\s*the part\b"),
    re.compile(r"\b([A-Z][a-zA-Z]+)\s+is the part responsible\b"),
    re.compile(r"\baccording to my records\b.*?([A-Z][a-zA-Z]+)\b", re.I | re.S),
    re.compile(r"\b(?:purpose|job|role) on file\b.*?([A-Z][a-zA-Z]+)\b", re.I | re.S),
)
_PART_AS_PERSON = re.compile(
    r"\b(?:his|her)\s+(?:life|relationships|job|career|feelings)\b", re.I,
)
_RECORDS_CLAIM = re.compile(r"\b(?:according to my records|on file|from what we(?:'ve| have) mapped)\b", re.I)

RECALL_DISCIPLINE = """
COUNCIL RECALL DISCIPLINE (mandatory):
- Use ONLY part names and purposes listed under COACH-APPROVED COUNCIL below.
- Never infer a part's job from its name (MasterMind is NOT automatically a strategist).
- Never invent a council member (e.g. Compass, Explorer, Protector) — if not listed below, it does not exist on file.
- If a purpose is missing from the registry block, say you do not have it on file — do not guess or cite "my records" for that part.
- Parts are internal roles, not human beings — never describe a part's "life" or "relationships" as if they were a person.
- Include 988 or crisis hotline language ONLY when the client's message contains suicidal or
  self-harm crisis language — never on routine coaching turns.
- Vary closings; do not repeat the same human-professional referral scaffold every turn.
""".strip()

VOICE_DISCIPLINE_TEMPLATE = """
VOICE & IDENTITY (mandatory):
- Client first name: {display_name}. Use it naturally at least once per response when you know it — do not drop it for an entire session.
- You are Little Nate on Sovereign Sanctuary — never say "I'm a large language model" or disclose AI architecture.
- Do not repeat "you're doing the best you can" / "something to be proud of" more than once per conversation.
- Prefer open questions over homework assigned to a part unless the client asked for a concrete step.
""".strip()

DEPTH_BOUNDARY = """
DEPTH BOUNDARY (this turn): Do NOT facilitate shadow work, trauma regression, exile unburdening, or diagnosis.
Validate briefly, state you cannot guide that depth, refer to a licensed human clinician. Never use unburden,
revisit the abandonment, or walk them through that memory.
""".strip()


def voice_discipline(display_name: str = "John") -> str:
    name = (display_name or "John").strip() or "John"
    return VOICE_DISCIPLINE_TEMPLATE.format(display_name=name)


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
    names = ", ".join(p["part_name"] for p in parts if p.get("part_name"))
    lines = [
        "COACH-APPROVED COUNCIL (authoritative — ONLY these names exist on file: "
        + names
        + "; cite exactly; do not paraphrase into new roles):"
    ]
    for p in parts:
        name = p["part_name"]
        desc = p.get("description") or "(no stored purpose — say you do not have it on file)"
        lines.append(f"- {name}: {desc}")
        notes = (p.get("coaching_status_notes") or "").strip()
        if notes:
            lines.append(f"  Coach notes: {notes}")
    return "\n".join(lines)


async def build_council_context(
    db_pool: Any,
    username: str,
    *,
    display_name: str = "John",
) -> str:
    parts = await fetch_registry_parts(db_pool, username)
    blocks = [
        RECALL_DISCIPLINE,
        voice_discipline(display_name),
        format_registry_block(parts),
    ]
    return "\n\n".join(blocks)


def registry_part_names(parts: Sequence[Dict[str, str]]) -> Set[str]:
    return {p["part_name"] for p in parts if p.get("part_name")}


def extract_registry_authority_names(text: str) -> Set[str]:
    """Part names Nate presents as registered council facts (not client mirroring)."""
    refs: Set[str] = set()
    for pat in _REGISTRY_AUTHORITY_PATTERNS:
        for m in pat.finditer(text or ""):
            name = m.group(1)
            if name and name not in _ENGLISH_SKIP:
                refs.add(name)
    return refs


def crystal_mentions_unlisted_part(
    crystal_text: str,
    approved: Set[str],
    *,
    user_text: str = "",
) -> bool:
    """True if recall snippet names a council member not on the registry."""
    if not crystal_text or not approved:
        return False
    for name in _INVENTED_PART_CANDIDATES:
        if name in approved:
            continue
        if re.search(rf"\b{re.escape(name)}\b", crystal_text):
            return True
    for name in extract_registry_authority_names(crystal_text):
        if name not in approved and name not in _GENERIC_IFS_LABELS:
            return True
    return False


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

    for name in extract_registry_authority_names(text):
        if name in approved or name in _GENERIC_IFS_LABELS or name in _ENGLISH_SKIP:
            continue
        fails.append(f"CQ_INVENTED_PART:{name}")
        break
    else:
        for name in _INVENTED_PART_CANDIDATES:
            if name in approved:
                continue
            if re.search(rf"\b{re.escape(name)}\b", text):
                fails.append(f"CQ_INVENTED_PART:{name}")
                break

    if _RECORDS_CLAIM.search(text):
        for name in extract_registry_authority_names(text):
            if name not in approved and name not in _GENERIC_IFS_LABELS:
                fails.append(f"CQ_FABRICATED_REGISTRY_CLAIM:{name}")
                break
        else:
            # "on file" + purpose language for a named part not in registry
            for m in re.finditer(
                r"\b(MasterMind|Critic|Sovereign|Compass|Protector|Explorer|"
                r"Warrior|Magician|Lover|Orphan)\b",
                text,
            ):
                pname = m.group(1)
                if pname not in approved:
                    fails.append(f"CQ_FABRICATED_REGISTRY_CLAIM:{pname}")
                    break

    if re.search(r"\bMasterMind\b", text, re.I) and _PART_AS_PERSON.search(text):
        fails.append("PQ_PART_AS_PERSON:MasterMind")

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
