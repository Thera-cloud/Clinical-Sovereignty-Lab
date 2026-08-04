"""Thera-World Global Symbol Safety System — Layers B/C/D enforcement engine.

Prevents any Thera-World character, NPC, or generated image from carrying a
symbol that could read as threatening, blasphemous, or alienating to a given
client — and makes any client objection ("no more snakes") a permanent,
mechanically-enforced exclusion rather than a one-time apology.

Layers implemented here:
  B  Symbol Risk Registry    — load symbol_risk_registry.json (never/high/medium/low tiers)
  C1 Consent posture         — resolve a user's effective per-symbol state
  C2 Conversational capture  — detect exclusion/opt-in intent in free text + persist it
  C3 Codex / Legend          — build a per-panel or full-registry legend in this user's own posture
  D1 Prompt construction     — sanitize any generated text before it reaches an image model
  D2 Substitution            — swap excluded-symbol language for the registry's abstract/neutral phrasing
  D4 Character resolution    — filter Thera-World character candidates by the user's live posture

Never DROP/ALTER schema from here. All persistence goes through user_symbol_exclusions
(migration 324_symbol_safety.sql), additive only.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "symbol_risk_registry.json")
_REGISTRY_CACHE: Optional[Dict[str, Any]] = None

# Tiers that must NEVER render — no opt-in path exists, ever, for any user.
_NEVER_TIERS = {"never"}
_HIGH_RISK_TIERS = {"high_risk"}
_MEDIUM_RISK_TIERS = {"medium_risk"}

# A Thera-World "character" (CRYSTAL_TO_CHARACTER value) that maps onto a
# registry-governed symbol. Only characters with literal-animal/sacred-figure
# risk need an entry here — abstract characters (Mirror, Reflection, Curiosity,
# Pride/Shame) carry no registry symbol and are always safe.
CHARACTER_TO_SYMBOL: Dict[str, str] = {
    "Serpent": "serpent",
}

# Labeling-only overrides (not exclusions) — swap display language based on
# the user's spiritual_framework. See symbol_risk_registry.json → cultural_label_overrides.
_CHRISTIAN_FRAMEWORKS = {"christian", "catholic", "protestant", "orthodox_christian"}


# ---------------------------------------------------------------------------
# Layer B — Registry
# ---------------------------------------------------------------------------

def load_registry() -> Dict[str, Any]:
    """Load and cache symbol_risk_registry.json. Never raises — returns {} on failure
    so a corrupt/missing registry degrades to 'no symbol filtering' rather than crashing
    the entire Thera-World pipeline (fail-open on load, fail-closed on individual symbols
    is handled by callers treating unknown symbols as unrestricted low_risk)."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE
    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            _REGISTRY_CACHE = json.load(f)
    except Exception as exc:
        logger.error("symbol_safety: failed to load registry at %s: %s", _REGISTRY_PATH, exc)
        _REGISTRY_CACHE = {"version": 0, "symbols": {}, "cultural_label_overrides": {}, "cultural_default_exclusions": {}}
    return _REGISTRY_CACHE


def get_symbol(symbol_id: str) -> Optional[Dict[str, Any]]:
    return load_registry().get("symbols", {}).get(symbol_id)


def all_symbol_ids() -> List[str]:
    return list(load_registry().get("symbols", {}).keys())


def never_tier_ids() -> List[str]:
    reg = load_registry().get("symbols", {})
    return [sid for sid, data in reg.items() if data.get("tier") in _NEVER_TIERS]


def _default_state_for_tier(tier: str) -> str:
    if tier in _NEVER_TIERS:
        return "excluded"
    if tier in _HIGH_RISK_TIERS:
        return "excluded"
    if tier in _MEDIUM_RISK_TIERS:
        return "abstract_only"
    return "allowed"


def cultural_default_exclusions(cultural_context: str = "", spiritual_framework: str = "") -> List[str]:
    """Auto-exclusions triggered by intake fields, before any explicit user action.
    Never overridable by opt-in for the 'never' tier; for other tiers this only sets
    the *default* posture — an explicit opt-in later can still lift it."""
    reg = load_registry()
    table = reg.get("cultural_default_exclusions", {})
    out: List[str] = []
    for raw in filter(None, [(cultural_context or "").lower(), (spiritual_framework or "").lower()]):
        for token in re.split(r"[,/\s]+", raw):
            token = token.strip()
            if token in table:
                out.extend(table[token])
    return list(dict.fromkeys(out))  # de-dupe, preserve order


def apply_cultural_label(character_name: str, spiritual_framework: str = "") -> str:
    """C1 labeling-only override — e.g. 'Holy Spirit' -> 'Guiding Light' for non-Christian users.
    Does NOT change which visual renders, only the display name used in narrative/Codex."""
    reg = load_registry()
    overrides = reg.get("cultural_label_overrides", {})
    if character_name == "Holy Spirit":
        fw = (spiritual_framework or "").lower().strip()
        override = overrides.get("holy_spirit", {})
        if fw and fw not in _CHRISTIAN_FRAMEWORKS and fw not in ("", "none", "unspecified", "agnostic", "spiritual_not_religious"):
            return override.get("non_christian_label", character_name)
    return character_name


# ---------------------------------------------------------------------------
# Layer C1 — Per-user posture resolution
# ---------------------------------------------------------------------------
#
# user_id here is stored verbatim (TEXT) as whatever identifier the caller
# already uses for this user across the Thera-World pipeline — hardware_id
# for orchestrator/panel call sites, matching thera_world_engine.py and
# quest_mission_engine.py. This module does not re-resolve identity; it
# trusts the same string its caller already resolved.

async def get_user_symbol_states(user_id: str, db_pool) -> Dict[str, str]:
    """Return {symbol_id: 'excluded'|'opted_in'|'opted_in_literal'} for every symbol
    the user has explicitly acted on. Symbols not present here fall back to the
    registry's tier default via effective_state()."""
    if not db_pool or not user_id:
        return {}
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT symbol_id, state FROM user_symbol_exclusions WHERE user_id = $1", user_id)
        return {r["symbol_id"]: r["state"] for r in rows}
    except Exception as exc:
        logger.warning("symbol_safety: get_user_symbol_states failed for %s: %s", user_id, exc)
        return {}


async def record_symbol_state(
    user_id: str,
    symbol_id: str,
    state: str,
    db_pool,
    source: str = "conversation",
    note: Optional[str] = None,
) -> bool:
    """Persist a permanent per-user symbol posture. Returns True only on confirmed write —
    callers (esp. LN conversational responses) MUST NOT promise "I'll remember that" unless
    this returns True (spec C2.2 promise-language gating)."""
    if not db_pool or not user_id or not symbol_id:
        return False
    if state not in ("excluded", "opted_in", "opted_in_literal"):
        return False
    # 'never' tier symbols can be excluded by a user but can never be opted into.
    sym = get_symbol(symbol_id)
    if sym and sym.get("tier") in _NEVER_TIERS and state != "excluded":
        logger.warning("symbol_safety: refused opt-in write for never-tier symbol %s (user=%s)", symbol_id, user_id)
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_symbol_exclusions (user_id, symbol_id, state, source, note)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (user_id, symbol_id)
                DO UPDATE SET state = $3, source = $4, note = COALESCE($5, user_symbol_exclusions.note),
                              updated_at = NOW()
                """,
                user_id, symbol_id, state, source, note,
            )
        return True
    except Exception as exc:
        logger.warning("symbol_safety: record_symbol_state write failed for %s/%s: %s", user_id, symbol_id, exc)
        return False


def effective_state(symbol_id: str, user_states: Dict[str, str], auto_excluded: Optional[List[str]] = None) -> str:
    """Combine registry tier default + user override + cultural auto-exclusion into
    one effective posture for this symbol, for this user, right now."""
    sym = get_symbol(symbol_id) or {}
    tier = sym.get("tier", "low_risk")
    if tier in _NEVER_TIERS:
        return "excluded"  # hard floor — no override can lift this
    if symbol_id in user_states:
        return user_states[symbol_id]
    if auto_excluded and symbol_id in auto_excluded:
        return "excluded"
    return _default_state_for_tier(tier)


async def build_posture(user_id: str, db_pool, cultural_context: str = "", spiritual_framework: str = "") -> Dict[str, str]:
    """One-shot: every registry symbol -> effective state, for a given user/context.
    Callers that need to check many symbols per request should call this once and
    reuse the dict rather than calling effective_state() N times with fresh DB round-trips."""
    user_states = await get_user_symbol_states(user_id, db_pool)
    auto = cultural_default_exclusions(cultural_context, spiritual_framework)
    return {sid: effective_state(sid, user_states, auto) for sid in all_symbol_ids()}


# ---------------------------------------------------------------------------
# Layer C2 — Conversational exclusion/opt-in intent detection
# ---------------------------------------------------------------------------

_EXCLUDE_PATTERNS = [
    r"\bno more\b.{0,20}\b{alias}\b",
    r"\bno\b.{0,10}\b{alias}\b.{0,15}\b(again|anymore|any more|please)\b",
    r"\bdon'?t\b.{0,10}(want|like|show me|use)\b.{0,20}\b{alias}\b",
    r"\bstop\b.{0,15}\b{alias}\b",
    r"\bhate\b.{0,10}\b{alias}\b",
    r"\bscared? of\b.{0,10}\b{alias}\b",
    r"\bafraid of\b.{0,10}\b{alias}\b",
    r"\bnever (show|use|put)\b.{0,20}\b{alias}\b",
    r"\bplease (remove|take out|no)\b.{0,20}\b{alias}\b",
    r"\b{alias}\b.{0,20}\b(scares? me|terrifies? me|triggers? me|freaks? me out)\b",
]

_OPT_IN_PATTERNS = [
    r"\b(i'?m|i am) (fine|ok|okay) with\b.{0,20}\b{alias}\b",
    r"\byou can (show|use|include)\b.{0,20}\b{alias}\b",
    r"\bi (like|love|want)\b.{0,10}\b{alias}\b.{0,15}\b(imagery|symbol|shown|showing)\b",
    r"\bit'?s okay to (show|use)\b.{0,20}\b{alias}\b",
]


def _compiled(patterns: List[str], alias: str) -> List[re.Pattern]:
    # NOTE: these regex templates contain literal quantifier braces (e.g. {0,20})
    # which collide with str.format()'s own brace syntax and raise KeyError. Use
    # a plain string replace for the {alias} placeholder instead.
    esc = re.escape(alias)
    return [re.compile(p.replace("{alias}", esc), re.I) for p in patterns]


def detect_exclusion_intent(text: str) -> List[Tuple[str, str]]:
    """Scan free text for exclusion or opt-in intent against every registry alias.
    Returns a list of (symbol_id, 'excluded'|'opted_in') tuples. Deliberately
    conservative — false negatives (missed intent) are safer than false positives
    (accidentally locking in an opt-in the user didn't mean)."""
    text = (text or "").strip()
    if not text or len(text) > 4000:
        return []
    reg = load_registry().get("symbols", {})
    found: List[Tuple[str, str]] = []
    for symbol_id, data in reg.items():
        aliases = [symbol_id.replace("_", " ")] + list(data.get("aliases", []))
        for alias in aliases:
            if not alias or len(alias) < 3:
                continue
            for pat in _compiled(_EXCLUDE_PATTERNS, alias):
                if pat.search(text):
                    found.append((symbol_id, "excluded"))
                    break
            else:
                continue
            break
        else:
            for alias in aliases:
                if not alias or len(alias) < 3:
                    continue
                for pat in _compiled(_OPT_IN_PATTERNS, alias):
                    if pat.search(text):
                        found.append((symbol_id, "opted_in"))
                        break
                else:
                    continue
                break
    return list(dict.fromkeys(found))


async def detect_and_record_exclusion(text: str, user_id: str, db_pool, source: str = "conversation") -> List[Dict[str, Any]]:
    """C2 end-to-end: detect intent in a chat turn, persist it, and return a list of
    {"symbol_id":..., "state":..., "written": bool} so the caller (LN's response
    composer) can gate promise-language on the actual write result."""
    hits = detect_exclusion_intent(text)
    results: List[Dict[str, Any]] = []
    for symbol_id, state in hits:
        written = await record_symbol_state(user_id, symbol_id, state, db_pool, source=source)
        results.append({"symbol_id": symbol_id, "state": state, "written": written})
        if written:
            logger.info("symbol_safety: %s -> %s (%s) for user=%s", symbol_id, state, source, user_id)
        else:
            logger.warning("symbol_safety: detected %s->%s for user=%s but WRITE FAILED — do not promise", symbol_id, state, user_id)
    return results


# ---------------------------------------------------------------------------
# Layer D1/D2 — Prompt sanitization & substitution
# ---------------------------------------------------------------------------

def _alias_regex(symbol_id: str, data: Dict[str, Any]) -> re.Pattern:
    aliases = [symbol_id.replace("_", " ")] + list(data.get("aliases", []))
    aliases = sorted({a for a in aliases if a}, key=len, reverse=True)
    escaped = "|".join(re.escape(a) for a in aliases)
    return re.compile(rf"\b({escaped})\b", re.I)


def build_negative_prompt(excluded_symbol_ids: List[str]) -> str:
    """Comma-joined alias list for image backends that support a negative prompt.
    Always includes every 'never' tier symbol regardless of what's passed in —
    those must never render for ANY user."""
    reg = load_registry().get("symbols", {})
    ids = set(excluded_symbol_ids) | set(never_tier_ids())
    terms: List[str] = []
    for sid in ids:
        data = reg.get(sid, {})
        terms.append(sid.replace("_", " "))
        terms.extend(data.get("aliases", [])[:4])
    return ", ".join(dict.fromkeys(terms))


def sanitize_text(text: str, excluded_symbol_ids: List[str], abstract_symbol_ids: Optional[List[str]] = None) -> str:
    """D2 substitution: rewrite any excluded-symbol alias found in free text (LLM-generated
    narrative or image prompt) into the registry's substitution phrase. 'never' tier symbols
    are always substituted regardless of what's passed in. Medium-risk ('abstract_only')
    symbols are rewritten to their abstract_variant phrasing rather than removed outright."""
    if not text:
        return text
    reg = load_registry().get("symbols", {})
    always_excluded = set(never_tier_ids())
    exclude_set = set(excluded_symbol_ids or []) | always_excluded
    abstract_set = set(abstract_symbol_ids or [])

    out = text
    for sid, data in reg.items():
        if sid not in exclude_set and sid not in abstract_set:
            continue
        pattern = _alias_regex(sid, data)
        if not pattern.search(out):
            continue
        if sid in exclude_set:
            replacement = None
            subs = data.get("substitutions") or []
            if subs:
                replacement = subs[0]
            elif data.get("abstract_variant"):
                replacement = data["abstract_variant"]
            else:
                replacement = "a quiet, unremarkable shape"
        else:  # abstract_only — use the abstract variant, not a full removal
            replacement = data.get("abstract_variant") or (data.get("substitutions") or ["an indistinct shape"])[0]
        out = pattern.sub(replacement, out)
    # Substitution phrases already carry their own article ("a still pool"); when the
    # original text had one too ("near a [shattered mirror]") this leaves "a a still
    # pool". Collapse the doubled article rather than leave grammatically broken text.
    out = re.sub(r"\b(a|an|the)\s+(a|an|the)\b", r"\2", out, flags=re.I)
    return out


async def sanitize_image_prompt(
    prompt: str,
    user_id: str,
    db_pool,
    cultural_context: str = "",
    spiritual_framework: str = "",
) -> Tuple[str, str]:
    """The single call every image-generation call site should make right before
    invoking the model. Returns (sanitized_prompt, negative_prompt).

    This is the D1/D2 safety net: even if a character/NPC choice upstream already
    avoided a symbol, this catches any symbol language the LLM narrative composer
    independently introduced into the free-text prompt."""
    posture = await build_posture(user_id, db_pool, cultural_context, spiritual_framework)
    excluded = [sid for sid, st in posture.items() if st == "excluded"]
    abstract = [sid for sid, st in posture.items() if st == "abstract_only"]
    sanitized = sanitize_text(prompt, excluded, abstract)
    negative = build_negative_prompt(excluded)
    return sanitized, negative


# ---------------------------------------------------------------------------
# Layer D4 — Character resolution filter
# ---------------------------------------------------------------------------

async def filter_character_candidates(
    candidates: List[Tuple[str, str]],
    user_id: str,
    db_pool,
    cultural_context: str = "",
    spiritual_framework: str = "",
) -> List[Tuple[str, str]]:
    """Remove any Thera-World character whose governing registry symbol is not at
    least 'opted_in' for this user, from a candidate list of (name, visual) tuples.
    Characters with no registry symbol (Mirror, Reflection, Curiosity, Pride/Shame,
    Holy Spirit) pass through untouched — only literal-risk characters are gated."""
    if not candidates:
        return candidates
    posture: Optional[Dict[str, str]] = None
    kept: List[Tuple[str, str]] = []
    for name, visual in candidates:
        symbol_id = CHARACTER_TO_SYMBOL.get(name)
        if not symbol_id:
            kept.append((name, visual))
            continue
        if posture is None:
            posture = await build_posture(user_id, db_pool, cultural_context, spiritual_framework)
        state = posture.get(symbol_id, "excluded")
        if state in ("opted_in", "opted_in_literal"):
            if state == "opted_in":
                sym = get_symbol(symbol_id) or {}
                visual = sym.get("abstract_variant") or visual
            kept.append((name, visual))
        # 'excluded' or 'abstract_only' default -> character itself is dropped from
        # candidacy (Layer A: animals aren't in the default lexicon at all until opted in).
    return kept


# ---------------------------------------------------------------------------
# Layer C3 — Codex / Legend
# ---------------------------------------------------------------------------
#
# "Every panel gets a tap-to-reveal legend: each character/symbol in the
# scene, its name, and its meaning in THIS USER'S story ... No unexplained
# recurring figures." (spec C3). These builders describe what the user will
# actually see given their own consent posture, not the abstract cross-
# cultural readings list — that list lives in the registry for reference,
# not as client-facing copy.

def _codex_entry_for_symbol(symbol_id: str, state: str) -> Dict[str, Any]:
    sym = get_symbol(symbol_id) or {}
    tier = sym.get("tier", "low_risk")
    if state == "opted_in_literal":
        readings = sym.get("positive_readings") or []
        meaning = "Shown to you literally, as you asked."
        if readings:
            meaning += f" In your story it carries: {readings[0]}."
    elif state == "opted_in":
        meaning = f"Shown as its abstract form: {sym.get('abstract_variant', 'a softened variant')}."
    elif state == "abstract_only":
        meaning = f"Shown only as its abstract form: {sym.get('abstract_variant', 'a softened variant')}."
    elif state == "excluded":
        subs = sym.get("substitutions") or []
        meaning = (f"Never shown to you. If its narrative role comes up, it appears instead as: "
                   f"{subs[0]}." if subs else "Never shown to you.")
    else:  # allowed
        meaning = "Appears in its ordinary form when the story calls for it."
    return {
        "symbol_id": symbol_id,
        "display_name": symbol_id.replace("_", " ").title(),
        "tier": tier,
        "state": state,
        "meaning": meaning,
    }


def _codex_entry_for_character(character_name: str, posture: Dict[str, str]) -> Dict[str, Any]:
    symbol_id = CHARACTER_TO_SYMBOL.get(character_name)
    if not symbol_id:
        # No registry symbol governs this character (Mirror, Reflection, Guide,
        # Curiosity, Pride/Shame, Holy Spirit) — always safe, describe generically.
        return {
            "symbol_id": None,
            "display_name": character_name,
            "tier": "low_risk",
            "state": "allowed",
            "meaning": "A recurring figure in your story.",
        }
    state = posture.get(symbol_id, "excluded")
    entry = _codex_entry_for_symbol(symbol_id, state)
    entry["display_name"] = character_name
    return entry


async def build_symbol_codex(
    user_id: str, db_pool, cultural_context: str = "", spiritual_framework: str = "",
) -> List[Dict[str, Any]]:
    """C3 — full-registry legend for a settings/review screen: every symbol
    the engine can invoke, with this user's current effective state and what
    it means for them specifically. Powers the onboarding-migration review
    flow (spec acceptance criterion 6) and a general 'my story's language' screen."""
    posture = await build_posture(user_id, db_pool, cultural_context, spiritual_framework)
    return [_codex_entry_for_symbol(sid, state) for sid, state in posture.items()]


async def build_panel_codex(
    character_name: str,
    npc_names: Optional[List[str]],
    user_id: str,
    db_pool,
    cultural_context: str = "",
    spiritual_framework: str = "",
) -> List[Dict[str, Any]]:
    """C3 — tap-to-reveal legend for ONE delivered panel: the panel's primary
    character plus any NPCs, each explained in this user's own consented
    posture. Every name that appears gets an entry — no unexplained figures."""
    posture = await build_posture(user_id, db_pool, cultural_context, spiritual_framework)
    names = [character_name] + list(dict.fromkeys(npc_names or []))
    seen: set = set()
    legend: List[Dict[str, Any]] = []
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        legend.append(_codex_entry_for_character(name, posture))
    return legend
