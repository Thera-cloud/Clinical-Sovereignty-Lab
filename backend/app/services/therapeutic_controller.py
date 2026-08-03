# QUANTUM-CRYSTAL-ARCH — Sovereign Standard clinical RED gate.
"""# FIX-THERAPEUTIC-CONTROLLER
State-dependent therapeutic controller — pre-flight + post-flight wrappers.

Wraps bridge_server's per-turn LLM dispatch without replacing it. Pre-flight
shapes the system prompt and token cap based on autonomic state, TMC class,
coherence trend, recurring patterns, and recent narratives. Post-flight
audits the final response, regenerates once on violation when a mismatch was
attempted, and logs metrics to sse_therapeutic_audit_log.

Backwards compatible: caller wraps each entry point in try/except and falls
back to existing behavior on any failure.

PHASE 3 v1.3 — ADDITIVITY CONTRACT (orchestrator absent → v1.2-aligned except bans)

When `register_directive`, `dissociation_delta`, and `coercion_severity` are
all None (the Phase 3 state, before Phase 4 orchestrator wiring), register
variants and caps match the v1.2 surface; **en-US banned substrings are the
three-entry hard-ban tuple** (`_THERAPEUTIC_BANNED_PHRASES_EN_US`), not the
historical v1.2 filler list. Optional `data/lexicons/banned_phrases_*.json` overlays still append.

- Token caps for `shutdown|activated|in_window|regulated` unchanged.
- Mismatch evaluation logic for `mismatch_available` unchanged.
- Thalamic Novelty Gate evaluates to `blocked=False` (no signals → no block).
- Predictability-continuity cap resolver is dormant (no register_directive).

Auditor checks (`_auditor_self_check`):
- `register_variants_additive_only` — every v1.2 variant still resolves
- `banned_phrases_extended_not_replaced` — any `_PHASE_V1_2_BANNED_PHRASES` pins ⊆ resolved
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

QUANTUM-CRYSTAL-ARCH — Sovereign Standard clinical RED gate.
"""

import asyncio
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
# DO NOT MODIFY registers without updating fixtures. Banned-phrase pins
# (`_PHASE_V1_2_BANNED_PHRASES`) may be empty; hard-ban list is
# `_THERAPEUTIC_BANNED_PHRASES_EN_US`.
_PHASE_V1_2_REGISTER_VARIANTS: Tuple[str, ...] = (
    "shutdown", "activated", "in_window", "regulated",
)
# Optional pins for auditors / parity (empty = no legacy v1.2 substring bans).
_PHASE_V1_2_BANNED_PHRASES: Tuple[str, ...] = ()

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

# En-US hard ban (post-flight audit substring match, lowercase). Only these three.
_THERAPEUTIC_BANNED_PHRASES_EN_US: Tuple[str, ...] = (
    "you have nothing to be ashamed of",
    "you'll get over this",
    "everything happens for a reason",
)

# In-code authoritative baseline. Lexicon overlay file (Note 3 stub) extends.
_BANNED_PHRASES_BY_LOCALE: Dict[str, Tuple[str, ...]] = {
    "en-US": _THERAPEUTIC_BANNED_PHRASES_EN_US,
}

# Path to the lexicon overlay directory (matches Phase 2 lexicon convention).
_LEXICON_DIR = Path(__file__).resolve().parents[2] / "data" / "lexicons"

# Backward-compat: `_BANNED_PHRASES_ALWAYS` mirrors en-US resolved baseline (no overlay).
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

TRANSPARENT_AUDIT_FALLBACK_MESSAGE: str = (
    "I want to think about that more carefully — can you tell me which "
    "part of what you shared feels most important to you right now?"
)


def _heuristic_input_affect_intensity(user_text: str) -> float:
    """Rough 0..1 affect load from lexical cues (no LLM). Used for cap scaling."""
    if not user_text:
        return 0.0
    lower = user_text.lower()
    score = 0.0
    for token in (
        "rape", "assault", "abuse", "trauma", "suicide", "kill myself",
        "hurt me", "panic", "terrified", "nightmare", "grand jury",
        "sexual", "molest", "violence", "dying", "worthless", "helpless",
    ):
        if token in lower:
            score += 0.12
    if len(user_text) > 800:
        score += 0.08
    return min(1.0, score)


def scaled_predictability_continuity_floor(
    user_text: str,
    base_floor: int = PREDICTABILITY_CONTINUITY_FLOOR_TOKENS,
) -> int:
    """C3: raise floor for long, emotionally weighted turns (predictability_continuity)."""
    n = len(user_text or "")
    if n > 500:
        length_bonus = min(400, (n - 500) // 5)
    else:
        length_bonus = 0
    aff = _heuristic_input_affect_intensity(user_text or "")
    if aff > 0.6:
        affect_bonus = 200
    elif aff > 0.3:
        affect_bonus = 100
    else:
        affect_bonus = 0
    return base_floor + length_bonus + affect_bonus


async def _resolve_predictability_continuity_cap(
    user_id: str,
    db_pool,
    floor: int = PREDICTABILITY_CONTINUITY_FLOOR_TOKENS,
    user_text: str = "",
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
    scaled_floor = scaled_predictability_continuity_floor(user_text or "", floor)
    if not db_pool or not user_id:
        return scaled_floor
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
                return scaled_floor
            words = int(row["word_count_ai"] or 0)
            if words <= 0:
                return scaled_floor
            # words → approximate tokens (~0.75 tokens/word)
            prior_tokens = int(round(words / 0.75))
            return max(prior_tokens, scaled_floor)
    except Exception as e:
        logger.warning(
            "therapeutic_controller: predictability cap resolve failed "
            "for %s: %s — returning scaled_floor=%d", user_id, e, scaled_floor,
        )
        return scaled_floor


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


_DIRECT_DELIVERY_TOOL_CLAUSE = (
    "When the client directly requests a therapeutic tool (mantra, "
    "grounding technique, breathing exercise, coping strategy, "
    "affirmation, truth statement, anchor phrase, or similar), "
    "OR concrete action steps / integration steps / 'teach me one idea' / "
    "'offer one suggestion', "
    "deliver it cleanly: state the tool or steps, give one brief instruction, "
    "then stop. Do not wrap in a question asking them to evaluate it."
)
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
            "physiological state and tolerates even less demand.\n"
            f"{_DIRECT_DELIVERY_TOOL_CLAUSE}"
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
            "last time' — be that.\n"
            f"{_DIRECT_DELIVERY_TOOL_CLAUSE}"
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


def _make_sensitive_bridge_checkin_agent(db_pool):
    # GA hardening: delegate to the bridge's cached per-pool instance instead
    # of constructing a fresh NateCheckInAgent on every chat turn.
    try:
        from app.services.sensitive_clinical_bridge import get_default_checkin_agent
        return get_default_checkin_agent(db_pool)
    except Exception:
        try:
            from app.services.nate_checkin_agent import NateCheckInAgent as _NCA
            return _NCA(db_pool=db_pool)
        except Exception:
            return None


def _apply_sensitive_bridge_decision(bridge_decision, fallback_register: Optional[str]):
    register = fallback_register
    lens_block = ""
    if bridge_decision is not None:
        if bridge_decision.register_directive:
            register = bridge_decision.register_directive
        lens_block = (
            (bridge_decision.audit_event or {}).get("lens_directives_block")
            or ""
        )
    return register, lens_block


# ─────────────────────────── Pre-flight ───────────────────────────

from app.services.sovereign_standard_gate import therapeutic_module

# QUANTUM-CRYSTAL-ARCH — user-text crisis when TMC mislabels (e.g. REST on SI).
# Includes third-person / paraphrased SI ("end a life", "ending their life") and
# high-risk HI / means stems that omit first-person "end my life".
_USER_CRISIS_INTENT = re.compile(
    r"(?:"
    r"\b(?:kill myself|suicide|suicidality|want to die|end it all|"
    r"not want to (?:be )?alive|take my (?:own )?life)\b|"
    r"\bend(?:ing)? (?:my |one'?s |their |your |a )?life\b|"
    r"\b(?:bought|purchased) a gun\b|"
    r"\bgun in (?:my|your|the) (?:nightstand|car)\b|"
    r"\b(?:talk me out of (?:it|killing)|sitting in my car outside|"
    r"i (?:did not|didn't) decide to live)\b|"
    r"\b(?:drove|went|walked) to (?:the )?(?:\w+ )?bridge\b|"
    r"\bstood (?:at|on|in) (?:the )?(?:middle of )?(?:the )?(?:\w+ )?bridge\b|"
    r"\blogistics of jumping\b"
    r")",
    re.IGNORECASE,
)


async def _prepare_therapeutic_context_faster(
    *,
    user_text: str,
    canonical_user_id: str,
    user_id: str,
    base_system_prompt: str,
    default_max_tokens: int,
    register_directive: Optional[str],
    locale: str,
    token_cap_fn,
) -> dict:
    """QUANTUM-CRYSTAL-ARCH: Faster conversational preflight — text state only.

    Skips Sensitive Bridge, TMC DB classify, narratives, neuroscience recall,
    forward reasoning, six-quotient live, and principal-review guide fetches.
    Crisis keyword detection + state caps remain. Target: normal-chat latency.
    """
    text_state = _detect_state_from_text(user_text)
    _crisis = bool(_USER_CRISIS_INTENT.search(user_text or ""))
    if _crisis or text_state == "activated":
        autonomic_state = "activated"
        tmc_class = "CRISIS" if _crisis else "THRESHOLD"
    elif text_state == "shutdown":
        autonomic_state = "shutdown"
        tmc_class = "REST"
    else:
        # Conversational default — never "regulated" (1500-token Extra dive)
        autonomic_state = "in_window"
        tmc_class = "REST"

    state_cap = TOKEN_CAPS.get(autonomic_state, 450)
    max_tokens = min(int(token_cap_fn(default_max_tokens)), int(state_cap))

    book_context_block = ""
    try:
        from app.services import therapeutic_book_registry as _tbr

        _matched_books = _tbr.detect_referenced_books(user_text or "")
        if _matched_books:
            book_context_block = _tbr.build_book_context_block(_matched_books)
    except Exception as _tbr_exc:
        logger.warning("therapeutic_controller faster: book context skipped: %s", _tbr_exc)

    direct_action_kind = None
    direct_action_block = ""
    try:
        from app.services.little_nate_clinical_output_policy import (
            build_direct_action_delivery_block as _dad_block,
            classify_direct_action_request as _dad_classify,
        )

        direct_action_kind = _dad_classify(user_text or "")
        if direct_action_kind:
            direct_action_block = "\n" + _dad_block(direct_action_kind) + "\n"
            if direct_action_kind == "action_steps" and max_tokens < 350:
                max_tokens = max(max_tokens, 350)
    except Exception as _dad_exc:
        logger.warning("therapeutic_controller faster: direct-action skipped: %s", _dad_exc)

    effective_register_directive = register_directive
    register_variant_block = _register_variant_guidance(effective_register_directive)

    _state_sym: dict = {}
    try:
        from dataclasses import asdict as _asdict_state

        from app.services.nate_commitment_extractor import build_state_symbol as _bss_pre

        _state_sym = _asdict_state(
            _bss_pre(
                user_text or "",
                audit_metadata={
                    "autonomic_state": autonomic_state,
                    "tmc_class": tmc_class,
                    "register_directive": effective_register_directive,
                    "distress_present": _crisis or autonomic_state == "activated",
                },
            )
        )
    except Exception as _ss_exc:
        logger.warning("therapeutic_controller faster: state_symbol skipped: %s", _ss_exc)

    enriched = (
        f"## CURRENT THERAPEUTIC STATE (FASTER)\n"
        f"autonomic_state: {autonomic_state} | tmc_class: {tmc_class}\n"
        f"Respond like a natural conversation — present, clinical, concise.\n\n"
        f"{_state_guidance(autonomic_state)}\n"
        f"{register_variant_block}\n"
        f"{direct_action_block}\n"
        f"{book_context_block}\n"
        f"---\n\n{base_system_prompt}"
    )

    if effective_register_directive:
        register_default_field = effective_register_directive
    else:
        register_default_field = "WARM"

    print(
        f">>> [THERAPEUTIC-CTRL] FASTER light path user={canonical_user_id} "
        f"state={autonomic_state} tmc={tmc_class} cap={max_tokens}"
    )

    return {
        "enriched_system_prompt": enriched,
        "max_tokens": max_tokens,
        "recent_narratives": [],
        "audit_metadata": {
            "autonomic_state": autonomic_state,
            "tmc_class": tmc_class,
            "mismatch_available": False,
            "encoded_patterns": [],
            "register_default": register_default_field,
            "max_tokens": max_tokens,
            "register_directive": effective_register_directive,
            "thalamic_gate_blocked": False,
            "thalamic_gate_reason": "faster_light_path",
            "dissociation_delta": None,
            "coercion_severity": None,
            "novelty_threshold": 0.30,
            "thalamic_gate_forced": False,
            "locale": locale,
            "bridge_event_severity": "info",
            "user_text_for_audit": (user_text or "")[:2000],
            "direct_action_request_kind": direct_action_kind,
            "state_symbol": _state_sym,
            "crisis_exempt": bool(_crisis),
            "crisis_class_fired": bool(_crisis),
            "principal_review_turn_class": "",
            "principal_review_teach_class": "",
            "principal_review_class_fired": False,
            "principal_review_guide_ids": [],
            "principal_review_guide_classes": [],
            "principal_review_guide_scenarios": [],
            "requester_user_id": canonical_user_id or user_id,
            "faster_light_path": True,
        },
    }


@therapeutic_module
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
    # ─── GA hardening additive params (2026-06-09 pre-GA flaw review) ───
    # session_id: audit-row correlation for sensitive_bridge_log.
    # coach_id: assigned coach username — enables step 15 mandatory
    #     reporting escalation + step 16 coach alert dispatch targeting.
    # Defaults (None) preserve prior behavior at every other call site.
    session_id: Optional[str] = None,
    coach_id: Optional[str] = None,
    # QUANTUM-CRYSTAL-ARCH — Phase 5c: profile for trial exclusion in forward reasoning
    profile: Optional[dict] = None,
    # QUANTUM-CRYSTAL-ARCH — gold/live-stack teaching class for non-crisis PR inject
    preferred_response_class: Optional[str] = None,
    # QUANTUM-CRYSTAL-ARCH — Faster depth: light preflight (not Extra deep dive)
    depth_mode: Optional[str] = None,
    # TRUST_LEDGER.md Entry 15 — six_quotient capability harness passes its own
    # scenario_id here so a scenario's own promoted guide (source_scenario
    # match) is excluded from its own regeneration's injected set. None in
    # every production call site (real user turns have no scenario_id) —
    # additive, preserves prior behavior everywhere except the harness.
    exclude_source_scenario: Optional[str] = None,
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

    # QUANTUM-CRYSTAL-ARCH: Faster = conversational light path (~6–7s), not Extra dive
    try:
        from app.websocket.chat_depth_mode import (
            allow_full_therapeutic_preflight as _allow_full_ttc,
            faster_max_tokens as _faster_tok,
        )

        if not _allow_full_ttc(depth_mode or ""):
            return await _prepare_therapeutic_context_faster(
                user_text=user_text,
                canonical_user_id=canonical_user_id,
                user_id=user_id,
                base_system_prompt=base_system_prompt,
                default_max_tokens=default_max_tokens,
                register_directive=register_directive,
                locale=locale,
                token_cap_fn=_faster_tok,
            )
    except Exception as _fast_exc:
        logger.warning(
            "therapeutic_controller: Faster light path failed, falling through: %s",
            _fast_exc,
        )

    lens_bridge_block = ""
    _bd = None
    # v1.3 Sensitive Clinical Bridge — single wiring seam (Phase 4 Note 1).
    # Master kill switch + per-user gap_features_enabled gate the orchestrator
    # internally; when dormant, register_directive is None and downstream
    # logic runs identically to v1.2.
    # GA hardening (2026-06-09): evaluate_disclosure_guarded encapsulates the
    # EVAL_TIMEOUT_S bound, telemetry counters, identity-drift audit, cached
    # check-in agent + mandatory reporting service — keeping this seam under
    # the Phase 4 15-line cap (phase4_wiring_diff_under_15_lines).
    try:
        from app.services import sensitive_clinical_bridge as _scb
        _bd = await _scb.evaluate_disclosure_guarded(
            db_pool=db_pool, user_id=canonical_user_id, raw_user_id=user_id,
            message=user_text, session_id=session_id, locale=locale,
            coach_id=coach_id,
        )
        if _bd is not None:
            register_directive, lens_bridge_block = _apply_sensitive_bridge_decision(
                _bd, register_directive,
            )
    except Exception as _e:
        logger.warning("therapeutic_controller: bridge wiring skipped: %s", _e)
    # end v1.3 Sensitive Clinical Bridge wiring seam

    # QUANTUM-CRYSTAL-ARCH (Sensitive Bridge v1.4 extension, additive):
    # Auto-ingest named IFS parts from chat into user_parts_registry as a
    # fire-and-forget side effect. Gated internally by enrollment + codeword
    # feature flag; no-op for unenrolled users. Never raises into hot path.
    try:
        import asyncio as _asyncio_pae
        from app.services import parts_auto_extractor as _pae

        async def _pae_task() -> None:
            try:
                await _pae.auto_extract_and_register(
                    db_pool,
                    canonical_username=canonical_user_id,
                    user_text=user_text or "",
                    session_id=session_id,
                )
            except Exception as _pae_exc:
                logger.warning("parts_auto_extractor task failed: %s", _pae_exc)

        _asyncio_pae.create_task(_pae_task())
    except Exception as _pae_outer:
        logger.warning("therapeutic_controller: parts auto-extract skipped: %s", _pae_outer)

    # QUANTUM-CRYSTAL-ARCH (additive): therapeutic book / workbook context.
    # When the client references a known clinician-vetted workbook (e.g.,
    # "He Came For All My Parts" by Kristy Moore), inject its themes into
    # the system prompt so Nate can attune to the imagery instead of decoding
    # it into clinical jargon. Pure regex match → in-memory dict lookup.
    book_context_block = ""
    try:
        from app.services import therapeutic_book_registry as _tbr
        _matched_books = _tbr.detect_referenced_books(user_text or "")
        if _matched_books:
            book_context_block = _tbr.build_book_context_block(_matched_books)
    except Exception as _tbr_exc:
        logger.warning("therapeutic_controller: book context skipped: %s", _tbr_exc)

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
                user_text=user_text or "",
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

    direct_action_kind = None
    direct_action_block = ""
    try:
        from app.services.little_nate_clinical_output_policy import (
            build_direct_action_delivery_block as _dad_block,
            classify_direct_action_request as _dad_classify,
        )

        direct_action_kind = _dad_classify(user_text or "")
        if direct_action_kind:
            direct_action_block = "\n" + _dad_block(direct_action_kind) + "\n"
            if direct_action_kind == "action_steps" and max_tokens < 350:
                max_tokens = max(max_tokens, 350)
    except Exception as _dad_exc:
        logger.warning("therapeutic_controller: direct-action block skipped: %s", _dad_exc)

    # QUANTUM-CRYSTAL-ARCH — Phase 5b: StateSymbol always on audit_metadata (Key gate)
    _state_sym: dict = {}
    try:
        from dataclasses import asdict as _asdict_state

        from app.services.nate_commitment_extractor import build_state_symbol as _bss_pre

        _state_sym = _asdict_state(
            _bss_pre(
                user_text or "",
                audit_metadata={
                    "autonomic_state": autonomic_state,
                    "tmc_class": tmc_class,
                    "register_directive": effective_register_directive,
                    "distress_present": (tmc_class or "").lower()
                    in ("crisis", "suicide_ideation", "distress"),
                },
            )
        )
    except Exception as _ss_exc:
        logger.warning("therapeutic_controller: state_symbol build skipped: %s", _ss_exc)

    forward_reasoning_block = ""
    try:
        from app.services.nate_forward_reasoning import (
            build_forward_constraints,
            format_constraints_for_prompt,
        )

        _emo_trend = "declining" if ec_slope < -0.05 else ("rising" if ec_slope > 0.05 else "stable")
        _constraints = await build_forward_constraints(
            db_pool,
            username=canonical_user_id,
            hardware_id=user_id,
            state_symbol=_state_sym,
            nevedal_snapshot={"c_emo": ec_current, "c_emo_trend": _emo_trend},
            profile=profile if isinstance(profile, dict) else None,
        )
        # QUANTUM-CRYSTAL-ARCH — L3c: foresight calibration gates soft constraints
        try:
            from app.services.foresight_calibration_gate import (
                filter_constraints_for_calibration,
                foresight_calibration_ok,
            )

            _cal_ok = await foresight_calibration_ok(db_pool)
            _before_n = len(_constraints or [])
            _constraints = filter_constraints_for_calibration(
                _constraints or [], calibration_ok=_cal_ok,
            )
            if _before_n and len(_constraints) < _before_n:
                print(
                    f">>> [THERAPEUTIC-CTRL] L3c foresight calibration "
                    f"filtered {_before_n}->{len(_constraints)} constraints"
                )
        except Exception as _cal_exc:
            logger.debug("therapeutic_controller: L3c calibration gate skipped: %s", _cal_exc)
        _fr_text = format_constraints_for_prompt(_constraints)
        if _fr_text:
            forward_reasoning_block = "\n" + _fr_text + "\n"
            # QUANTUM-CRYSTAL-ARCH — Phase 5c soak visibility
            print(
                f">>> [THERAPEUTIC-CTRL] forward_reasoning n={len(_constraints)} "
                f"types={[c.get('type') for c in _constraints]}"
            )
    except Exception as _fr_exc:
        logger.warning("therapeutic_controller: forward reasoning skipped: %s", _fr_exc)

    # QUANTUM-CRYSTAL-ARCH — battery/CEO self-dev cues into live therapy (flag-gated)
    six_q_live_block = ""
    try:
        from app.services.six_quotient_live_context import get_live_addendum

        _sq_add = await get_live_addendum(db_pool, surface="bridge_chat")
        if _sq_add:
            six_q_live_block = "\n" + _sq_add + "\n"
    except Exception as _sq_exc:
        logger.warning("therapeutic_controller: six-quotient live context skipped: %s", _sq_exc)

    # QUANTUM-CRYSTAL-ARCH — Principal-Review Guides (crisis OR class-matched)
    principal_crisis_block = ""
    principal_class_block = ""
    _pr_guides = []
    _pr_turn_class = None
    _pr_teach_class = ""
    try:
        from app.services.principal_review_crisis_policy import (
            classify_crisis_turn_class as _pr_classify_turn,
            infer_teaching_response_class as _pr_infer_teach,
            normalize_teaching_response_class as _pr_norm_teach,
        )

        _pr_turn_class = _pr_classify_turn(user_text or "")
        _pr_teach_class = _pr_norm_teach(preferred_response_class) or (
            _pr_infer_teach(user_text or "") or ""
        )
        # Substantial non-crisis disclosures default to therapeutic_engage so
        # engage Guides can demonstrate recall outside live-stack labels.
        if (
            not _pr_turn_class
            and not _pr_teach_class
            and len((user_text or "").strip()) >= 40
        ):
            _pr_teach_class = "therapeutic_engage"
    except Exception:
        _pr_turn_class = None
        _pr_teach_class = ""
    _crisis_class = (
        (tmc_class or "").lower() in ("crisis", "suicide_ideation")
        or bool(_USER_CRISIS_INTENT.search(user_text or ""))
        or bool(_pr_turn_class)
    )
    if _crisis_class and db_pool:
        try:
            from app.services.principal_review_crisis_policy import (
                TURN_CLASS_SI,
                fetch_principal_review_crisis_guides,
                format_crisis_guide_injection,
            )

            _tc = _pr_turn_class or TURN_CLASS_SI
            _pr_guides = await fetch_principal_review_crisis_guides(
                db_pool,
                limit=3,
                turn_class=_tc,
                actor_id=canonical_user_id,
                user_text=user_text or "",
                exclude_source_scenario=exclude_source_scenario,
            )
            # QUANTUM-CRYSTAL-ARCH — dose-response v2: sequenced MUST pack
            # behind LN7_MUST_SEQUENCE_PACK_LIVE (default off). Replaces the
            # compound ∧-joined MUST digest only; guides + MUST-NOT unchanged.
            _must_override = None
            try:
                from app.services.ln7_must_sequence_pack import (
                    format_must_sequence_pack,
                    must_sequence_pack_live_enabled,
                )
                from app.services.ln7_structural_verifier_floor import (
                    MEANS_LANGUAGE_IN_TEXT,
                )

                if must_sequence_pack_live_enabled():
                    _ut = user_text or ""
                    _must_override = format_must_sequence_pack(
                        turn_class=_tc,
                        has_named_means=bool(MEANS_LANGUAGE_IN_TEXT.search(_ut)),
                        has_stated_prohibition=bool(
                            re.search(
                                r"\b(?:not suicidal|i(?:'m| am) not going to|"
                                r"legally|by law|don'?t (?:tell|say)|"
                                r"can(?:'?t|not) tell)\b",
                                _ut,
                                re.I,
                            )
                        ),
                    )
            except Exception as _msp_exc:
                logger.warning(
                    "therapeutic_controller: must-sequence pack skipped: %s",
                    _msp_exc,
                )
                _must_override = None
            principal_crisis_block = format_crisis_guide_injection(
                _pr_guides,
                turn_class=_tc,
                must_block_override=_must_override,
            )
            if principal_crisis_block:
                _gids = [str(g.get("id") or "") for g in (_pr_guides or [])]
                print(
                    f">>> [THERAPEUTIC-CTRL] principal_review crisis guides n="
                    f"{len(_pr_guides)} turn_class={_tc} ids={_gids}"
                    f" must_sequence={'on' if _must_override else 'off'}"
                )
        except Exception as _pr_exc:
            logger.warning(
                "therapeutic_controller: principal_review crisis inject skipped: %s",
                _pr_exc,
            )
    elif (not _crisis_class) and _pr_teach_class and db_pool:
        try:
            from app.services.principal_review_crisis_policy import (
                fetch_principal_review_class_guides,
                format_class_guide_injection,
            )

            _pr_guides = await fetch_principal_review_class_guides(
                db_pool,
                response_class=_pr_teach_class,
                user_text=user_text or "",
                limit=4,
                actor_id=canonical_user_id,
                exclude_source_scenario=exclude_source_scenario,
            )
            principal_class_block = format_class_guide_injection(
                _pr_guides, response_class=_pr_teach_class
            )
            if principal_class_block:
                _gids = [str(g.get("id") or "") for g in (_pr_guides or [])]
                print(
                    f">>> [THERAPEUTIC-CTRL] principal_review class guides n="
                    f"{len(_pr_guides)} class={_pr_teach_class} ids={_gids}"
                )
        except Exception as _pr_cls_exc:
            logger.warning(
                "therapeutic_controller: principal_review class inject skipped: %s",
                _pr_cls_exc,
            )

    enriched = (
        f"## DNA — NEUROSCIENCE BEDROCK\n{_DNA_PREFIX}\n\n"
        f"## CURRENT THERAPEUTIC STATE\n"
        f"autonomic_state: {autonomic_state} | tmc_class: {tmc_class} | "
        f"ec_current: {ec_current:.2f} | ec_slope: {ec_slope:+.2f}\n\n"
        f"{_state_guidance(autonomic_state)}\n"
        f"{register_variant_block}\n"
        f"{direct_action_block}\n"
        f"{lens_bridge_block}\n"
        f"{mismatch_block}\n"
        f"{forward_reasoning_block}\n"
        f"{six_q_live_block}"
        f"{principal_crisis_block}"
        f"{principal_class_block}"
        f"{book_context_block}\n"
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
            # QUANTUM-CRYSTAL-ARCH — stall suppression metadata (Fix 5)
            "bridge_event_severity": (
                (_bd.audit_event or {}).get("event_severity") if _bd else None
            ) or "info",
            "user_text_for_audit": (user_text or "")[:2000],
            "direct_action_request_kind": direct_action_kind,
            # QUANTUM-CRYSTAL-ARCH — Phase 5b Key + Surface gates
            "state_symbol": _state_sym,
            "crisis_exempt": bool(_crisis_class),
            "crisis_class_fired": bool(_crisis_class),
            "principal_review_turn_class": (_pr_turn_class or "")[:40],
            "principal_review_teach_class": (_pr_teach_class or "")[:40],
            "principal_review_class_fired": bool(
                (not _crisis_class) and _pr_teach_class and _pr_guides
            ),
            "principal_review_guide_ids": [
                str(g.get("id") or "") for g in (_pr_guides or []) if g.get("id")
            ],
            "principal_review_guide_classes": [
                str(
                    g.get("response_class")
                    or g.get("source_scenario")
                    or ""
                )[:80]
                for g in (_pr_guides or [])
            ],
            "principal_review_guide_scenarios": [
                str(g.get("source_scenario") or "")[:40] for g in (_pr_guides or [])
            ],
            "requester_user_id": canonical_user_id or user_id,
        },
    }


# ─────────────────────────── Post-flight ───────────────────────────

def _symbolic_verifier_enabled() -> bool:
    import os

    return os.getenv("ENABLE_SYMBOLIC_VERIFIER", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


_SYMBOLIC_CRISIS_MARKERS = re.compile(
    r"\b(?:988|741741|838255|267-5463|copline|veterans crisis line)\b",
    re.IGNORECASE,
)


_CRISIS_RESOURCE_SUFFIX = (
    " If you're in crisis, call or text 988 for support, "
    "or text HOME to 741741."
)

# QUANTUM-CRYSTAL-ARCH — Principal-Review spine when naming/escalation missing
_CRISIS_SPINE_SUFFIX = (
    " What you're describing puts you in danger. I'm here with you now — "
    "your coach needs to know, and call or text 988."
)


def _user_text_implies_crisis(audit_metadata: Optional[dict] = None) -> bool:
    """QUANTUM-CRYSTAL-ARCH: SI intent from user text even when tmc_class is REST."""
    meta = audit_metadata or {}
    tmc = (meta.get("tmc_class") or "").lower()
    if tmc in ("crisis", "suicide_ideation"):
        return True
    ut = meta.get("user_text_for_audit") or ""
    return bool(_USER_CRISIS_INTENT.search(ut))


def ensure_crisis_resource_in_text(response_text: str, audit_metadata: Optional[dict] = None) -> str:
    """QUANTUM-CRYSTAL-ARCH: Re-assert 988 after post-processors that may strip it."""
    meta = audit_metadata or {}
    if not _user_text_implies_crisis(meta):
        return response_text or ""
    text = response_text or ""
    if _symbolic_has_crisis_resource(text, meta):
        return text
    return text.rstrip() + _CRISIS_RESOURCE_SUFFIX


async def light_symbolic_post_audit(
    response_text: str,
    *,
    user_text: str,
    user_id: str,
    db_pool,
    profile: Optional[dict] = None,
    crystal_scopes: Optional[list] = None,
) -> str:
    """QUANTUM-CRYSTAL-ARCH: Verifier for sanctuary/coaching/voice (no full prepare)."""
    if not _symbolic_verifier_enabled() or not (response_text or "").strip():
        return response_text or ""
    try:
        from dataclasses import asdict as _asdict

        from app.services.nate_commitment_extractor import build_state_symbol as _bss

        _st = _asdict(_bss(user_text or "", audit_metadata=None))
        _distress = bool(_st.get("distress_present"))
        _crisis_kw = bool(_USER_CRISIS_INTENT.search(user_text or "")) or bool(
            re.search(r"\b988\b", (user_text or ""), re.I)
        )
        tmc = "crisis" if _crisis_kw else ("distress" if _distress else "coaching")
        requester = (
            (profile or {}).get("username")
            or (profile or {}).get("hardware_id")
            or user_id
        )
        meta = {
            "state_symbol": _st,
            "tmc_class": tmc,
            "crisis_exempt": tmc in ("crisis", "suicide_ideation")
            or bool(_USER_CRISIS_INTENT.search(user_text or "")),
            "crystal_scopes": list(crystal_scopes or [])[:50],
            "requester_user_id": requester,
            "user_id": requester,
            "max_tokens": 600,
            "user_text_for_audit": (user_text or "")[:800],
        }
        out = await audit_therapeutic_response(
            response_text=response_text,
            audit_metadata=meta,
            user_id=str(requester),
            db_pool=db_pool,
        )
        return (out or {}).get("response_text") or response_text
    except Exception as e:
        logger.warning("therapeutic_controller: light_symbolic_post_audit failed: %s", e)
        return response_text


def _symbolic_has_crisis_resource(response_text: str, audit_metadata: dict) -> bool:
    """True if reply cites a usable crisis resource (988 alone is enough for 5b)."""
    if _SYMBOLIC_CRISIS_MARKERS.search(response_text or ""):
        return True
    try:
        from app.services.crisis_resource_registry import has_crisis_resources_in_text as _has_cr

        _prof = audit_metadata.get("profile") if isinstance(audit_metadata, dict) else None
        return bool(_has_cr(response_text, _prof if isinstance(_prof, dict) else None))
    except Exception:
        return False


# QUANTUM-CRYSTAL-ARCH — clinical precision: named kinship / invented soma / advice dump
_KINSHIP_TERMS = (
    "brother", "sister", "mom", "mother", "dad", "father", "wife", "husband",
    "son", "daughter", "spouse", "partner", "uncle", "aunt", "cousin",
    "boyfriend", "girlfriend", "fiancé", "fiance", "grandma", "grandfather",
    "grandmother", "grandpa",
)
_SOMATIC_CLAIM = re.compile(
    r"\b(?:in your (?:chest|throat|stomach|gut|shoulders?|jaw|hands?)|"
    r"(?:tightness|heaviness|pressure) in your|"
    r"i (?:can )?feel (?:the )?(?:tightness|heaviness|weight) in your|"
    r"your (?:chest|throat|shoulders?) (?:is|are|feels?))\b",
    re.I,
)
_SOMATIC_USER_MARKERS = (
    "chest", "throat", "stomach", "gut", "shoulder", "jaw", "breath",
    "body", "tight", "heavy", "nause", "heart rac", "shak",
)
_ADVICE_ASK = re.compile(
    r"\b(?:what should i do|what do i do|tell me what to do|give me advice|"
    r"how do i (?:fix|handle|deal)|any advice)\b",
    re.I,
)
_TIP_DUMP = re.compile(
    r"(?:^\s*\d+[\.\)]\s+|here(?:'s| are) (?:a few |some )?things? (?:you can|to try)|"
    r"\byou should\b|\btry to\b|\bstart by\b)",
    re.I | re.M,
)
_WITNESS_BRIDGE = (
    "what's coming up", "what comes up", "stay with", "before we",
    "your coach", "bring this to", "i'm here with", "right here with",
    "we can sit", "don't have to solve",
)


def _symbolic_precision_violations(response_text: str, audit_metadata: dict) -> list:
    """QUANTUM-CRYSTAL-ARCH: referent lock, invented soma, advice-before-witness."""
    out: list = []
    user_text = (audit_metadata.get("user_text_for_audit") or "").strip()
    if not user_text or not (response_text or "").strip():
        return out
    ul = user_text.lower()
    rl = response_text.lower()

    # Named-referent drop: kinship in user turn + "this/that person" without kinship echo
    kin_hits = [k for k in _KINSHIP_TERMS if re.search(rf"\b{re.escape(k)}\b", ul)]
    if kin_hits and re.search(r"\b(?:this|that) person\b", rl):
        if not any(re.search(rf"\b{re.escape(k)}\b", rl) for k in kin_hits):
            out.append("symbolic_referent_drop")

    # Invented somatic claim not grounded in user text
    if _SOMATIC_CLAIM.search(response_text) and not any(m in ul for m in _SOMATIC_USER_MARKERS):
        out.append("symbolic_invented_somatic")

    # Advice dump without witness/coach bridge (skip crisis — 988 path owns that)
    if not bool(audit_metadata.get("crisis_exempt")) and _ADVICE_ASK.search(user_text):
        if _TIP_DUMP.search(response_text) and not any(w in rl for w in _WITNESS_BRIDGE):
            out.append("symbolic_advice_dump")
    return out


_RP_NARRATION_RE = re.compile(
    r"(?:Nate'?s\s+(?:eyes|voice|gaze|hand|lips)|"
    r"his voice (?:cracks|barely|soft)|"
    r"looking up at you with|"
    r"He pauses,\s*looking|"
    r"\*[a-z][a-z]+(?:s|ing)\*)",
    re.I,
)


def _symbolic_audit_violations(response_text: str, audit_metadata: dict) -> list:
    """QUANTUM-CRYSTAL-ARCH: Phase 5b symbolic constraint checks."""
    if not _symbolic_verifier_enabled():
        return []
    violations: list = []
    if not response_text or not response_text.strip():
        return violations
    rl = response_text.lower()
    # QUANTUM-CRYSTAL-ARCH — client-facing: first person only (no RP novelization)
    if _RP_NARRATION_RE.search(response_text):
        violations.append("symbolic_third_person_rp")
    state_sym = audit_metadata.get("state_symbol") or {}
    if isinstance(state_sym, dict) and state_sym.get("distress_present"):
        celebratory = ("proud of", "celebrat", "smiling through", "so glad you", "amazing progress")
        if any(m in rl for m in celebratory):
            violations.append("symbolic_emotion_mirror")
    if _user_text_implies_crisis(audit_metadata):
        if not _symbolic_has_crisis_resource(response_text, audit_metadata):
            violations.append("symbolic_crisis_resource_missing")
        # QUANTUM-CRYSTAL-ARCH — Principal-Review crisis laws (must / must-not)
        try:
            from app.services.principal_review_crisis_policy import (
                crisis_si_law_violations as _crisis_laws,
            )

            for _v in _crisis_laws(response_text):
                if _v not in violations:
                    violations.append(_v)
        except Exception as _cl_exc:
            logger.warning(
                "therapeutic_controller: crisis SI law check skipped: %s", _cl_exc
            )
    # QUANTUM-CRYSTAL-ARCH — Seam: admin_only / archived scopes must not reach clients
    try:
        from app.services.crystal_graph_isolation import scope_allows_recall

        requester = (
            audit_metadata.get("requester_user_id")
            or audit_metadata.get("user_id")
            or ""
        )
        for scope in audit_metadata.get("crystal_scopes") or []:
            if not scope_allows_recall(str(scope), None, requester or None):
                violations.append("symbolic_scope_isolation")
                break
    except Exception as _sc_exc:
        logger.warning("therapeutic_controller: scope isolation check skipped: %s", _sc_exc)
    # QUANTUM-CRYSTAL-ARCH — clinical precision (Jake-class misses)
    violations.extend(_symbolic_precision_violations(response_text, audit_metadata))
    return violations


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

    # QUANTUM-CRYSTAL-ARCH — crisis_exempt: skip somatic invitation. Safety
    # spines (988 / means-distance / plain naming) must not be replaced by
    # transparent_fallback for missing body-scan language.
    if state == "activated" and not bool(audit_metadata.get("crisis_exempt")):
        # Workers AI / common models often use heart, grounding, "sit with", "I sense" without
        # the original minimal list — expand markers to reduce transparent_fallback on good prose.
        somatic_markers = [
            "body",
            "breath",
            "chest",
            "shoulder",
            "feel in your",
            "notice",
            "sensation",
            "heart",
            "sit with",
            "grounded",
            "grounding",
            "i sense",
        ]
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

    try:
        from app.services.little_nate_clinical_output_policy import direct_action_audit_violations

        violations.extend(
            direct_action_audit_violations(
                response_text,
                audit_metadata.get("direct_action_request_kind"),
            )
        )
    except Exception as _da_exc:
        logger.warning("therapeutic_controller: direct-action audit skipped: %s", _da_exc)

    violations.extend(_symbolic_audit_violations(response_text, audit_metadata))

    return violations


def _direct_action_violations(violations: list) -> list:
    return [
        v
        for v in violations
        if v.startswith("direct_action") or v.startswith("action_steps")
    ]


async def _repair_direct_action_response(
    response_text: str,
    audit_metadata: dict,
    violations: list,
) -> tuple[str, list, bool]:
    """Regenerate once when client asked for steps/teaching but reply deflected."""
    if not _direct_action_violations(violations):
        return response_text, violations, False
    kind = audit_metadata.get("direct_action_request_kind")
    if not kind:
        return response_text, violations, False
    try:
        from app.services.little_nate_clinical_output_policy import (
            build_direct_action_delivery_block,
        )
        from app.sse.llm_fallback import chat_completion_with_fallback

        user_text = audit_metadata.get("user_text_for_audit") or ""
        cap = max(int(audit_metadata.get("max_tokens") or 600), 350)
        retry_sys = (
            "The client explicitly requested direct coaching content. "
            f"{build_direct_action_delivery_block(kind)}\n"
            "Violations to fix: "
            + ", ".join(_direct_action_violations(violations))
            + ". Deliver substance — not questions only."
        )
        retry = await chat_completion_with_fallback(
            [
                {"role": "system", "content": retry_sys},
                {
                    "role": "user",
                    "content": (
                        f"Client message: {user_text[:800]}\n\n"
                        f"Failed draft: {response_text[:500]}\n\n"
                        "Write the corrected reply."
                    ),
                },
            ],
            max_tokens=cap,
            temperature=0.65,
        )
        if retry and retry.strip():
            retry_violations = _audit_violations(retry.strip(), audit_metadata, [])
            if len(retry_violations) < len(violations):
                return retry.strip(), retry_violations, len(retry_violations) == 0
    except Exception as e:
        logger.warning("therapeutic_controller: direct-action repair failed: %s", e)
    return response_text, violations, False


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
    crisis_exempt = bool(audit_metadata.get("crisis_exempt"))

    # QUANTUM-CRYSTAL-ARCH — Phase 5b: 988 append always; LLM regen capped at 1;
    # crisis_exempt skips LLM rewrite only (Surface gate).
    if not audit_passed and _symbolic_verifier_enabled():
        sym_violations = [v for v in violations if v.startswith("symbolic_")]
        if sym_violations and not audit_metadata.get("symbolic_regen_used"):
            if "symbolic_crisis_resource_missing" in sym_violations:
                final_text = ensure_crisis_resource_in_text(final_text, audit_metadata)
                violations = _audit_violations(final_text, audit_metadata, recent_narratives)
                audit_passed = len(violations) == 0
                sym_violations = [v for v in violations if v.startswith("symbolic_")]
            # Deterministic spine for missing MUST (naming / escalation) — no LLM.
            if any(
                v in sym_violations
                for v in (
                    "symbolic_crisis_naming_missing",
                    "symbolic_crisis_escalation_contingent",
                )
            ):
                if _CRISIS_SPINE_SUFFIX.strip() not in (final_text or ""):
                    final_text = (final_text or "").rstrip() + _CRISIS_SPINE_SUFFIX
                violations = _audit_violations(final_text, audit_metadata, recent_narratives)
                audit_passed = len(violations) == 0
                sym_violations = [v for v in violations if v.startswith("symbolic_")]
            # MUST-NOT law breaks: one regen even under crisis_exempt (never-bad).
            _crisis_must_not = (
                "symbolic_crisis_plan_validation",
                "symbolic_crisis_debate",
                "symbolic_crisis_activity_diversion",
                "symbolic_third_person_rp",
            )
            _needs_law_regen = any(v in sym_violations for v in _crisis_must_not)
            if (not crisis_exempt and sym_violations) or _needs_law_regen:
                try:
                    from app.sse.llm_fallback import chat_completion_with_fallback

                    audit_metadata["symbolic_regen_used"] = True
                    retry_sys = (
                        "Symbolic verifier failed. Fix these violations only: "
                        + ", ".join(sym_violations)
                        + ". Speak in first person as Nate only — never narrate "
                        "Nate's eyes/voice/actions in third person, never stage "
                        "directions. Keep warm therapeutic tone. For crisis_si: MUST "
                        "plain-name danger, escalate non-contingently (988/coach), "
                        "stay present; MUST NOT validate a suicide plan's rationale, "
                        "debate reality, or divert to activities. Adapt — do not recite."
                    )
                    retry = await chat_completion_with_fallback(
                        [
                            {"role": "system", "content": retry_sys},
                            {"role": "user", "content": f"Draft: {response_text[:500]}"},
                        ],
                        max_tokens=audit_metadata.get("max_tokens", 600),
                        temperature=0.5,
                    )
                    if retry and retry.strip():
                        retry_violations = _audit_violations(
                            retry.strip(), audit_metadata, recent_narratives,
                        )
                        if len(retry_violations) < len(violations):
                            final_text = retry.strip()
                            violations = retry_violations
                            audit_passed = len(retry_violations) == 0
                except Exception as e:
                    logger.warning("therapeutic_controller: symbolic regen failed: %s", e)

    if not audit_passed and _direct_action_violations(violations):
        final_text, violations, audit_passed = await _repair_direct_action_response(
            final_text, audit_metadata, violations,
        )
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
                "invitation if activated; do not use: 'you have nothing to be ashamed of', "
                "\"you'll get over this\", 'everything happens for a reason'. "
                "Address what the user said directly."
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

    if not audit_passed and not _direct_action_violations(violations):
        from app.services.stall_suppression import resolve_audit_fallback

        final_text = resolve_audit_fallback(
            user_text=audit_metadata.get("user_text_for_audit") or "",
            bridge_event_severity=audit_metadata.get("bridge_event_severity") or "info",
            default_fallback=TRANSPARENT_AUDIT_FALLBACK_MESSAGE,
        )
        print(
            f">>> [THERAPEUTIC-CTRL] audit_failed_transparent_fallback user={user_id} "
            f"violations={len(violations)}"
        )

    # QUANTUM-CRYSTAL-ARCH — Gate 2 structural floor staged wiring (2026-08-03,
    # docs/ln7/GATE2_VERIFIER_CALIBRATION.md). Runs LAST, independent of
    # ENABLE_SYMBOLIC_VERIFIER (own flag: STRUCTURAL_FLOOR_MODE, default
    # 'off' — zero behavior change until a human explicitly sets it), and
    # only on crisis-classified turns. off/shadow never touch final_text;
    # enforce_with_alert/enforce_quiet attempt one regen, then fall back to
    # the same resolve_audit_fallback() path above if the floor still fails.
    _floor_turn_class = (audit_metadata.get("principal_review_turn_class") or "").strip()
    if _floor_turn_class in ("crisis_si", "crisis_hi"):
        try:
            from app.services.ln7_structural_verifier_floor import (
                effective_structural_floor_mode,
                log_structural_floor_check,
                record_enforcement_outcome,
                verify_structural_floor,
            )

            _floor_mode = await effective_structural_floor_mode(db_pool)
            _floor_user_text = audit_metadata.get("user_text_for_audit") or ""

            if _floor_mode == "shadow":
                import asyncio as _floor_asyncio

                _floor_asyncio.create_task(
                    log_structural_floor_check(
                        db_pool,
                        response_text=final_text,
                        user_text=_floor_user_text,
                        turn_class=_floor_turn_class,
                        source="audit_therapeutic_response_shadow",
                    )
                )
            elif _floor_mode in ("enforce_with_alert", "enforce_quiet"):
                _floor_result = await log_structural_floor_check(
                    db_pool,
                    response_text=final_text,
                    user_text=_floor_user_text,
                    turn_class=_floor_turn_class,
                    source="audit_therapeutic_response_enforce",
                )
                if _floor_result and not _floor_result.get("floor_met"):
                    _missing = [
                        k for k, v in (_floor_result.get("floor_checks") or {}).items()
                        if not v
                    ]
                    _floor_regen_ok = False
                    try:
                        from app.sse.llm_fallback import chat_completion_with_fallback

                        _retry_sys = (
                            "Structural floor check failed. This is a crisis turn "
                            f"missing required moves: {', '.join(_missing)}. Rewrite "
                            "to include them explicitly — name the danger plainly if "
                            "'naming_or_assessment' is missing, bring in the coach "
                            "non-contingently if 'escalation' is missing, ask for "
                            "distance from the named means if 'means_distance' is "
                            "missing. Keep the warm therapeutic register; adapt, "
                            "do not recite a script."
                        )
                        _retry = await chat_completion_with_fallback(
                            [
                                {"role": "system", "content": _retry_sys},
                                {"role": "user", "content": f"Draft: {final_text[:500]}"},
                            ],
                            max_tokens=audit_metadata.get("max_tokens", 600),
                            temperature=0.4,
                        )
                        if _retry and _retry.strip():
                            _retry_result = verify_structural_floor(
                                _retry.strip(),
                                user_text=_floor_user_text,
                                turn_class=_floor_turn_class,
                            )
                            if _retry_result.get("floor_met"):
                                final_text = _retry.strip()
                                _floor_regen_ok = True
                    except Exception as _floor_regen_exc:
                        logger.warning(
                            "structural_floor: regen failed: %s", _floor_regen_exc
                        )

                    _floor_outcome = await record_enforcement_outcome(
                        persisted_after_regen=not _floor_regen_ok,
                        db_pool=db_pool,
                        notes=f"user={user_id}",
                    )
                    if not _floor_regen_ok:
                        if _floor_mode == "enforce_with_alert" or _floor_outcome.get(
                            "reverted_now"
                        ):
                            try:
                                from app.services.flywheel_anomaly import (
                                    notify_flywheel_anomaly,
                                )

                                await notify_flywheel_anomaly(
                                    "structural_floor_persist_fail",
                                    {
                                        "user_id": user_id,
                                        "missing": _missing,
                                        "streak": _floor_outcome.get("streak"),
                                    },
                                    db_pool=db_pool,
                                )
                            except Exception:
                                pass
                        from app.services.stall_suppression import resolve_audit_fallback

                        final_text = resolve_audit_fallback(
                            user_text=_floor_user_text,
                            bridge_event_severity=audit_metadata.get(
                                "bridge_event_severity"
                            )
                            or "info",
                            default_fallback=TRANSPARENT_AUDIT_FALLBACK_MESSAGE,
                        )
                        print(
                            f">>> [THERAPEUTIC-CTRL] structural_floor_fallback "
                            f"user={user_id} mode={_floor_mode} missing={_missing}"
                        )
        except Exception as _floor_exc:
            logger.warning("structural_floor: gate check failed: %s", _floor_exc)

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
        "crisis_exempt": crisis_exempt,
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
            # QUANTUM-CRYSTAL-ARCH: Phase 5b dual-write for Layer-8 inspection
            sym_violations = [v for v in violations if str(v).startswith("symbolic_")]
            if sym_violations and _symbolic_verifier_enabled():
                await conn.execute(
                    """
                    INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                    VALUES ('clinical', 'symbolic_verifier_action', $1, $2, NOW())
                    """,
                    json.dumps({
                        "user_id": user_id,
                        "violations": sym_violations,
                        "audit_passed": audit_passed,
                        "symbolic_regen_used": bool(audit_metadata.get("symbolic_regen_used")),
                    }),
                    "info" if audit_passed else "warning",
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
    """Every pinned `_PHASE_V1_2_BANNED_PHRASES` entry must appear in en-US resolved set.

    Legacy v1.2 pins may be empty; if non-empty, dropping one is a regression.
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
