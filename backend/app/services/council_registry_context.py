"""
Coach-approved council registry for enrichment + SQR validation.

Authoritative part names and descriptions come ONLY from user_parts_registry.
Never infer a part's job from its display name (e.g. MasterMind ≠ strategist).
"""
from __future__ import annotations

import os
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
- ANSWER FROM BOTH CHANNELS: when the client asks about a part that IS listed below, use the stored
  purpose even if nothing was shared in this conversation — then note what has or hasn't come up in the thread.
  Never answer "you haven't told me anything about X" when X is on the registry below.
- REGISTRY VOICE (critical): use stored facts in natural clinical language. Do NOT open with or repeat
  "your registry says…" / "according to my records…" / "on file" unless the client explicitly asked for
  a reminder or quote (e.g. "remind me what X's job is"). Example — natural: "That's the Critic doing
  exactly its job — flagging risk before a high-stakes moment." Example — citation (remind-only):
  "MasterMind's stored purpose is to protect the other parts from outside manipulation."
- RELEVANCE GATE (allowlist): introduce a registered part's stored purpose only when that part is linked
  to the live thread — named in this message, named in the prior user turn, obliquely referenced
  ("the loud one", "that protective part"), asked about explicitly, OR tied to the active session record.
  "What now?" after work on named parts IS continuity — but do NOT pivot to an unrelated registered part
  just because it exists on file (e.g. MasterMind after a Critic/Sovereign breathing win).
- When the client raises a registered part, greet it by its stored role in plain language — do not
  treat a registered part as a stranger.
- After registry-informed reflection, ask ONE curious clinical question when appropriate (e.g. what
  might Sovereign need right now, what is each part trying to protect) — retrieve AND inquire.
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
- DISENGAGEMENT ("whatever", "it's fine", "done talking"): honor the exit immediately. One warm sentence —
  e.g. "Okay. I'm here whenever you want to pick it back up." No "I acknowledge your decision", no exercises,
  no grounding, no questions, no summarizing what they "might really" feel.
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


_RECALL_ABOUT_PART = re.compile(
    r"\b(how is|how(?:'s| are)|tell me about|what do you know about)\b",
    re.I,
)
_CONTINUATION_TURN = re.compile(
    r"\b(what now|what next|helped a little|breathing practice)\b",
    re.I,
)
_REGISTRY_CITATION_INTENT = re.compile(
    r"(?:"
    r"\b(?:remind me|refresh me|tell me again|what(?:'s| is) (?:his|her|their|its) job again)\b"
    r"|(?:wait,?\s*)?what(?:'s| is) (?:his|her|their) (?:job|role|purpose) again\b"
    r"|\bwhich one is \w+"
    r"|\bwhat (?:was|is) \w+(?:'s)? (?:job|role|purpose) on (?:file|record)\b"
    r"|\bwhat does \w+ do (?:on file|in my registry|again)\b"
    r")",
    re.I,
)
_CLINICAL_DATA_INTENT = re.compile(
    r"(?:"
    r"\b(?:diagnose me|give me a diagnosis|tell me if (?:i )?have|can you tell me if (?:i )?have|"
    r"do i have|am i)\b.{0,48}\b(?:ptsd|adhd|bipolar|borderline|anxiety disorder|depression|ocd)\b"
    r"|\b(?:based on|from) (?:our|these|everything we(?:'ve| have)) (?:conversations|sessions|chats|talked about)\b"
    r".{0,30}\b(?:ptsd|diagnos)\b"
    r"|\b(?:ptsd|diagnos(?:is|e)?)\b.{0,40}\b(?:from|based on) (?:our|everything we(?:'ve| have))\b"
    r"|\bclinical (?:data|summary|report)\b.{0,40}\b(?:clinician|therapist|doctor|evaluation)\b"
    r")",
    re.I,
)
_PART_ALIAS_RULES: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:the loud one|inner critic|that critic voice)\b", re.I), "Critic"),
    (re.compile(r"\b(?:that protective part|protector part|the protector)\b", re.I), "MasterMind"),
    (re.compile(r"\b(?:core self|the self part|sovereign part)\b", re.I), "Sovereign"),
)
_MIN_SESSION_FIELDS_FOR_CLINICAL = 1

_REMIND_PROMPT = re.compile(
    r"\b(remind me|what(?:'s| is)\s+\w+(?:'s)?\s+job\b|what was .+ job)\b",
    re.I,
)


def part_named_in_text(user_text: str, part_name: str) -> bool:
    text = user_text or ""
    if part_name == "Sovereign":
        return bool(re.search(r"\bSovereign\b(?!\s+Sanctuary)", text, re.I))
    return bool(re.search(rf"\b{re.escape(part_name)}\b", text, re.I))


def is_registry_citation_intent(user_text: str) -> bool:
    """User asks to recall a registered part's stored role — citation voice allowed."""
    text = user_text or ""
    return bool(_REGISTRY_CITATION_INTENT.search(text) or _REMIND_PROMPT.search(text))


def is_registry_citation_turn(user_text: str, *, prompt_id: str = "") -> bool:
    """Backward-compatible alias — intent only, not slot IDs."""
    return is_registry_citation_intent(user_text)


def is_clinical_data_intent(user_text: str) -> bool:
    return bool(_CLINICAL_DATA_INTENT.search(user_text or ""))


def clinical_summary_export_enabled() -> bool:
    return os.getenv("LN_CLINICAL_SUMMARY_EXPORT", "false").lower() in (
        "1",
        "true",
        "yes",
    )


def resolve_part_references(
    text: str,
    parts: Sequence[Dict[str, str]],
) -> Set[str]:
    if not text:
        return set()
    found: Set[str] = set()
    for p in parts:
        name = p.get("part_name") or ""
        if name and part_named_in_text(text, name):
            found.add(name)
    for pattern, canonical in _PART_ALIAS_RULES:
        if pattern.search(text):
            for p in parts:
                if (p.get("part_name") or "").lower() == canonical.lower():
                    found.add(p["part_name"])
                    break
            else:
                found.add(canonical)
    return found


def active_thread_parts(
    parts: Sequence[Dict[str, str]],
    *,
    prior_user_texts: Optional[Sequence[str]] = None,
    session: Optional[Dict[str, str]] = None,
) -> Set[str]:
    linked: Set[str] = set()
    for t in prior_user_texts or ():
        linked |= resolve_part_references(t, parts)
    if session:
        corpus = " ".join(
            str(session.get(k) or "")
            for k in ("summary", "what_shifted", "open_thread")
        )
        linked |= resolve_part_references(corpus, parts)
    return linked


def registry_part_relevant(
    user_text: str,
    part: Dict[str, str],
    *,
    prior_user_texts: Optional[Sequence[str]] = None,
    session: Optional[Dict[str, str]] = None,
    parts: Optional[Sequence[Dict[str, str]]] = None,
) -> bool:
    """Allowlist: part must tie to current turn, prior user thread, or session record."""
    text = user_text or ""
    name = (part.get("part_name") or "").strip()
    if not name:
        return False
    all_parts = list(parts or [part])
    thread = active_thread_parts(
        all_parts,
        prior_user_texts=prior_user_texts,
        session=session,
    )
    refs_now = resolve_part_references(text, all_parts)
    if name in refs_now:
        return True
    if _RECALL_ABOUT_PART.search(text) and name.lower() in text.lower():
        return True
    if is_registry_citation_intent(text) and name.lower() in text.lower():
        return True
    if _CONTINUATION_TURN.search(text) and name in thread:
        return True
    if name not in thread:
        return False
    desc = (part.get("description") or "").lower()
    if not desc:
        return bool(_CONTINUATION_TURN.search(text))
    hooks = set(re.findall(r"[a-z]{5,}", desc))
    utter = set(re.findall(r"[a-z]{5,}", text.lower()))
    return len(hooks & utter) >= 2


def build_registry_turn_directive(
    user_text: str,
    parts: Sequence[Dict[str, str]],
    *,
    prior_user_texts: Optional[Sequence[str]] = None,
    session: Optional[Dict[str, str]] = None,
    prompt_id: str = "",
) -> str:
    """Deterministic per-turn fusion directive when registered parts are relevant.

    Natural voice by default; citation voice only on remind/quote turns (A3-type).
    Returns "" when no registered part is relevant to this utterance.
    """
    text = user_text or ""
    if not text or not parts:
        return ""
    cite = is_registry_citation_intent(text)
    relevant: List[Dict[str, str]] = []
    for p in parts:
        name = (p.get("part_name") or "").strip()
        if not name:
            continue
        if registry_part_relevant(
            text,
            p,
            prior_user_texts=prior_user_texts,
            session=session,
            parts=parts,
        ):
            relevant.append(p)
    if not relevant:
        return ""
    voice = (
        "CITATION VOICE: the client asked for a reminder — you may quote the stored purpose verbatim."
        if cite
        else "NATURAL VOICE: weave stored purposes into plain clinical language — do NOT say "
        '"your registry says" or "on file".'
    )
    lines = [
        "THIS TURN — REGISTRY FUSION (mandatory): registered part(s) are relevant now.",
        voice,
    ]
    for p in relevant:
        name = p["part_name"]
        desc = (p.get("description") or "").strip()
        if desc:
            lines.append(f'- {name} stored purpose: "{desc}". Use this fact; connect to the thread.')
        else:
            lines.append(
                f"- {name} is registered but purpose is blank — invite the client to define it."
            )
    lines.append("Do NOT deny you have information about these parts. Do NOT open with a denial.")
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


def build_clinical_data_directive(
    user_text: str,
    parts: Sequence[Dict[str, str]],
    session: Optional[Dict[str, str]] = None,
) -> str:
    """Clinician-handoff offer gated on data presence, export capability, and privacy."""
    if not is_clinical_data_intent(user_text):
        return ""
    parts_with_desc = [p for p in parts if (p.get("description") or "").strip()]
    session_fields = sum(
        1
        for k in ("summary", "what_shifted", "open_thread")
        if session and (session.get(k) or "").strip()
    )
    if len(parts_with_desc) == 0 and session_fields < _MIN_SESSION_FIELDS_FOR_CLINICAL:
        return (
            "THIS TURN — CLINICAL DATA BOUNDARY: The user asked for diagnosis or a "
            "clinician summary, but no registry or session record is loaded yet. Do not "
            "invent history. Decline diagnosis; say you need more tracked sessions "
            "before you can walk through patterns together."
        )
    export_ok = clinical_summary_export_enabled()
    if export_ok:
        offer = (
            "You may offer a brief de-identified council pattern summary they could "
            "bring to a licensed clinician evaluation."
        )
    else:
        offer = (
            "Offer ONLY what you can walk through in conversation now — themes and "
            "patterns from loaded registry + session memory. Do NOT claim a download, "
            "export, PDF, or feature that does not exist."
        )
    privacy = (
        "Use themes and patterns only — no raw session quotes, no real names, no "
        "verbatim client disclosures; this artifact may leave the platform."
    )
    return (
        "THIS TURN — CLINICAL DATA OFFER (not diagnosis): "
        f"{offer} {privacy} Never diagnose. Refuse diagnostic labels."
    )


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
