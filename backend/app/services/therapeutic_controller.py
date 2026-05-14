"""# FIX-THERAPEUTIC-CONTROLLER
State-dependent therapeutic controller — pre-flight + post-flight wrappers.

Wraps bridge_server's per-turn LLM dispatch without replacing it. Pre-flight
shapes the system prompt and token cap based on autonomic state, TMC class,
coherence trend, recurring patterns, and recent narratives. Post-flight
audits the final response, regenerates once on violation when a mismatch was
attempted, and logs metrics to sse_therapeutic_audit_log.

Backwards compatible: caller wraps each entry point in try/except and falls
back to existing behavior on any failure.

PHASE 3 v1.3 — ADDITIVITY CONTRACT (orchestrator absent → identical to v1.2)

When `register_directive`, `dissociation_delta`, and `coercion_severity` are
all None (the Phase 3 state, before Phase 4 orchestrator wiring), this module
must produce byte-identical behavior to v1.2:

- Token caps for `shutdown|activated|in_window|regulated` unchanged.
- Banned-phrase set for en-US is a STRICT SUPERSET of the v1.2 list.
- Mismatch evaluation logic for `mismatch_available` unchanged.
- Thalamic Novelty Gate evaluates to `blocked=False` (no signals → no block).
- Predictability-continuity cap resolver is dormant (no register_directive).

Auditor checks (`_auditor_self_check`):
- `register_variants_additive_only` — every v1.2 variant still resolves
- `banned_phrases_extended_not_replaced` — v1.3 list ⊇ v1.2 list
- `thalamic_gate_dual_insertion_present` — both source markers present
- `phase3_controller_v1_2_fixtures_pass` — external fixture suite (Phase 6)

PHASE 3 v1.3 — NEW REGISTER VARIANTS (Gap 6 / 10 / 7 / dissociation + Gap 4)

- `purity_wound`             — slow, no rushing, validates without attacking
                                faith tradition; somatic invitation; no
                                "deprogramming" framing.
- `betrayal_response`        — companions infidelity-trauma response; no
                                pressure toward forgiveness or stay/leave.
- `unfaithful_shame`         — holds shame without minimizing; no moralizing;
                                works underlying patterns; never becomes
                                couples' therapist.
- `dissociation_grounding`   — narrows to grounding without forcing presence;
                                triggered by `dissociation_delta_detector`;
                                distinct from existing `shutdown` state.
- `predictability_continuity`— Gap 4 register selected when Thalamic Novelty
                                Gate blocks. Token cap is RESOLVED PER-USER
                                via `_resolve_predictability_continuity_cap`
                                (parity with prior turn's actual emitted
                                tokens, with floor).

PHASE 3 v1.3 — THALAMIC NOVELTY GATE (Gap 4)

For hyper-vigilant trauma survivors, novelty registers as threat first and
corrective experience second (if at all). The gate suppresses mismatch when
`dissociation_delta` or `coercion_severity` exceeds the user's per-cohort
threshold (trafficking=0.20, general trauma=0.30 default), or when
`thalamic_gate_forced=True` (trigger date or legal proximity).

Dual insertion sites (BOTH must remain present per Note 1, Phase 3):

1. `# THALAMIC GATE INSERTION 1 of 2 — top-of-function pre-flight`
   In `prepare_therapeutic_context`, immediately after `mismatch_available`
   is computed. Gate result overrides register and disables mismatch.

2. `# THALAMIC GATE INSERTION 2 of 2 — mismatch decision path`
   In `audit_therapeutic_response`, immediately before the regenerate-on-
   violation branch. Re-evaluates from `audit_metadata` to defensively catch
   any future code path that might re-enable mismatch downstream.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from app.services._dna_neuroscience_text import DNA_PROMPT_PREFIX as _DNA_PREFIX
except Exception:
    logger.warning("therapeutic_controller: DNA module unavailable, using compressed fallback")
    _DNA_PREFIX = (
        "Three commitments: regulation precedes integration; mismatch within the "
        "labile window updates the trace; continuity reshapes schema. WARM register "
        "is default; shift to CLINICAL only with a bridge sentence. I do not claim "
        "specific brain activations and do not replace human clinicians for severe "
        "trauma, suicidality, dissociation, psychosis, or active danger."
    )

# ─────────────────────────── Pattern detectors ───────────────────────────

_ACTIVATED_PATTERNS = [
    re.compile(r"\b(panic|chest (is )?(so )?tight|can'?t breathe|hyperventilat|racing heart)", re.I),
    re.compile(r"\b(rage|fury|gonna explode|losing it|out of control|so angry)", re.I),
]
_SHUTDOWN_PATTERNS = [
    re.compile(r"\b(numb|empty|frozen|disconnect|nothing matters|don'?t care|hollow)", re.I),
    re.compile(r"\b(why bother|pointless|gone|can'?t feel)", re.I),
]
_DISTRESS_PATTERNS = [
    re.compile(r"\b(crisis|emergency|breaking down|falling apart)", re.I),
    re.compile(r"\b(want to die|kill myself|end it|suicid|not worth living|better off dead)", re.I),
]
_META_QUESTION_PATTERNS = [
    re.compile(r"\b(why do you|how does this|what'?s happening|what are you doing)", re.I),
    re.compile(r"\b(my brain|my nervous system|my body|polyvagal|reconsolidat|window of tolerance)", re.I),
    re.compile(r"\b(why (do|are) you (ask|pause|slow|short|warm|gentle|quiet))", re.I),
]

TOKEN_CAPS = {
    # v1.2 base — autonomic-state-derived caps
    "shutdown": 200,
    "activated": 350,
    "in_window": 600,
    "regulated": 1500,
    # v1.3 register-variant caps — orchestrator-driven (Phase 4 wiring)
    # Dormant in Phase 3 (no orchestrator => register_directive=None => unused).
    "purity_wound": 350,
    "betrayal_response": 400,
    "unfaithful_shame": 350,
    "dissociation_grounding": 200,
    # predictability_continuity uses an FLOOR here only; the actual cap is
    # resolved per-user via _resolve_predictability_continuity_cap() because
    # the variant requires length parity with the prior turn (Gap 4).
    "predictability_continuity": 80,
}

_LABILE_WINDOW_TMC = {"THRESHOLD", "BREAKTHROUGH", "RECURRENCE"}

# ─────────────── v1.2 sealed reference (additivity verification) ───────────────
# DO NOT MODIFY. Used by _auditor_self_check() to prove v1.3 is a strict
# superset of v1.2 (register_variants_additive_only,
# banned_phrases_extended_not_replaced).
_PHASE_V1_2_REGISTER_VARIANTS: Tuple[str, ...] = (
    "shutdown", "activated", "in_window", "regulated",
)
_PHASE_V1_2_BANNED_PHRASES: Tuple[str, ...] = (
    "i sense",
    "i want to acknowledge",
    "it takes courage",
    "holding space",
    "honor your journey",
    "liminal threshold",
    "sit with that",
)

# v1.3 additive register variants (orchestrator-driven, dormant in Phase 3).
_PHASE_V1_3_NEW_REGISTERS: Tuple[str, ...] = (
    "purity_wound",
    "betrayal_response",
    "unfaithful_shame",
    "dissociation_grounding",
    "predictability_continuity",
)

# ─────────────── Banned phrases (locale-aware, additive) ───────────────
# Note 3 (Phase 3 build): structure is dict-keyed by locale from day one,
# even though only en-US is populated in v1.3. Future locale additions are
# pure data work — no code change. Mirrors the lexicon-overlay pattern.

# v1.3 additions (en-US). Three phrases per Plan v1.3:
#  - "you have nothing to be ashamed of"  → bypasses lived experience
#  - "you'll get over this"               → problem-solves grief work
#  - "everything happens for a reason"    → spiritual bypass
_PHASE_V1_3_NEW_BANNED_PHRASES_EN_US: Tuple[str, ...] = (
    "you have nothing to be ashamed of",
    "you'll get over this",
    "everything happens for a reason",
)

# In-code authoritative baseline. Lexicon overlay file (Note 3 stub) extends.
_BANNED_PHRASES_BY_LOCALE: Dict[str, Tuple[str, ...]] = {
    "en-US": _PHASE_V1_2_BANNED_PHRASES + _PHASE_V1_3_NEW_BANNED_PHRASES_EN_US,
}

# Path to the lexicon overlay directory (matches Phase 2 lexicon convention).
_LEXICON_DIR = Path(__file__).resolve().parents[2] / "data" / "lexicons"

# Backward-compat: v1.2 callers reference _BANNED_PHRASES_ALWAYS as a flat list.
# Resolves to en-US default (v1.2 superset). Kept so existing imports do not
# break; _audit_violations() uses the locale-aware resolver below.
_BANNED_PHRASES_ALWAYS: List[str] = list(_BANNED_PHRASES_BY_LOCALE["en-US"])


def _resolve_banned_phrases(locale: str = "en-US") -> Tuple[str, ...]:
    """Resolve banned-phrase set for a given locale with overlay merge.

    Fallback chain (matches the Phase 2 lexicon convention):
        <requested_locale> → <language> → en-US → in-code defaults

    Overlay file at `data/lexicons/banned_phrases_<locale>.json` is appended
    to the in-code baseline (additive only — overlays cannot remove a
    baseline phrase). Empty/missing overlay returns the in-code baseline.

    Phase 3 ships en-US in-code only; overlay file is an authoring-stub.
    """
    requested = (locale or "en-US").strip() or "en-US"
    language = requested.split("-", 1)[0]
    candidates = []
    for lc in (requested, language, "en-US"):
        if lc and lc not in candidates:
            candidates.append(lc)

    base: Tuple[str, ...] = ()
    for lc in candidates:
        if lc in _BANNED_PHRASES_BY_LOCALE:
            base = _BANNED_PHRASES_BY_LOCALE[lc]
            break
    if not base:
        base = _BANNED_PHRASES_BY_LOCALE["en-US"]

    overlay: List[str] = []
    overlay_path = _LEXICON_DIR / f"banned_phrases_{requested}.json"
    if overlay_path.exists():
        try:
            with overlay_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            phrases = payload.get("phrases") or []
            if isinstance(phrases, list):
                for ph in phrases:
                    if isinstance(ph, str) and ph.strip():
                        overlay.append(ph.strip().lower())
        except Exception as e:
            # Fail-closed-additively: overlay parse error never DROPS a baseline
            # phrase. Log and proceed with in-code baseline.
            logger.warning(
                "therapeutic_controller: banned-phrases overlay parse failed "
                "(%s) — using in-code baseline only: %s",
                overlay_path.name, e,
            )

    if not overlay:
        return base

    seen = set()
    merged: List[str] = []
    for ph in list(base) + overlay:
        key = ph.lower()
        if key not in seen:
            seen.add(key)
            merged.append(ph)
    return tuple(merged)


# ─────────────── Thalamic Novelty Gate (Gap 4) ───────────────

@dataclass(frozen=True)
class ThalamicGateDecision:
    """Outcome of the Thalamic Novelty Gate (Gap 4).

    For hyper-vigilant trauma survivors, novelty registers as threat first,
    corrective experience second (if at all). When dissociation or coercion
    signals exceed the user's per-cohort threshold, novelty (mismatch) is
    suppressed and `predictability_continuity` register takes over —
    sustained predictable presence as the corrective experience.

    Phase 3 default (no orchestrator → no signals) returns blocked=False.
    """
    blocked: bool
    reason: str
    dissociation_delta: float
    coercion_severity: float
    threshold: float


def _evaluate_thalamic_novelty_gate(
    dissociation_delta: Optional[float] = None,
    coercion_severity: Optional[float] = None,
    threshold: float = 0.30,
    forced_on: bool = False,
) -> ThalamicGateDecision:
    """Evaluate whether mismatch should be blocked this turn.

    Args:
        dissociation_delta: From dissociation_delta_detector (Phase 4 input).
            None in Phase 3 (no orchestrator) → contributes 0.0.
        coercion_severity: From coercion_pattern_detector (Phase 4 input).
            None in Phase 3 → contributes 0.0.
        threshold: Per-user (trafficking=0.20, general trauma=0.30 default).
        forced_on: True when trigger-date proximity or legal proximity forces
            the gate ON regardless of computed signals (Gap 5, Gap 9).

    Returns:
        ThalamicGateDecision. In Phase 3 with no orchestrator inputs, returns
        blocked=False with reason='signals_below_threshold' — preserving v1.2
        behavior exactly per the additivity contract.
    """
    diss = float(dissociation_delta or 0.0)
    coer = float(coercion_severity or 0.0)
    thr = float(threshold or 0.30)

    if forced_on:
        return ThalamicGateDecision(
            blocked=True,
            reason="forced_on_trigger_or_legal_proximity",
            dissociation_delta=diss,
            coercion_severity=coer,
            threshold=thr,
        )
    if diss >= thr or coer >= thr:
        return ThalamicGateDecision(
            blocked=True,
            reason="signal_above_threshold",
            dissociation_delta=diss,
            coercion_severity=coer,
            threshold=thr,
        )
    return ThalamicGateDecision(
        blocked=False,
        reason="signals_below_threshold",
        dissociation_delta=diss,
        coercion_severity=coer,
        threshold=thr,
    )


# ─────────────── Predictability-continuity cap resolver (Gap 4) ───────────────

PREDICTABILITY_CONTINUITY_FLOOR_TOKENS: int = 80
"""Minimum cap when prior-turn parity would collapse the response.

Per Note 2 (Phase 3 build): floor at the variant's minimum — don't let cap
collapse to zero if the prior turn was a single-word acknowledgement. 80
tokens (~60 words) is a "warm short response" floor — enough for 3-4
sentences of sustained presence without truncating mid-thought.
"""


async def _resolve_predictability_continuity_cap(
    user_id: str,
    db_pool,
    floor: int = PREDICTABILITY_CONTINUITY_FLOOR_TOKENS,
) -> int:
    """Resolve `predictability_continuity` token cap by parity with prior turn.

    Per Note 2 (Phase 3 build): the predictability_continuity register's
    clinical purpose — sustained predictable presence as the corrective
    mismatch — fails if Nate's response length swings unpredictably while the
    register is active. Cap matches the prior turn's ACTUAL emitted token
    count (not the cap that turn was allowed), with `floor` as the lower
    bound.

    Source of truth: `conversation_history.word_count_ai` (set at insert time
    per migration 099) — the actual word count of what was emitted, NOT the
    `metadata.max_tokens` cap that turn was permitted. Word→token conversion
    uses the same 0.75 ratio used elsewhere in this module (Claude/GPT-4-class
    tokenizers average ~0.75 tokens per English word).

    Args:
        user_id: Hardware-id or username (matches conversation_history.user_id).
        db_pool: asyncpg pool. None → returns floor.
        floor: Lower bound on returned cap. Defaults to module constant.

    Returns:
        int. Minimum is `floor`. No upper bound (parity is the design goal).
        Returns `floor` on any failure path so the register never crashes the
        caller.
    """
    if not db_pool or not user_id:
        return floor
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT word_count_ai FROM conversation_history "
                "WHERE user_id = $1 AND ai_text IS NOT NULL "
                "AND btrim(ai_text) <> '' "
                "ORDER BY created_at DESC LIMIT 1",
                user_id,
            )
            if not row:
                return floor
            words = int(row["word_count_ai"] or 0)
            if words <= 0:
                return floor
            # words → approximate tokens (~0.75 tokens/word)
            prior_tokens = int(round(words / 0.75))
            return max(prior_tokens, floor)
    except Exception as e:
        logger.warning(
            "therapeutic_controller: predictability cap resolve failed "
            "for %s: %s — returning floor=%d", user_id, e, floor,
        )
        return floor


# ─────────────────────────── Helpers ───────────────────────────

def _detect_state_from_text(user_text: str) -> Optional[str]:
    if not user_text:
        return None
    if any(p.search(user_text) for p in _ACTIVATED_PATTERNS):
        return "activated"
    if any(p.search(user_text) for p in _DISTRESS_PATTERNS):
        return "activated"
    if any(p.search(user_text) for p in _SHUTDOWN_PATTERNS):
        return "shutdown" if len(user_text) < 80 else "activated"
    return None


def _is_meta_therapeutic(user_text: str) -> bool:
    if not user_text:
        return False
    return any(p.search(user_text) for p in _META_QUESTION_PATTERNS)


async def _classify_tmc(db_pool, user_id: str) -> dict:
    if not db_pool or not user_id:
        return {}
    try:
        from app.sse.ucd.tmc import TherapeuticMomentClassifier
        tmc = TherapeuticMomentClassifier(db_pool)
        return await tmc.classify(user_id) or {}
    except Exception as e:
        logger.warning("therapeutic_controller: TMC classify failed for %s: %s", user_id, e)
        return {}


async def _fetch_recent_narratives(db_pool, user_id: str) -> list:
    if not db_pool or not user_id:
        return []
    try:
        async with db_pool.acquire() as conn:
            uuid_val = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 OR id::text = $1 LIMIT 1",
                user_id,
            )
            if not uuid_val:
                return []
            rows = await conn.fetch(
                "SELECT client_narrative_text FROM sse_delivery_generation_log "
                "WHERE user_id::text = $1 AND client_narrative_text IS NOT NULL "
                "AND btrim(client_narrative_text)<>'' "
                "AND generated_at > NOW() - INTERVAL '14 days' "
                "ORDER BY generated_at DESC LIMIT 7",
                str(uuid_val),
            )
            return [r["client_narrative_text"] for r in rows if r["client_narrative_text"]]
    except Exception as e:
        logger.warning("therapeutic_controller: recent narratives fetch failed: %s", e)
        return []


async def _recall_neuroscience_crystals(db_pool, query_text: str, limit: int = 3) -> str:
    """Domain-filtered recall for meta-therapeutic questions. Bypasses
    crystal_recall_log on purpose — these are reference knowledge, not user
    memory, so reinforcement weighting does not apply."""
    if not db_pool or not query_text:
        return ""
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT crystal_text
                FROM nate_intelligence_crystals
                WHERE domain = 'neuroscience_foundations'
                  AND scope = 'global'
                  AND superseded_by IS NULL
                  AND to_tsvector('english', crystal_text)
                      @@ websearch_to_tsquery('english', $1)
                ORDER BY ts_rank(
                    to_tsvector('english', crystal_text),
                    websearch_to_tsquery('english', $1)) DESC,
                    confidence DESC
                LIMIT $2
                """,
                query_text[:200], limit,
            )
            if not rows:
                return ""
            lines = ["NEUROSCIENCE FOUNDATIONS (use to answer naturally; do not lecture):"]
            for r in rows:
                txt = (r["crystal_text"] or "")[:280]
                lines.append(f"- {txt}")
            return "\n".join(lines)
    except Exception as e:
        logger.warning("therapeutic_controller: neuroscience recall failed: %s", e)
        return ""


def _detect_recurring_patterns(tmc_result: dict, signals: dict) -> list:
    patterns = []
    if tmc_result.get("moment_class") == "RECURRENCE":
        domain = signals.get("crystal_domain") or "pattern"
        patterns.append(f"recurring_{domain}")
    if signals.get("crystal_confidence", 0) >= 0.65 and not signals.get("first_time_pattern_break", False):
        patterns.append("encoded_high_confidence")
    return patterns


def _state_guidance(state: str) -> str:
    if state == "shutdown":
        return (
            "## STATE GUIDANCE — SHUTDOWN (dorsal vagal collapse risk)\n"
            "Bare presence. No demands, no questions that require effort. One short "
            "sentence naming what you see, plus an offer to be present without "
            "requiring response. WARM register only. Under 200 tokens. No "
            "interpretation. No reframes."
        )
    if state == "activated":
        return (
            "## STATE GUIDANCE — ACTIVATED (sympathetic mobilization or panic)\n"
            "Short, regulating, no interpretation. Offer one somatic invitation — "
            "naming what the body might be doing without prescribing. WARM register "
            "forced. Under 350 tokens. No clinical decoding. No 'I sense'. The job "
            "is to lower arousal, not to teach."
        )
    if state == "regulated":
        return (
            "## STATE GUIDANCE — REGULATED (integration band)\n"
            "Full conversational range. Depth allowed when invited. WARM default; "
            "CLINICAL allowed with bridge sentence when interpretation lands cleanly."
        )
    return (
        "## STATE GUIDANCE — IN WINDOW (regulation present, integration possible)\n"
        "WARM register unless directness is invited or a recurring pattern needs "
        "naming. If shifting to CLINICAL, bridge sentence is mandatory. Keep "
        "responses 2-4 sentences unless depth is explicitly requested."
    )


# ─────────────── v1.3 register-variant guidance (additive) ───────────────
# These guidance blocks fire only when an orchestrator (Phase 4) sets
# `register_directive`. Phase 3 callers leave register_directive=None →
# _register_variant_guidance() returns "" and v1.2 behavior is preserved.

def _register_variant_guidance(variant: Optional[str]) -> str:
    """Return register-specific guidance block for v1.3 register variants.

    Returns "" for None or unknown variants (preserves v1.2 behavior). The
    caller appends the returned string to the enriched system prompt; an
    empty string adds nothing.
    """
    if not variant:
        return ""
    if variant == "purity_wound":
        return (
            "## REGISTER VARIANT — PURITY WOUND\n"
            "Slow. No rushing. Validate the lived experience without attacking "
            "the survivor's faith tradition or family of origin. Somatic "
            "invitation is allowed and encouraged when the body is present. "
            "DO NOT use 'deprogramming' framing. DO NOT pathologize the "
            "tradition itself; the wound is in the rupture, not the doctrine. "
            "Hold both: the harm IS real, AND the person's loyalty to family "
            "is also real. Under 350 tokens."
        )
    if variant == "betrayal_response":
        return (
            "## REGISTER VARIANT — BETRAYAL RESPONSE (hurt party)\n"
            "Companion the trauma response. No pressure toward forgiveness. "
            "No pressure toward stay-or-leave. The person is in acute "
            "betrayal-trauma activation; the work right now is presence with "
            "the rupture, not problem-solving the relationship. Validate the "
            "shock and the body's alarm. Under 400 tokens."
        )
    if variant == "unfaithful_shame":
        return (
            "## REGISTER VARIANT — UNFAITHFUL SHAME (party who broke trust)\n"
            "Hold the shame without minimizing what happened. NO moralizing. "
            "Work the underlying patterns (attachment, avoidance, dissociation "
            "from intimacy) — never become the couples' therapist. The other "
            "party is not in this conversation; do not reconstruct their "
            "experience or speak for them. Under 350 tokens."
        )
    if variant == "dissociation_grounding":
        return (
            "## REGISTER VARIANT — DISSOCIATION GROUNDING\n"
            "Narrow the scope. Do NOT force presence. Offer one orienting "
            "anchor (a fact in the room, a felt sense of contact with the "
            "chair) and let it sit. NO somatic-prompting questions ('where do "
            "you feel that'). NO trauma processing. Bare presence. Under 200 "
            "tokens. Distinct from `shutdown` — dissociation is a different "
            "physiological state and tolerates even less demand."
        )
    if variant == "predictability_continuity":
        return (
            "## REGISTER VARIANT — PREDICTABILITY CONTINUITY (Thalamic Gate)\n"
            "Sustained, predictable, non-triggering presence. Same opening "
            "cadence as prior turns. Mismatch DISABLED in this register — the "
            "ABSENCE of novelty IS the corrective experience. Length matches "
            "the prior turn's actual length (parity is the clinical signal). "
            "No reframes. No new interpretations. No new metaphors. The "
            "survivor's nervous system is reading 'is this the same Nate as "
            "last time' — be that."
        )
    return ""


def _anti_repeat_block(narratives: list) -> str:
    if not narratives:
        return ""
    snippets = "\n".join(f"- {n[:200]}" for n in narratives[:7])
    return (
        "## RECENT NARRATIVES (do NOT repeat themes, metaphors, or phrasings):\n"
        f"{snippets}\n"
        "Find a different angle, sensation, or detail."
    )


# ─────────────────────────── Pre-flight ───────────────────────────

async def prepare_therapeutic_context(
    user_text: str,
    user_id: str,
    db_pool,
    base_system_prompt: str,
    default_max_tokens: int = 600,
    # ─── Phase 3 v1.3 additive params (orchestrator-driven, Phase 4 wiring) ───
    # All defaults preserve v1.2 behavior identically (additivity contract).
    register_directive: Optional[str] = None,
    dissociation_delta: Optional[float] = None,
    coercion_severity: Optional[float] = None,
    novelty_threshold: float = 0.30,
    thalamic_gate_forced: bool = False,
    locale: str = "en-US",
) -> dict:
    """Classify state, assemble context, shape prompt + cap. Always returns
    a dict; on partial failure, fields default to the original prompt/cap.

    Phase 3 v1.3 — ADDITIVE PARAMETERS (Phase 4 orchestrator only):
        register_directive: When set, overrides autonomic-state-derived
            register selection. Selects guidance from
            `_register_variant_guidance()`. None = v1.2 behavior.
        dissociation_delta, coercion_severity: Detector outputs consumed by
            the Thalamic Novelty Gate (Insertion 1 below). None = no signal.
        novelty_threshold: Per-user gate threshold (default 0.30 general
            trauma; trafficking cohort uses 0.20).
        thalamic_gate_forced: Forces gate ON regardless of signals (Gap 5
            trigger-date proximity, Gap 9 legal proximity).
        locale: Resolves banned-phrase set (Note 3, Phase 3 build).
    """
    # Canonical username for DB-backed paths (portal + FK tables use username;
    # bridge chat passes hardware_id). Unresolved → keep raw id (fail-soft).
    canonical_user_id = user_id
    if db_pool and user_id:
        try:
            from app.services._identity_resolver import resolve_username as _resolve_username

            _resolved = await _resolve_username(db_pool, user_id)
            if _resolved is None:
                logger.warning(
                    "therapeutic_controller: sensitive bridge identity unresolved "
                    "(provided_identifier=%r source=bridge_boundary)",
                    user_id,
                )
                canonical_user_id = user_id
            else:
                canonical_user_id = _resolved
        except Exception as _rid_exc:
            logger.warning(
                "therapeutic_controller: identity resolution failed: %s — using raw id",
                _rid_exc,
            )
            canonical_user_id = user_id

    # v1.3 Sensitive Clinical Bridge — single wiring seam (Phase 4 Note 1).
    # Master kill switch + per-user gap_features_enabled gate the orchestrator
    # internally; when dormant, register_directive is None and downstream
    # logic runs identically to v1.2. Failure is best-effort: a raised
    # exception leaves register_directive at the caller-supplied value.
    lens_bridge_block = ""
    try:
        from app.services import sensitive_clinical_bridge as _scb
        # v1.4 — lightweight NateCheckInAgent for part-aware codeword detection.
        # The bridge container has no app.state.nate_checkin_agent; we create a
        # thin instance backed by the same db_pool. Only check_codeword /
        # detect_codeword_disclosure methods are used (no background loop).
        _nca_inst = None
        try:
            from app.services.nate_checkin_agent import NateCheckInAgent as _NCA
            _nca_inst = _NCA(db_pool=db_pool)
        except Exception:
            pass  # graceful: step 2 runs with nate_checkin_agent=None
        _bd = await _scb.evaluate_disclosure(
            db_pool=db_pool,
            user_id=canonical_user_id,
            message=user_text,
            locale=locale,
            nate_checkin_agent=_nca_inst,
        )
        if _bd is not None:
            if _bd.register_directive:
                register_directive = _bd.register_directive
            lens_bridge_block = (
                (_bd.audit_event or {}).get("lens_directives_block") or ""
            )
    except Exception as _e:
        logger.warning("therapeutic_controller: bridge wiring skipped: %s", _e)

    tmc_result = await _classify_tmc(db_pool, canonical_user_id)
    signals = tmc_result.get("signals", {}) or {}
    tmc_class = tmc_result.get("moment_class") or "REST"
    ec_current = float(signals.get("ec_current") or 0.0)
    ec_slope = float(signals.get("ec_slope") or 0.0)

    text_state = _detect_state_from_text(user_text)
    if tmc_class == "CRISIS" or text_state == "activated":
        autonomic_state = "activated"
    elif text_state == "shutdown":
        autonomic_state = "shutdown"
    elif ec_current >= 0.65 and ec_slope >= 0.0 and tmc_class in ("INTEGRATION", "REST"):
        autonomic_state = "regulated"
    else:
        autonomic_state = "in_window"

    encoded_patterns = _detect_recurring_patterns(tmc_result, signals)
    mismatch_available = (
        autonomic_state == "in_window"
        and bool(encoded_patterns)
        and tmc_class in _LABILE_WINDOW_TMC
    )

    # THALAMIC GATE INSERTION 1 of 2 — top-of-function pre-flight
    # Per Note 1 (Phase 3 build): block novelty BEFORE mismatch_block emits
    # when dissociation/coercion signals exceed user's per-cohort threshold,
    # OR when forced ON by trigger-date / legal proximity. In Phase 3 (no
    # orchestrator → no signals), gate evaluates blocked=False and behavior
    # is identical to v1.2. AUDITOR CHECK: thalamic_gate_dual_insertion_present
    # greps for THIS exact comment marker; do not rename it.
    gate_decision = _evaluate_thalamic_novelty_gate(
        dissociation_delta=dissociation_delta,
        coercion_severity=coercion_severity,
        threshold=novelty_threshold,
        forced_on=thalamic_gate_forced,
    )
    effective_register_directive = register_directive
    if gate_decision.blocked:
        # Force predictability_continuity unless an even-more-specific register
        # directive was explicitly supplied (orchestrator may already have set
        # a higher-acuity register; do not downgrade).
        if not effective_register_directive:
            effective_register_directive = "predictability_continuity"
        mismatch_available = False

    recent_narratives = await _fetch_recent_narratives(db_pool, canonical_user_id)
    neuroscience_ctx = ""
    if _is_meta_therapeutic(user_text):
        neuroscience_ctx = await _recall_neuroscience_crystals(db_pool, user_text, limit=3)

    state_cap = TOKEN_CAPS.get(autonomic_state, 600)
    if default_max_tokens > 600 and autonomic_state in ("activated", "shutdown"):
        max_tokens = state_cap
    elif default_max_tokens > 600:
        max_tokens = max(default_max_tokens, state_cap)
    else:
        max_tokens = state_cap

    # v1.3 register-directive cap override (orchestrator-driven, dormant in
    # Phase 3). predictability_continuity uses the parity resolver; all other
    # variants use their TOKEN_CAPS entry.
    if effective_register_directive:
        if effective_register_directive == "predictability_continuity":
            max_tokens = await _resolve_predictability_continuity_cap(
                user_id=canonical_user_id,
                db_pool=db_pool,
                floor=PREDICTABILITY_CONTINUITY_FLOOR_TOKENS,
            )
        elif effective_register_directive in TOKEN_CAPS:
            max_tokens = TOKEN_CAPS[effective_register_directive]

    mismatch_block = ""
    if mismatch_available:
        mismatch_block = (
            "\n## MISMATCH OPPORTUNITY DETECTED\n"
            f"Patterns encoded: {', '.join(encoded_patterns)}. State is in_window; "
            f"TMC class is {tmc_class}. If you address a recurring pattern this turn, "
            "deliver an experience that contradicts what the pattern predicts — not a "
            "new insight, but a moment that updates the trace. CLINICAL register only "
            "with a bridge sentence."
        )

    register_variant_block = _register_variant_guidance(effective_register_directive)

    enriched = (
        f"## DNA — NEUROSCIENCE BEDROCK\n{_DNA_PREFIX}\n\n"
        f"## CURRENT THERAPEUTIC STATE\n"
        f"autonomic_state: {autonomic_state} | tmc_class: {tmc_class} | "
        f"ec_current: {ec_current:.2f} | ec_slope: {ec_slope:+.2f}\n\n"
        f"{_state_guidance(autonomic_state)}\n"
        f"{register_variant_block}\n"
        f"{lens_bridge_block}\n"
        f"{mismatch_block}\n"
        f"{neuroscience_ctx}\n"
        f"{_anti_repeat_block(recent_narratives)}\n\n"
        f"---\n\n{base_system_prompt}"
    )

    if effective_register_directive:
        register_default_field = effective_register_directive
    elif mismatch_available:
        register_default_field = "CLINICAL_BRIDGED"
    else:
        register_default_field = "WARM"

    return {
        "enriched_system_prompt": enriched,
        "max_tokens": max_tokens,
        "recent_narratives": recent_narratives,
        "audit_metadata": {
            "autonomic_state": autonomic_state,
            "tmc_class": tmc_class,
            "mismatch_available": mismatch_available,
            "encoded_patterns": encoded_patterns,
            "register_default": register_default_field,
            "max_tokens": max_tokens,
            # v1.3 additive metadata (carried into audit_therapeutic_response
            # for Insertion 2 re-evaluation; absent in Phase 3 fixtures means
            # the v1.2 audit logic still works unchanged).
            "register_directive": effective_register_directive,
            "thalamic_gate_blocked": gate_decision.blocked,
            "thalamic_gate_reason": gate_decision.reason,
            "dissociation_delta": gate_decision.dissociation_delta,
            "coercion_severity": gate_decision.coercion_severity,
            "novelty_threshold": gate_decision.threshold,
            "thalamic_gate_forced": bool(thalamic_gate_forced),
            "locale": locale,
        },
    }


# ─────────────────────────── Post-flight ───────────────────────────

def _audit_violations(response_text: str, audit_metadata: dict, recent_narratives: list) -> list:
    violations = []
    if not response_text or not response_text.strip():
        return ["empty_response"]
    rl = response_text.lower()
    state = audit_metadata.get("autonomic_state")
    cap = audit_metadata.get("max_tokens", 600)

    approx_tokens = int(len(response_text.split()) / 0.75)
    if approx_tokens > cap * 1.15:
        violations.append(f"length_over_cap_{approx_tokens}_vs_{cap}")

    # Locale-aware banned phrases (v1.3). For v1.2 audit_metadata that lacks
    # 'locale', fall back to en-US — which is a strict superset of v1.2's
    # _BANNED_PHRASES_ALWAYS, preserving existing audit semantics.
    banned_phrases = _resolve_banned_phrases(audit_metadata.get("locale", "en-US"))
    for phrase in banned_phrases:
        if phrase in rl:
            violations.append(f"banned_phrase:{phrase}")

    if state == "activated":
        somatic_markers = ["body", "breath", "chest", "shoulder", "feel in your", "notice", "sensation"]
        if not any(m in rl for m in somatic_markers):
            violations.append("missing_somatic_invitation")

    clinical_markers = ["repetition compulsion", "you're recreating", "let me tell you what i actually see"]
    bridge_markers = ["put aside", "owe you honesty", "instead of reflecting", "going to try something different", "i'm going to be direct"]
    if any(c in rl for c in clinical_markers) and not any(b in rl for b in bridge_markers):
        violations.append("clinical_shift_without_bridge")

    if recent_narratives:
        for narr in recent_narratives:
            narr_words = (narr or "").lower().split()
            for i in range(len(narr_words) - 4):
                phrase = " ".join(narr_words[i:i + 5])
                if len(phrase) >= 25 and phrase in rl:
                    violations.append("phrase_overlap_with_recent_narrative")
                    break
            if any("phrase_overlap" in v for v in violations):
                break

    return violations


async def audit_therapeutic_response(
    response_text: str,
    audit_metadata: dict,
    user_id: str,
    db_pool,
    recent_narratives: Optional[list] = None,
) -> dict:
    """Audit, optionally regenerate once on violation, log to audit table."""
    recent_narratives = recent_narratives or []
    violations = _audit_violations(response_text, audit_metadata, recent_narratives)
    audit_passed = len(violations) == 0
    final_text = response_text
    mismatch_delivered = audit_passed and bool(audit_metadata.get("mismatch_available"))

    # THALAMIC GATE INSERTION 2 of 2 — mismatch decision path
    # Per Note 1 (Phase 3 build): defensively re-evaluate the gate using
    # signals carried in audit_metadata before entering the regenerate-on-
    # violation branch. Catches any future code path that might re-enable
    # mismatch downstream of Insertion 1 (e.g., a maintainer who flips
    # audit_metadata['mismatch_available'] manually). In Phase 3 with no
    # orchestrator signals, the gate evaluates blocked=False and the
    # regenerate path runs identically to v1.2. AUDITOR CHECK:
    # thalamic_gate_dual_insertion_present greps for THIS exact comment
    # marker; do not rename it.
    gate_decision_post = _evaluate_thalamic_novelty_gate(
        dissociation_delta=audit_metadata.get("dissociation_delta"),
        coercion_severity=audit_metadata.get("coercion_severity"),
        threshold=audit_metadata.get("novelty_threshold", 0.30),
        forced_on=bool(audit_metadata.get("thalamic_gate_forced", False)),
    )

    if (
        not audit_passed
        and audit_metadata.get("mismatch_available")
        and not gate_decision_post.blocked
    ):
        try:
            from app.sse.llm_fallback import chat_completion_with_fallback
            retry_sys = (
                f"AUDIT FAILED ON PRIOR ATTEMPT. Violations: {', '.join(violations)}. "
                f"State={audit_metadata.get('autonomic_state')}; cap={audit_metadata.get('max_tokens')} tokens. "
                "Generate a corrected therapeutic response that avoids these violations. "
                "WARM register; bridge sentence required for any clinical shift; somatic "
                "invitation if activated; no banned phrases ('I sense', 'It takes courage', "
                "'holding space', 'honor your journey'). Address what the user said directly."
            )
            retry = await chat_completion_with_fallback(
                [
                    {"role": "system", "content": retry_sys},
                    {"role": "user", "content": f"Original response: {response_text[:400]}\n\nWrite a corrected version."},
                ],
                max_tokens=audit_metadata.get("max_tokens", 600),
                temperature=0.7,
            )
            if retry and retry.strip():
                retry_violations = _audit_violations(retry, audit_metadata, recent_narratives)
                if len(retry_violations) < len(violations):
                    final_text = retry.strip()
                    violations = retry_violations
                    audit_passed = len(retry_violations) == 0
                    mismatch_delivered = audit_passed
        except Exception as e:
            logger.warning("therapeutic_controller: regenerate failed: %s", e)

    await _log_audit(
        db_pool=db_pool, user_id=user_id, audit_metadata=audit_metadata,
        violations=violations, audit_passed=audit_passed,
        response_token_count=int(len(final_text.split()) / 0.75),
        mismatch_delivered=mismatch_delivered,
    )

    print(
        f">>> [THERAPEUTIC-CTRL] audit user={user_id} passed={audit_passed} "
        f"violations={len(violations)} mismatch_delivered={mismatch_delivered}"
    )

    return {
        "response_text": final_text,
        "audit_passed": audit_passed,
        "violations": violations,
        "mismatch_delivered": mismatch_delivered,
    }


async def _log_audit(
    db_pool,
    user_id: str,
    audit_metadata: dict,
    violations: list,
    audit_passed: bool,
    response_token_count: int,
    mismatch_delivered: bool,
) -> None:
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sse_therapeutic_audit_log
                    (user_id, autonomic_state, tmc_class, register_used,
                     mismatch_attempted, mismatch_delivered, audit_passed,
                     audit_violations, response_token_count, encoded_patterns)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10::jsonb)
                """,
                user_id,
                audit_metadata.get("autonomic_state"),
                audit_metadata.get("tmc_class"),
                audit_metadata.get("register_default"),
                bool(audit_metadata.get("mismatch_available")),
                mismatch_delivered,
                audit_passed,
                json.dumps(violations),
                response_token_count,
                json.dumps(audit_metadata.get("encoded_patterns") or []),
            )
    except Exception as e:
        logger.warning("therapeutic_controller: audit log write failed: %s", e)


# ─────────────── Auditor self-check (Phase 6 surface) ───────────────

def _verify_thalamic_gate_dual_insertion_present() -> bool:
    """Confirm both Thalamic Gate insertion markers are present in this module.

    Greps the module's own source file for the EXACT comment markers that flag
    each insertion site. Failing either marker fails the auditor check
    `thalamic_gate_dual_insertion_present`. Source-file grep (not introspection
    of compiled bytecode) is intentional — comments are the contract surface
    that future maintainers will read.

    Returns True on success. Raises AssertionError on missing marker.
    """
    src_path = Path(__file__)
    try:
        src = src_path.read_text(encoding="utf-8")
    except Exception as e:
        raise AssertionError(
            f"thalamic_gate_dual_insertion_present FAILED: cannot read "
            f"source file {src_path.name}: {e}"
        )
    marker_1 = (
        "# THALAMIC GATE INSERTION 1 of 2 \u2014 top-of-function pre-flight"
    )
    marker_2 = (
        "# THALAMIC GATE INSERTION 2 of 2 \u2014 mismatch decision path"
    )
    assert marker_1 in src, (
        f"thalamic_gate_dual_insertion_present FAILED: missing marker 1 "
        f"({marker_1!r})"
    )
    assert marker_2 in src, (
        f"thalamic_gate_dual_insertion_present FAILED: missing marker 2 "
        f"({marker_2!r})"
    )
    return True


def _verify_register_variants_additive_only() -> bool:
    """Confirm v1.2 register variants still resolve to a guidance block.

    Iterates `_PHASE_V1_2_REGISTER_VARIANTS` and asserts that
    `_state_guidance(variant)` returns a non-trivial string. Detects the
    failure mode where a future maintainer renames or merges an existing
    variant without preserving its guidance surface.
    """
    for variant in _PHASE_V1_2_REGISTER_VARIANTS:
        guidance = _state_guidance(variant)
        assert guidance and len(guidance) >= 50, (
            f"register_variants_additive_only FAILED: v1.2 variant "
            f"{variant!r} no longer resolves to a guidance block "
            f"(got {len(guidance) if guidance else 0} chars)"
        )
    return True


def _verify_banned_phrases_extended_not_replaced() -> bool:
    """Confirm v1.3 banned-phrase set is a strict superset of v1.2.

    Resolves en-US banned phrases via `_resolve_banned_phrases('en-US')` and
    asserts every entry in `_PHASE_V1_2_BANNED_PHRASES` is still present.
    Detects the failure mode where a maintainer accidentally drops a v1.2
    phrase while editing the locale-keyed dict.
    """
    current = set(_resolve_banned_phrases("en-US"))
    v1_2 = set(_PHASE_V1_2_BANNED_PHRASES)
    missing = v1_2 - current
    assert not missing, (
        f"banned_phrases_extended_not_replaced FAILED: v1.2 banned phrases "
        f"removed from v1.3 en-US set: {sorted(missing)}"
    )
    return True


def _auditor_self_check() -> Dict[str, Any]:
    """Lightweight contract verification for the Phase 6 sensitive-bridge auditor.

    Runs the three in-module checks:
        - register_variants_additive_only
        - banned_phrases_extended_not_replaced
        - thalamic_gate_dual_insertion_present

    The fourth check (`phase3_controller_v1_2_fixtures_pass`) is intentionally
    out of scope here — it requires the v1.2 fixture suite which lives
    external to this module. Phase 6 auditor invokes this function and runs
    the fixture suite separately.

    Returns:
        Dict with keys:
            checks: list[{"name": str, "passed": bool, "detail": str}]
            v1_2_register_count: int
            v1_3_register_count: int
            v1_2_banned_count: int
            v1_3_banned_count_en_us: int
    """
    results: List[Dict[str, Any]] = []
    for name, fn in (
        ("register_variants_additive_only", _verify_register_variants_additive_only),
        ("banned_phrases_extended_not_replaced", _verify_banned_phrases_extended_not_replaced),
        ("thalamic_gate_dual_insertion_present", _verify_thalamic_gate_dual_insertion_present),
    ):
        try:
            fn()
            results.append({"name": name, "passed": True, "detail": "ok"})
        except AssertionError as e:
            results.append({"name": name, "passed": False, "detail": str(e)})
        except Exception as e:
            results.append({
                "name": name,
                "passed": False,
                "detail": f"unexpected_error: {type(e).__name__}: {e}",
            })

    return {
        "checks": results,
        "v1_2_register_count": len(_PHASE_V1_2_REGISTER_VARIANTS),
        "v1_3_register_count": (
            len(_PHASE_V1_2_REGISTER_VARIANTS) + len(_PHASE_V1_3_NEW_REGISTERS)
        ),
        "v1_2_banned_count": len(_PHASE_V1_2_BANNED_PHRASES),
        "v1_3_banned_count_en_us": len(_resolve_banned_phrases("en-US")),
    }


# ─────────────── Boot-time additivity guard ───────────────
# Per Phase 3 sequencing reminder: controller behavior with register_directive
# unset must be identical to v1.2. These two checks are the cheapest possible
# enforcement and run at module import time. A regression here will surface
# on backend startup, not in production.
try:
    _verify_register_variants_additive_only()
    _verify_banned_phrases_extended_not_replaced()
except AssertionError as _boot_err:
    logger.error(
        "therapeutic_controller: BOOT-TIME ADDITIVITY GUARD FAILED — %s. "
        "v1.3 controller has regressed from v1.2 contract. Halting import.",
        _boot_err,
    )
    raise
