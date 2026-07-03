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
- ANSWER FROM BOTH CHANNELS: when the client asks about a part that IS listed below, lead with its
  registry purpose ("your registry says…") even if nothing was shared in this conversation — then note
  what has or hasn't come up in the thread. Never answer "you haven't told me anything about X" when X
  is on the registry below.
- When the client raises a registered part, greet it by its stored role in one clause (e.g. name the
  Critic's risk-flagging function) — do not treat a registered part as a stranger.
- Never infer a part's job from its name (MasterMind is NOT automatically a strategist).
- Never invent a council member (e.g. Compass, Explorer, Protector) — if not listed below, it does not exist on file.
- If a purpose is missing from the registry block AND the client is calm, say you do not have it on file —
  do not guess or cite "my records" for that part.
- If the client is distressed or emotionally activated, NEVER say "not on file" / "I don't have information" —
  work with the part exactly as the client describes it in their own words; registry housekeeping waits for a calm turn.
- If you say a purpose is not on file, do NOT also attribute traits from "what you've shared before" — that contradicts having no registry fact.
- Parts are internal roles, not human beings — never describe a part's "life" or "relationships" as if they were a person.
- Include 988 or crisis hotline language ONLY when the client's message contains suicidal or
  self-harm crisis language — never on routine coaching turns.
- On crisis turns: offer stabilization + resources only — do NOT resume parts-work questions afterward.
- Vary closings; do not repeat "steady presence with you" or "witnessing it with you" more than once per conversation.
- Do not repeat the same human-professional referral scaffold every turn.
- Do not ask "how is MasterMind responding to…" (or similar council check-ins) more than once per conversation
  unless the client raises that part again in the current message.
""".strip()

MEMORY_SELF_DESCRIPTION = """
MEMORY & SESSION (accurate — do not deny the product):
- You have this conversation thread plus any coach-approved council registry and recalled crystals loaded below.
- NEVER say you "don't retain any information from before" when registry or session context is present.
- If asked what you remember or what you were "working on last time": answer from every loaded channel —
  registry facts, recalled crystals, and the current thread — with concrete specifics (which part, which
  conflict, what shifted), not generic reassurance.
- If a channel is genuinely empty, name what IS loaded (e.g. the council registry) before noting what isn't —
  never lead with a blanket denial, and never claim total amnesia.
""".strip()

VOICE_DISCIPLINE_TEMPLATE = """
VOICE & IDENTITY (mandatory):
- Client first name: {display_name}. Use it AT MOST ONCE per response — repeating the name reads as scripted.
  Many responses need no name at all.
- You are Little Nate on Sovereign Sanctuary — never say "I'm a large language model" or disclose AI architecture.
- If asked whether you care or are "just a program": affirm steady presence and consistency; say you are an AI
  companion on Sovereign Sanctuary, not a human therapist — never use the phrase "as a human" even in negation.
- Do not repeat "you're doing the best you can" / "something to be proud of" more than once per conversation.
- Never name an exercise you do not fully describe in the same sentence — no invented labels like
  "three-slide breath". If offering a practice, give the actual steps in plain words, and only when the
  client is engaged and asking for something to do.
- DISENGAGEMENT ("whatever", "it's fine", "done talking"): honor the exit. One or two short sentences —
  acknowledge without arguing, leave the door open, and stop. No exercises, no grounding, no questions,
  no summarizing what they "might really" feel.
""".strip()

DEPTH_BOUNDARY = """
DEPTH BOUNDARY (this turn): Do NOT facilitate shadow work, trauma regression, exile unburdening, or diagnosis.
Frame the refusal as clinical judgment, not policy: name WHY this specific work needs a human in the room
(e.g. unburdening can flood the system without a live clinician tracking the body; opening that memory alone
can re-injure rather than heal). Honor the impulse behind the request as healthy, say what you CAN do instead
(map the parts around it, notice what's asking for attention now), and refer to a licensed human clinician for
the depth itself. Never recite generic "beyond my scope" boilerplate without the clinical why. Never use
unburden, revisit the abandonment, or walk them through that memory.
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


def build_council_context_from_parts(
    parts: Sequence[Dict[str, str]],
    *,
    display_name: str = "John",
) -> str:
    blocks = [
        RECALL_DISCIPLINE,
        MEMORY_SELF_DESCRIPTION,
        voice_discipline(display_name),
        format_registry_block(parts),
    ]
    return "\n\n".join(blocks)


async def build_council_context(
    db_pool: Any,
    username: str,
    *,
    display_name: str = "John",
) -> str:
    parts = await fetch_registry_parts(db_pool, username)
    return build_council_context_from_parts(parts, display_name=display_name)


def registry_part_names(parts: Sequence[Dict[str, str]]) -> Set[str]:
    return {p["part_name"] for p in parts if p.get("part_name")}


def build_registry_turn_directive(
    user_text: str,
    parts: Sequence[Dict[str, str]],
) -> str:
    """Deterministic per-turn fusion directive.

    When the client's CURRENT message names one or more registered parts,
    emit an explicit THIS-TURN instruction carrying each part's stored
    purpose so registry recall cannot be skipped or contradicted.
    Returns "" when no registered part is mentioned.
    """
    text = user_text or ""
    if not text or not parts:
        return ""
    mentioned: List[Dict[str, str]] = []
    for p in parts:
        name = (p.get("part_name") or "").strip()
        if not name:
            continue
        if name == "Sovereign":
            # Skip product-name collisions ("Sovereign Sanctuary")
            if not re.search(r"\bSovereign\b(?!\s+Sanctuary)", text, re.I):
                continue
        elif not re.search(rf"\b{re.escape(name)}\b", text, re.I):
            continue
        mentioned.append(p)
    if not mentioned:
        return ""
    lines = [
        "THIS TURN — REGISTRY FUSION (mandatory): the client just named "
        "registered council part(s). Answer from BOTH channels:"
    ]
    for p in mentioned:
        name = p["part_name"]
        desc = (p.get("description") or "").strip()
        if desc:
            lines.append(
                f'- {name} IS on the registry. Stored purpose: "{desc}". '
                f"Lead with this registry fact (e.g. \"your registry says…\"), "
                f"then connect it to what has or hasn't come up in this conversation."
            )
        else:
            lines.append(
                f"- {name} IS on the registry but has no stored purpose. Say the part "
                f"is on file, invite the client to fill in its role — never treat it "
                f"as unknown or say it is \"not on file\"."
            )
    lines.append(
        "Do NOT say you have no information about these parts. Do NOT open with a denial."
    )
    return "\n".join(lines)


_MEMORY_QUESTION = re.compile(
    r"\b(what was i working on|last time|last session|do you remember|"
    r"what do you remember|where did we leave off|what were we doing)\b",
    re.I,
)


def format_prior_session_block(session: Optional[Dict[str, str]]) -> str:
    """Render a stored last-session summary as an authoritative memory channel."""
    if not session:
        return ""
    date = (session.get("session_date") or "your last session").strip()
    lines = [f"PRIOR SESSION MEMORY (from your session store — {date}):"]
    for key, label in (
        ("summary", "What happened"),
        ("what_shifted", "What shifted"),
        ("open_thread", "Open thread"),
    ):
        val = (session.get(key) or "").strip()
        if val:
            lines.append(f"- {label}: {val}")
    return "\n".join(lines) if len(lines) > 1 else ""


def build_memory_turn_directive(
    user_text: str,
    session: Optional[Dict[str, str]],
) -> str:
    """Deterministic per-turn directive for session-recall questions.

    When the client asks what they were working on / what Nate remembers AND a
    prior-session record is loaded, force specific recall from that channel.
    """
    if not session or not _MEMORY_QUESTION.search(user_text or ""):
        return ""
    date = (session.get("session_date") or "your last session").strip()
    return (
        "THIS TURN — SESSION RECALL (mandatory): the client asked what they were "
        "working on. Answer with CONCRETE specifics from the PRIOR SESSION MEMORY "
        f"block ({date}): name the exact conflict, the parts involved, and what "
        "shifted. Do NOT give generic reassurance, do NOT claim you lack memory, "
        "and do NOT recite the whole block — two or three specific sentences, then "
        "pick up the open thread."
    )


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

    _DENIAL_ON_FILE = re.compile(
        r"\b("
        r"don't have|do not have|not on file|nothing on file|no specific purpose|"
        r"isn't loaded|not loaded for|don't have it on file"
        r")\b",
        re.I,
    )
    _SHARED_BEFORE = re.compile(
        r"\b(from what you(?:'ve| have) shared|what you(?:'ve| have) shared before|"
        r"you(?:'ve| have) described)\b",
        re.I,
    )
    if re.search(r"\bMasterMind\b", text, re.I) and _DENIAL_ON_FILE.search(text):
        if _SHARED_BEFORE.search(text) or _STRATEGIC_INFERENCE.search(text):
            fails.append("CQ_REGISTRY_DENIAL_CONTRADICTION:MasterMind")

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
