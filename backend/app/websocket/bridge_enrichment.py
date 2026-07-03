"""
LN Enrichment Tiers (1-5) — per-turn enrichment that makes a single routed
LLM call smarter on input and stricter on output.

Design constraints:
- All behavior is flag-gated (default OFF) via LN_ENRICHMENT + per-tier flags.
- Zero import-time side effects; heavy services (FederatedSearch, Helix) are
  lazy singletons created on first use.
- Python 3.9 compatible (Optional[...], no PEP 604 unions).
- Every public entry point is exception-safe: failures degrade to no-op.

Tier map:
  Tier 1 — sharper recall helpers (memory-turn detection, lexical global
           re-rank) consumed by crystal_recall_bridge.
  Tier 2 — FederatedSearch + Helix synthesis directive on high-signal turns,
           appended to the system prompt by bridge_server.
  Tier 3 — therapeutic language guard (banned-phrase surgical replacement)
           + next-turn correction directive.
  Tier 4 — session compounding: IFS parts-activity hints folded into the
           Tier 2 directive (recent-thread block + session digest already
           exist in the bridge).
  Tier 5 — per-turn enrichment audit log (JSONL) + offline A/B harness
           (backend/scripts/enrichment_ab_harness.py).
"""
import asyncio
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ─── Flags ────────────────────────────────────────────────────────────────

def _flag(name: str, default: str = "") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in ("1", "true", "yes", "on")


def enrichment_enabled() -> bool:
    """Master switch. All bridge hooks check this first."""
    return _flag("LN_ENRICHMENT")


def tier_enabled(tier: int) -> bool:
    """Per-tier override. Defaults to the master flag when unset."""
    val = os.getenv(f"LN_T{tier}_ENRICH", "")
    if val.strip():
        return _flag(f"LN_T{tier}_ENRICH")
    return enrichment_enabled()


# ─── Tier 1: recall helpers ──────────────────────────────────────────────

_MEMORY_TURN_RE = re.compile(
    r"\b(do you remember|you remember|remember when|last time|last session|"
    r"we talked about|we discussed|you said|i told you|as i mentioned|"
    r"like i said|what did i say|bring up again|earlier you|previously)\b",
    re.IGNORECASE,
)

_STOPWORDS = frozenset(
    "a an the and or but if then this that these those i you he she it we they "
    "my your his her its our their me him them is are was were be been being "
    "have has had do does did will would can could should shall may might of "
    "in on at to for with from about as by not no so very just really".split()
)


def is_memory_turn(text: str) -> bool:
    """True when the user is explicitly reaching back into shared history."""
    return bool(text and _MEMORY_TURN_RE.search(text))


def _query_tokens(text: str) -> Set[str]:
    return {
        t for t in re.findall(r"[a-z']{3,}", (text or "").lower())
        if t not in _STOPWORDS
    }


def lexical_rerank_globals(
    cached_rows: List[dict],
    query_text: str,
    limit: int,
    seen_ids: Set[Any],
) -> List[dict]:
    """Re-rank the cached global crystal pool by token overlap with the
    current turn, blended with stored confidence.  Falls back to
    confidence order (the pre-existing behavior) when the query is thin.

    Returns up to `limit` rows not already in `seen_ids`; adds picked ids
    to `seen_ids` so the caller's dedup stays consistent.
    """
    q_tokens = _query_tokens(query_text)
    candidates = [r for r in cached_rows if r.get("id") not in seen_ids]
    if len(q_tokens) >= 2:
        scored = []
        for r in candidates:
            c_tokens = _query_tokens(r.get("crystal_text") or "")
            overlap = len(q_tokens & c_tokens) / float(len(q_tokens))
            conf = float(r.get("confidence") or 0.0)
            scored.append((overlap * 0.6 + conf * 0.4, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        picked = [r for _, r in scored[:limit]]
    else:
        picked = candidates[:limit]
    for r in picked:
        seen_ids.add(r.get("id"))
    return picked


# ─── Tier 4: IFS parts-activity hints ────────────────────────────────────

_IFS_PART_SIGNALS = [
    ("Manager", re.compile(
        r"\b(i have to|i should|i must|keep it together|stay in control|"
        r"plan(ning)? everything|perfect|can't afford to|on top of)\b", re.I)),
    ("Firefighter", re.compile(
        r"\b(numb|shut (it |myself )?down|drink|drank|binge|scroll(ing)?|"
        r"blow(ing)? up|rage|explode|escape|check(ed)? out|distract)\b", re.I)),
    ("Exile", re.compile(
        r"\b(worthless|unlovable|never enough|abandoned|small|ashamed|"
        r"nobody (wants|sees)|deep down|little (kid|girl|boy)|hidden)\b", re.I)),
    ("Protector", re.compile(
        r"\b(wall(s)? up|won't let|guard(ed)?|keep (them|people) (out|away)|"
        r"don't trust|push(ed)? (them |people )?away|defend)\b", re.I)),
]


def ifs_part_hints(user_text: str) -> List[str]:
    """Detect which IFS parts are speaking in this turn (coach-approved labels)."""
    if not user_text:
        return []
    return [name for name, patt in _IFS_PART_SIGNALS if patt.search(user_text)]


# ─── Tier 2: FederatedSearch + Helix synthesis directive ────────────────

_HIGH_SIGNAL_RE = re.compile(
    r"\b(feel|felt|afraid|scared|ashamed|shame|guilt|angry|hurt|pain|"
    r"trauma|triggered|lonely|alone|abandoned|hopeless|stuck|pattern|"
    r"always|never|marriage|divorce|father|mother|childhood|can't stop|"
    r"crying|tears|worthless|numb|dissociat|suicid|die|death)\b",
    re.IGNORECASE,
)

_fed_search = None          # FederatedSearchCoordinator singleton
_helix = None               # HelixOrchestrator singleton
_T2_TIMEOUT_S = float(os.getenv("LN_T2_TIMEOUT_S", "2.5"))
_T2_MAX_CHARS = int(os.getenv("LN_T2_MAX_CHARS", "1400"))
_T2_MIN_TURN_LEN = int(os.getenv("LN_T2_MIN_TURN_LEN", "60"))


def is_high_signal_turn(user_text: str) -> bool:
    """A turn worth the extra ~2s of enrichment latency: emotionally loaded,
    memory-reaching, or a substantial disclosure."""
    if not user_text:
        return False
    if is_memory_turn(user_text):
        return True
    if len(user_text) < _T2_MIN_TURN_LEN:
        return False
    return len(_HIGH_SIGNAL_RE.findall(user_text)) >= 2


# ─── Clinical priority overrides (SQ-2 / AQ-3 / AQ-4 / witnessing) ───────

_CONTROL_MARKERS = re.compile(
    r"\b(i need you to|don't ask me about|just give me|"
    r"i don't want to talk about feelings|actionable|practical|"
    r"stop asking|that's not helpful|can we focus on|"
    r"i need strategies not therapy|give me a list|tell me what to do)\b",
    re.I,
)
_INTELLECTUALIZATION = re.compile(
    r"\b(depersonalization|attachment style|tachycardia|cortisol|amygdala|"
    r"precipitating stressor|textbook case|from a research perspective|"
    r"logically i understand|diagnos(?:is|ed)|symptom(?:s)? of)\b",
    re.I,
)
_WITNESSING = re.compile(
    r"\b(suicid(?:e|al)?|kill myself|end it all|don't want to live|"
    r"homicid|want to hurt|moral injur|cleared hot|"
    r"rage toward|fantasy of violence|can't forgive what)\b",
    re.I,
)
_UNSOLVABLE = re.compile(
    r"\b(terminal|dying child|child is dying|irreversible|"
    r"nothing will bring|can't be fixed|no way to save|"
    r"will never walk again|inoperable)\b",
    re.I,
)


def detect_priority_overrides(user_text: str) -> List[str]:
    """Return active override keys for this turn (parallel_process, somatic,
    witnessing, helplessness). Used by enrichment addendum + benchmark harness."""
    if not user_text:
        return []
    active: List[str] = []
    if _CONTROL_MARKERS.search(user_text):
        active.append("parallel_process")
    if _INTELLECTUALIZATION.search(user_text):
        active.append("somatic_interrupt")
    if _WITNESSING.search(user_text):
        active.append("witnessing")
    if _UNSOLVABLE.search(user_text):
        active.append("therapeutic_helplessness")
    return active


def build_priority_override_addendum(user_text: str) -> str:
    """Compact THIS-TURN directive when override markers fire. Mirrors bridge
    PRIORITY OVERRIDES block but scoped to detected signals."""
    if not enrichment_enabled():
        return ""
    active = detect_priority_overrides(user_text)
    if not active:
        return ""
    lines = [
        "THIS-TURN PRIORITY OVERRIDE (fires before all other response logic):"
    ]
    if "parallel_process" in active:
        lines.append(
            "- PARALLEL PROCESS: client used control/demand language. Do NOT "
            "answer their question or give strategies. Mirror the control "
            "dynamic in the room, then stop."
        )
    if "somatic_interrupt" in active:
        lines.append(
            "- SOMATIC INTERRUPT: client is intellectualizing. Do NOT discuss "
            "diagnosis or validate analysis. Interrupt and ask what is "
            "happening in their body right now."
        )
    if "witnessing" in active:
        lines.append(
            "- WITNESSING: lethality/violence/moral injury present. Do NOT "
            "refuse, hedge, or give safety disclaimers. Witness what they "
            "carry without solving."
        )
    if "therapeutic_helplessness" in active:
        lines.append(
            "- THERAPEUTIC HELPLESSNESS: unsolvable loss. Do NOT offer coping "
            "lists, reframes, or exercises. Acknowledge you cannot fix it; "
            "stay present."
        )
    return "\n".join(lines)


def _get_fed_search(db_pool):
    global _fed_search
    if _fed_search is None:
        from app.services.quantum_knowledge_field import FederatedSearchCoordinator
        _fed_search = FederatedSearchCoordinator(db_pool=db_pool, app_state=None)
    return _fed_search


def _get_helix():
    global _helix
    if _helix is None:
        from app.services.helix_orchestrator import HelixOrchestrator
        _helix = HelixOrchestrator()
    return _helix


async def build_enrichment_addendum(db_pool, user_id: str, user_text: str) -> str:
    """Tier 2 + 4: on high-signal turns, run FederatedSearch over the crystal
    field and a Helix think() cycle, and distill both into a compact
    synthesis directive appended to the system prompt.

    Bounded by _T2_TIMEOUT_S; returns "" on any failure or low-signal turn.
    Priority overrides fire even on low-signal turns when markers match.
    """
    if not enrichment_enabled():
        return ""
    priority_block = build_priority_override_addendum(user_text)
    if not tier_enabled(2):
        return priority_block[:_T2_MAX_CHARS] if priority_block else ""
    if not is_high_signal_turn(user_text):
        return priority_block[:_T2_MAX_CHARS] if priority_block else ""
    t0 = time.monotonic()
    crystals: List[Dict[str, Any]] = []
    try:
        fed = _get_fed_search(db_pool)
        result = await asyncio.wait_for(
            fed.search(
                query=user_text[:400],
                user_id=user_id,
                include_devices=False,
                timeout_seconds=_T2_TIMEOUT_S,
                domain="clinical",
            ),
            timeout=_T2_TIMEOUT_S + 0.5,
        )
        crystals = (result or {}).get("results", [])[:6]
    except Exception as e:
        logger.info("bridge_enrichment: federated search skipped: %s", e)

    synthesis_line = ""
    if tier_enabled(2):
        try:
            helix = _get_helix()
            cycle = await asyncio.wait_for(
                helix.think(query=user_text[:400], crystals=crystals),
                timeout=_T2_TIMEOUT_S,
            )
            syn = cycle.synthesis or {}
            odpe = cycle.odpe_result or {}
            signal = odpe.get("signal") or odpe.get("dominant_signal") or ""
            coherence = syn.get("sovereignty_adjusted") or syn.get("fused_coherence")
            bits = []
            if signal:
                bits.append(f"signal={signal}")
            if coherence is not None:
                bits.append(f"coherence={coherence}")
            if bits:
                synthesis_line = (
                    "Helix read on this turn: " + ", ".join(str(b) for b in bits)
                    + ". Treat high-coherence recall below as established shared "
                    "history; treat low coherence as tentative — verify before "
                    "referencing."
                )
        except Exception as e:
            logger.info("bridge_enrichment: helix synthesis skipped: %s", e)

    lines: List[str] = []
    approved_names: set = set()
    if _flag("BRIDGE_IFS_METADATA"):
        try:
            from app.services.council_registry_context import (
                build_council_context,
                crystal_mentions_unlisted_part,
                fetch_registry_parts,
                registry_part_names,
            )
            reg_rows = await fetch_registry_parts(db_pool, user_id)
            approved_names = registry_part_names(reg_rows)
            council = await build_council_context(db_pool, user_id)
            if council:
                lines.insert(0, council)
        except Exception as e:
            logger.info("bridge_enrichment: council registry skipped: %s", e)

    ranked = []
    for c in crystals:
        text = (c.get("crystal_text") or c.get("text") or "").strip()
        if not text:
            continue
        rel = c.get("relevance_score", c.get("confidence", 0))
        ranked.append((float(rel or 0), text[:280]))
    ranked.sort(key=lambda x: x[0], reverse=True)
    if ranked:
        lines.append(
            "RANKED RECALL FOR THIS TURN (most relevant first — weave the top "
            "items into your response naturally, in the client's own words):"
        )
        shown = 0
        for rel, text in ranked:
            if approved_names and crystal_mentions_unlisted_part(
                text, approved_names, user_text=user_text,
            ):
                continue
            lines.append(f"- ({rel:.2f}) {text}")
            shown += 1
            if shown >= 4:
                break
    if synthesis_line:
        lines.append(synthesis_line)

    if tier_enabled(4):
        parts = ifs_part_hints(user_text)
        if parts:
            lines.append(
                "PARTS ACTIVITY (IFS): the client's language suggests these "
                f"parts are active this turn: {', '.join(parts)}. Speak to the "
                "part gently and by function, not by label, unless the client "
                "already uses parts language."
            )

    if priority_block:
        lines.insert(0, priority_block)

    if not lines:
        return ""
    block = "PER-TURN SYNTHESIS DIRECTIVE:\n" + "\n".join(lines)
    if len(block) > _T2_MAX_CHARS:
        block = block[:_T2_MAX_CHARS]
    logger.info(
        "bridge_enrichment: addendum built in %.0fms (%d crystals, %d chars)",
        (time.monotonic() - t0) * 1000, len(ranked), len(block),
    )
    return block


# ─── Tier 3: therapeutic language guard ──────────────────────────────────

# Mirrors LINGUISTIC DISCIPLINE — ABSOLUTE BAN in the bridge system prompt.
# Surgical replacement only: streaming output cannot be regenerated, so we
# swap warmth-noise for neutral concrete phrasing and issue a next-turn
# correction directive.
_BANNED_REPLACEMENTS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bliminal\b", re.I), "in-between"),
    (re.compile(r"\bhold(?:ing)? space\b", re.I), "staying with you"),
    (re.compile(r"\bsit with that\b", re.I), "stay with what you just said"),
    (re.compile(r"\bhonor your journey\b", re.I), "respect what you've lived through"),
    (re.compile(r"\bin-between space\b", re.I), "middle ground"),
    (re.compile(r"\bsacred ground\b", re.I), "important ground"),
    (re.compile(r"\baching\b", re.I), "raw"),
    (re.compile(r"\btender place\b", re.I), "sore spot"),
    (re.compile(r"\bI hear you\b", re.I), "That lands"),
    (
        re.compile(r"\bI(?:'m| am) a large language model[^.!?]*[.!?]?\s*", re.I),
        "",
    ),
    (
        re.compile(
            r"\byou're doing the best you can, and that's something to be proud of\b",
            re.I,
        ),
        "you're carrying a lot right now",
    ),
    (re.compile(r"\bSteady presence with you\b", re.I), "With you"),
    (re.compile(r"\bwitnessing it right here\b", re.I), "right here with you"),
    (re.compile(r"\bwitnessing it with you\b", re.I), "here with you"),
    (re.compile(r"\bholding steady\b", re.I), "staying with you"),
    # "threshold" and bare "tender" are riskier to auto-swap (legit clinical
    # uses exist, e.g. pain threshold); they get flagged, not replaced.
]
_BANNED_FLAG_ONLY: List[re.Pattern] = [
    re.compile(r"\bthreshold\b", re.I),
    re.compile(r"\btender\b", re.I),
]

_STAMP_DEDUP: List[re.Pattern] = [
    re.compile(r"\bSteady presence with you\b", re.I),
    re.compile(r"\bwitnessing it (?:right here|with you)\b", re.I),
    re.compile(r"\bholding steady\b", re.I),
]
_stamp_seen: Dict[str, set] = {}
# Per-uid correction directive for the NEXT turn's system prompt.
_pending_corrections: Dict[str, List[str]] = {}
_MAX_PENDING_USERS = 500


def apply_language_guard(text: str, uid: Optional[str] = None) -> Tuple[str, List[str]]:
    """Replace banned warmth-noise phrases in the final response.

    Returns (cleaned_text, hits).  When `uid` is given and anything was
    hit (replaced or flagged), a correction directive is queued for that
    user's next turn.
    """
    if not tier_enabled(3) or not text:
        return text, []
    hits: List[str] = []
    cleaned = text
    for patt, repl in _BANNED_REPLACEMENTS:
        if patt.search(cleaned):
            hits.append(patt.pattern)
            cleaned = patt.sub(repl, cleaned)
    if uid:
        seen = _stamp_seen.setdefault(uid, set())
        if len(_stamp_seen) > _MAX_PENDING_USERS:
            _stamp_seen.clear()
            seen = _stamp_seen.setdefault(uid, set())
        for patt in _STAMP_DEDUP:
            if patt.search(cleaned):
                key = patt.pattern
                if key in seen:
                    cleaned = patt.sub("With you", cleaned)
                    hits.append(key + " (repeat)")
                else:
                    seen.add(key)
    for patt in _BANNED_FLAG_ONLY:
        if patt.search(cleaned):
            hits.append(patt.pattern + " (flagged)")
    if hits and uid:
        if len(_pending_corrections) > _MAX_PENDING_USERS:
            _pending_corrections.clear()
        _pending_corrections[uid] = hits
    return cleaned, hits


def pop_correction_directive(uid: str) -> str:
    """One-shot directive injected into the NEXT turn's system prompt after
    a banned-phrase hit.  Consumed on read."""
    if not tier_enabled(3):
        return ""
    hits = _pending_corrections.pop(uid, None)
    if not hits:
        return ""
    return (
        "CORRECTION DIRECTIVE (from your previous turn): your last response "
        "used banned filler language. This turn, use ONLY the client's own "
        "words or concrete sensory description. No abstractions about space, "
        "journeys, or thresholds."
    )


# ─── Tier 5: enrichment turn audit ───────────────────────────────────────

_AUDIT_PATH = os.getenv(
    "LN_ENRICH_AUDIT_PATH",
    os.path.join(os.getenv("DATA_DIR", "data"), "enrichment_audit.jsonl"),
)
_audit_lock = asyncio.Lock()


def _hash_uid(uid: str) -> str:
    return hashlib.sha256((uid or "").encode()).hexdigest()[:12]


def log_turn_audit(
    uid: str = "",
    provider: str = "",
    latency_ms: int = 0,
    prompt_chars: int = 0,
    crystal_chars: int = 0,
    response_chars: int = 0,
    guard_hits: int = 0,
    enrichment_addendum_chars: int = 0,
) -> None:
    """Fire-and-forget JSONL audit row per turn (Tier 5). No PII: uid hashed,
    no message text stored."""
    if not tier_enabled(5):
        return
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "uid": _hash_uid(uid),
        "provider": provider,
        "latency_ms": latency_ms,
        "prompt_chars": prompt_chars,
        "crystal_chars": crystal_chars,
        "response_chars": response_chars,
        "guard_hits": guard_hits,
        "addendum_chars": enrichment_addendum_chars,
        "flags": {f"t{i}": tier_enabled(i) for i in range(1, 6)},
    }

    async def _write():
        try:
            async with _audit_lock:
                os.makedirs(os.path.dirname(_AUDIT_PATH) or ".", exist_ok=True)
                with open(_AUDIT_PATH, "a") as f:
                    f.write(json.dumps(row) + "\n")
        except Exception as e:
            logger.debug("bridge_enrichment: audit write failed: %s", e)

    try:
        asyncio.get_event_loop().create_task(_write())
    except RuntimeError:
        pass


def apply_ln_post_llm_pipeline(
    text: str,
    user_text: str,
    uid: Optional[str] = None,
    registry_parts: Optional[List[str]] = None,
) -> Tuple[str, List[Dict[str, Any]], List[str]]:
    """Boundary router (crisis/depth/hypo) then Tier-3 language guard — QUANTUM-CRYSTAL-ARCH."""
    from app.services.crisis_response_router import apply_ln_boundary_post_guard

    cleaned, boundary_hits = apply_ln_boundary_post_guard(
        text or "",
        user_text or "",
        registry_parts=registry_parts,
    )
    cleaned, lang_hits = apply_language_guard(cleaned, uid=uid)
    return cleaned, boundary_hits, lang_hits
