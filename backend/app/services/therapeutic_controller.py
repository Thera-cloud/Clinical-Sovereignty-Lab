"""# FIX-THERAPEUTIC-CONTROLLER
State-dependent therapeutic controller — pre-flight + post-flight wrappers.

Wraps bridge_server's per-turn LLM dispatch without replacing it. Pre-flight
shapes the system prompt and token cap based on autonomic state, TMC class,
coherence trend, recurring patterns, and recent narratives. Post-flight
audits the final response, regenerates once on violation when a mismatch was
attempted, and logs metrics to sse_therapeutic_audit_log.

Backwards compatible: caller wraps each entry point in try/except and falls
back to existing behavior on any failure.
"""

import json
import logging
import re
from typing import Any, Optional

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
    "shutdown": 200,
    "activated": 350,
    "in_window": 600,
    "regulated": 1500,
}

_LABILE_WINDOW_TMC = {"THRESHOLD", "BREAKTHROUGH", "RECURRENCE"}

# Banned phrases (Lisa transcript audit + register guidelines)
_BANNED_PHRASES_ALWAYS = [
    "i sense",
    "i want to acknowledge",
    "it takes courage",
    "holding space",
    "honor your journey",
    "liminal threshold",
    "sit with that",
]


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
) -> dict:
    """Classify state, assemble context, shape prompt + cap. Always returns
    a dict; on partial failure, fields default to the original prompt/cap."""
    tmc_result = await _classify_tmc(db_pool, user_id)
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

    recent_narratives = await _fetch_recent_narratives(db_pool, user_id)
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

    enriched = (
        f"## DNA — NEUROSCIENCE BEDROCK\n{_DNA_PREFIX}\n\n"
        f"## CURRENT THERAPEUTIC STATE\n"
        f"autonomic_state: {autonomic_state} | tmc_class: {tmc_class} | "
        f"ec_current: {ec_current:.2f} | ec_slope: {ec_slope:+.2f}\n\n"
        f"{_state_guidance(autonomic_state)}\n"
        f"{mismatch_block}\n"
        f"{neuroscience_ctx}\n"
        f"{_anti_repeat_block(recent_narratives)}\n\n"
        f"---\n\n{base_system_prompt}"
    )

    return {
        "enriched_system_prompt": enriched,
        "max_tokens": max_tokens,
        "recent_narratives": recent_narratives,
        "audit_metadata": {
            "autonomic_state": autonomic_state,
            "tmc_class": tmc_class,
            "mismatch_available": mismatch_available,
            "encoded_patterns": encoded_patterns,
            "register_default": "CLINICAL_BRIDGED" if mismatch_available else "WARM",
            "max_tokens": max_tokens,
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

    for phrase in _BANNED_PHRASES_ALWAYS:
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

    if not audit_passed and audit_metadata.get("mismatch_available"):
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
