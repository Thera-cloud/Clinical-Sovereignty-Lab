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
    "Dragon Sovereign": "dragon",
    "Death Knight": "skull_bones",
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


def _neuro_champion(name: str) -> Optional[Dict[str, Any]]:
    """QUANTUM-CRYSTAL-ARCH — Neuro region figure lookup (lazy import; None = not Neuro)."""
    try:
        from app.sse.neuro_scoring import champion_by_name
        return champion_by_name(name)
    except Exception:
        return None


def _codex_entry_for_character(character_name: str, posture: Dict[str, str]) -> Dict[str, Any]:
    symbol_id = CHARACTER_TO_SYMBOL.get(character_name)
    champ = _neuro_champion(character_name) if not symbol_id else None
    if champ:
        # Neuro champions are mirrors with a stated purpose — no registry symbol governs them.
        return {
            "symbol_id": None,
            "display_name": champ.get("name") or character_name,
            "tier": "low_risk",
            "state": "allowed",
            "meaning": champ.get("purpose") or (
                f"{character_name} stands in this panel as a mirror for what is emerging in you."
            ),
            "region": "neuro",
        }
    if not symbol_id:
        # No registry symbol governs this character (Mirror, Reflection, Guide,
        # Curiosity, Pride/Shame, Holy Spirit) — always safe, describe generically.
        return {
            "symbol_id": None,
            "display_name": character_name,
            "tier": "low_risk",
            "state": "allowed",
            "meaning": (
                f"{character_name} is one of Little Nate's figures for what is "
                "emerging in you — a presence in the panel, not a random extra."
            ),
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


def _npc_catalog() -> List[Dict[str, str]]:
    """Lazy DOMAIN_TO_NPC read — avoids importing the engine at module load."""
    try:
        from app.sse.thera_world_engine import DOMAIN_TO_NPC
        return list(DOMAIN_TO_NPC.values())
    except Exception:
        return []


def npc_role_for_name(name: str) -> str:
    if not name:
        return ""
    for spec in _npc_catalog():
        if (spec.get("name") or "") == name:
            return (spec.get("role") or "").strip()
    champ = _neuro_champion(name)
    if champ:
        return (champ.get("role") or "").strip()
    return ""


def _neuro_roster_names() -> List[str]:
    try:
        from app.sse.neuro_scoring import load_champions
        return [c.get("name") or "" for c in load_champions()]
    except Exception:
        return []


_THE_PREFIX = re.compile(r"^the\s+", re.I)
_CORE_FIGURES = (
    "Holy Spirit",
    "Pride/Shame",
    "Serpent",
    "Reflection",
    "Curiosity",
    "Mirror",
    "Little Nate",
)


def _name_keys(name: str) -> List[str]:
    n = (name or "").strip()
    if not n:
        return []
    keys = [n.lower()]
    bare = _THE_PREFIX.sub("", n).strip().lower()
    if bare and bare not in keys:
        keys.append(bare)
    if "/" in bare:
        for part in bare.split("/"):
            p = part.strip()
            if len(p) >= 4 and p not in keys:
                keys.append(p)
    return [k for k in keys if len(k) >= 4]


def name_mentioned(name: str, text: str) -> bool:
    """True when a catalog/core name (or its bare form) appears in text."""
    blob = (text or "").lower()
    if not blob or not name:
        return False
    for key in _name_keys(name):
        if re.search(rf"\b{re.escape(key)}\b", blob):
            return True
    return False


def figures_named_in_narrative(narrative: str, biome: str = "") -> List[str]:
    if not (narrative or "").strip():
        return []
    found: List[str] = []
    for spec in _npc_catalog():
        n = (spec.get("name") or "").strip()
        if n and name_mentioned(n, narrative) and n not in found:
            found.append(n)
    for core in _CORE_FIGURES:
        if name_mentioned(core, narrative) and core not in found:
            found.append(core)
    # Neuro roster only scanned for Neuro panels — bare forms like "sovereign",
    # "wonder", "lover" are ordinary words inside Origin narratives.
    if _is_neuro_biome(biome):
        for champ in _neuro_roster_names():
            if champ and champ not in found and _full_name_mentioned(champ, narrative):
                found.append(champ)
    return found


def _full_name_mentioned(name: str, narrative: str) -> bool:
    """Whole-name match only (no bare form): 'The Wonder' must not fire on 'a sense of wonder'."""
    if not name or not narrative:
        return False
    return re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", narrative, re.IGNORECASE) is not None


def _is_neuro_biome(biome: str) -> bool:
    try:
        from app.sse.thera_world_regions import NEURO_BIOMES
        return (biome or "") in NEURO_BIOMES
    except Exception:
        return False


def _excerpt(text: str, limit: int = 160) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return ""
    if len(raw) <= limit:
        return raw
    cut = raw[:limit].rsplit(" ", 1)[0]
    return (cut or raw[:limit]).rstrip(".,;:") + "…"


def _sentence_mentioning(name: str, narrative: str) -> str:
    if not name or not narrative:
        return ""
    needle = name.lower()
    for chunk in re.split(r"(?<=[.!?])\s+", narrative.strip()):
        if needle in chunk.lower():
            return _excerpt(chunk, 180)
    return ""


def compose_figure_in_panel(
    name: str,
    *,
    role: str = "",
    narrative: str = "",
    is_core: bool = False,
    biome: str = "",
) -> str:
    """Client-facing description of what this figure is doing in THIS panel."""
    biome_h = (biome or "").replace("_", " ").strip()
    bits: List[str] = []
    if is_core:
        bits.append(
            f"{name} is the core figure in this panel — the presence Little Nate "
            "placed at the center of what is emerging."
        )
    else:
        bits.append(
            f"{name} is in this panel as a companion figure, not decoration."
        )
    if role:
        bits.append(f"In your story they {role}.")
    mention = _sentence_mentioning(name, narrative)
    if mention:
        bits.append(f"In this scene: {mention}")
    elif biome_h:
        bits.append(f"They appear in {biome_h}.")
    return " ".join(bits)


def compose_prior_note(name: str, prior_panels: Optional[List[Dict[str, Any]]]) -> str:
    if not name:
        return ""
    hits: List[str] = []
    for p in prior_panels or []:
        blob = " ".join(
            filter(None, [p.get("character_manifest") or "", p.get("narrative_text") or ""])
        )
        if not name_mentioned(name, blob):
            continue
        biome = (p.get("biome") or "").replace("_", " ").strip()
        hits.append(biome or "an earlier scene")
    if not hits:
        return ""
    if len(hits) == 1:
        return (
            f"Returned from a prior panel in {hits[0]}. Little Nate is still "
            "working this figure with you across time."
        )
    return (
        f"Has appeared across {len(hits)} earlier panels (most recently {hits[0]}). "
        "A continuing thread in Little Nate's reading of your inner world."
    )


def compose_journey_thread(
    *,
    panel_sequence: int = 0,
    biome: str = "",
    narrative: str = "",
    character_name: str = "",
    prior_panels: Optional[List[Dict[str, Any]]] = None,
    last_panel_summary: str = "",
) -> str:
    """How this panel continues Little Nate's subconscious read over time."""
    biome_h = (biome or "Thera-world").replace("_", " ").strip()
    prior = list(prior_panels or [])
    seq = panel_sequence or (len(prior) + 1)
    parts = [
        f"Panel {seq} of your journey — {biome_h}.",
        "This is Little Nate's continuing read of what is emerging in you, "
        "not a one-off illustration.",
    ]
    if prior:
        prev = prior[0]
        prev_biome = (prev.get("biome") or "").replace("_", " ").strip() or "the last scene"
        prev_char = (prev.get("character_manifest") or "").strip() or "the previous panel"
        excerpt = _excerpt(prev.get("narrative_text") or last_panel_summary or "", 140)
        cont = f"It continues from {prev_char} in {prev_biome}"
        parts.append(f"{cont}: {excerpt}" if excerpt else f"{cont}.")
    if character_name:
        parts.append(f"The core figure here is {character_name}.")
    scene = _excerpt(narrative, 140)
    if scene:
        parts.append(f"What this panel is holding: {scene}")
    return " ".join(parts)


def enrich_panel_legend(
    legend: List[Dict[str, Any]],
    *,
    character_name: str = "",
    narrative_text: str = "",
    biome: str = "",
    npc_details: Optional[List[Dict[str, Any]]] = None,
    prior_panels: Optional[List[Dict[str, Any]]] = None,
    panel_sequence: int = 0,
    last_panel_summary: str = "",
    archetype_hint: str = "",
) -> Dict[str, Any]:
    """C3 payload: figure-level descriptives + journey continuity.

    Pure (no DB). `legend` is the consent-posture list from build_panel_codex.
    Neuro figures additionally carry `purpose` (why this figure stands in the
    panel) and `archetype_mirror` (how they meet the client's archetype). Both
    pass the client language wall — never structure names, never scores.
    """
    neuro_panel = _is_neuro_biome(biome)
    biome_label = biome
    if neuro_panel:
        try:
            from app.sse.thera_world_regions import biome_display_name
            biome_label = biome_display_name(biome)
        except Exception:
            pass
    role_by_name: Dict[str, str] = {}
    for spec in npc_details or []:
        n = (spec.get("name") or "").strip()
        if n:
            role_by_name[n] = (spec.get("role") or "").strip() or npc_role_for_name(n)
    core = (character_name or "").strip()
    entries = list(legend or [])
    if not entries and (narrative_text or biome or core):
        entries = [{
            "symbol_id": None,
            "display_name": core or "The scene",
            "tier": "low_risk",
            "state": "allowed",
            "meaning": (
                "No named companion is foregrounded. The biome and atmosphere "
                "are the language of this panel."
            ),
        }]
    enriched: List[Dict[str, Any]] = []
    for entry in entries:
        row = dict(entry)
        name = (row.get("display_name") or "").strip()
        is_core = bool(core) and name == core
        role = role_by_name.get(name) or npc_role_for_name(name)
        prior_note = compose_prior_note(name, prior_panels)
        row["role"] = role
        row["is_core"] = is_core
        row["seen_before"] = bool(prior_note)
        row["prior_note"] = prior_note
        row["figure_in_panel"] = compose_figure_in_panel(
            name or "This figure",
            role=role,
            narrative=narrative_text,
            is_core=is_core,
            biome=biome_label,
        )
        champ = _neuro_champion(name) if name else None
        if champ:
            row["region"] = "neuro"
            row["purpose"] = _client_safe(champ.get("purpose") or "")
            row["archetype_mirror"] = _client_safe(_archetype_mirror(champ, archetype_hint))
        enriched.append(row)
    return {
        "legend": enriched,
        "journey_thread": compose_journey_thread(
            panel_sequence=panel_sequence,
            biome=biome_label,
            narrative=narrative_text,
            character_name=core,
            prior_panels=prior_panels,
            last_panel_summary=last_panel_summary,
        ),
        "panel_sequence": panel_sequence or (len(prior_panels or []) + 1),
        "biome": biome,
        "biome_label": biome_label,
        "region": "neuro" if neuro_panel else "origin",
        "character": core,
    }


def _archetype_mirror(champ: Dict[str, Any], archetype_hint: str) -> str:
    try:
        from app.sse.neuro_scoring import compose_archetype_mirror
        return compose_archetype_mirror(champ, archetype_hint or "")
    except Exception:
        return ""


def _client_safe(text: str) -> str:
    """Language wall: strip a Neuro legend line rather than leak engine vocabulary."""
    try:
        from app.sse.neuro_scoring import client_safe_violations
        return "" if client_safe_violations(text) else text
    except Exception:
        return text
