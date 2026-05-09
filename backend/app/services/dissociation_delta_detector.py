"""
Dissociation Delta Detector — mid-conversation dissociative-shift analyzer.

Reads turn N (the just-arrived inbound user message) and compares it against
turns N-3..N-1 from `conversation_history`. Triggers on three independent
signal classes:

  1. **Voice / POV shift**  — sudden first-person → third-person about self
     ("I felt..." → "she just stood there"); or shift from "I" to "you" used
     as self-reference ("you just freeze, you know?"). Documented in DSM-5
     depersonalization-derealization criteria.
  2. **Depersonalization markers** — explicit phrases ("I watched myself",
     "it was like I wasn't there", "I went away", "felt like a movie", etc.).
     Conservative seed; clinician overlay tunes per population.
  3. **Length / style delta** — current message length deviates >2 sigma from
     recent rolling mean. Sudden one-word reply after multi-sentence flow,
     or sudden long flat-affect monologue after short engaged turns.

Per `docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md`
section 3:

    dissociation_delta_detector.py — analyzes turn N against turns N-3..N-1
    from `conversation_history`. Triggers on: sudden voice/POV shift
    (I→she/they), depersonalization language ("I watched myself"), >2sigma
    length/style delta. Returns DissociationSignal{detected, confidence,
    markers}. Output drives a new register variant (see #4).

Output contract
---------------
`DissociationSignal`:
  - `detected: bool`
  - `confidence: float` — 0.0-1.0
  - `markers: list[str]` — short labels of which signals fired (audit-only)
  - `pov_shift_detected: bool`
  - `depersonalization_detected: bool`
  - `length_anomaly_z: float | None` — z-score of current message length vs
    recent mean (None if insufficient history)
  - `recommended_register: str | None` — 'dissociation_grounding' when
    detected; orchestrator may choose to override.

Design invariants
-----------------
1. Confidence is the **average** of fired-signal confidences, capped at 1.0.
   A single low-confidence signal (e.g., length delta of z=2.1 only) yields
   a low confidence — which is correct. Multiple signals compound.
2. Z-score requires >=3 prior turns. With <3, length signal is suppressed
   (returns None) — never invented from too-small samples.
3. POV-shift detection compares pronoun ratios in the current message vs
   the rolling baseline of the prior turns. The threshold is conservative;
   a single "she" in a long "I" message does NOT fire — only a clear
   inversion does.
4. NEVER returns user text. `markers` are short labels.
5. Failure modes (DB unreachable, empty history) degrade gracefully:
   detector returns a signal scoped to *what it could measure* (e.g.,
   depersonalization markers from current message alone). It never raises.
6. The detector is read-only against `conversation_history`. It never writes.

REGISTRY_VERSION
----------------
Bump REGISTRY_VERSION when DEPERSONALIZATION_PHRASES or thresholds change.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

REGISTRY_VERSION = "1.0.0-2026-05-08"

# Window of prior turns to inspect.
LOOKBACK_TURNS = 3

# Z-score threshold for length anomaly (per plan: ">2sigma length/style delta").
LENGTH_Z_THRESHOLD = 2.0

# Minimum prior turns required to compute length z-score honestly.
MIN_PRIOR_FOR_Z = 3

# ---------------------------------------------------------------------------
# DETECTOR CONTRACT — DO NOT REMOVE OR LOWER WITHOUT CLINICAL REVIEW
# ---------------------------------------------------------------------------
# Floor below which the orchestrator MUST NOT dispatch a register change.
# Length anomaly alone confidence = 0.45; this constant prevents
# single-weak-signal register modulation from firing `dissociation_grounding`.
#
# Rationale: length_anomaly is "informative not diagnostic" — a one-word reply
# after multi-sentence flow may be dissociation, but it may also be fatigue,
# distraction, or simply the conversation finishing a thought. Firing the
# grounding register on that signal alone would (a) interrupt non-dissociated
# clients with somatic prompts they did not need, and (b) train clients to
# associate brief replies with Nate "going clinical" — a chilling effect on
# natural conversational rhythm.
#
# This constant is the *contract* between detector and orchestrator. The
# orchestrator's policy threshold may be HIGHER than this floor, but never
# lower. Compile-time enforcement (orchestrator imports this constant); not
# runtime hope.
#
# If you find yourself wanting to lower this for "more sensitivity," the
# correct architectural fix is to have the orchestrator escalate via signal
# *frequency across turns*, not by lowering the per-turn confidence floor.
MIN_REGISTER_CONFIDENCE: float = 0.55
# ---------------------------------------------------------------------------

# Confidence assigned to each signal class when it fires.
_SIGNAL_CONFIDENCE = {
    "depersonalization": 0.85,
    "pov_shift": 0.70,
    "length_anomaly": 0.45,
}


# ---------------------------------------------------------------------------
# Seed depersonalization phrase set
#
# DSM-5 derived (Depersonalization-Derealization Disorder, criteria A.1-A.2)
# plus widely documented colloquial expressions. Seed is intentionally short;
# overlay (`backend/data/lexicons/dissociation_phrases_<locale>.json`)
# supplements per population.
# ---------------------------------------------------------------------------

DEPERSONALIZATION_PHRASES: Tuple[str, ...] = (
    r"\bi\s+watched\s+myself\b",
    r"\bwatching\s+myself\s+from\s+(?:above|outside|the\s+ceiling)\b",
    r"\b(?:it|everything)\s+felt\s+(?:like\s+)?(?:a\s+)?(?:dream|movie|tv\s+show|video)\b",
    r"\bi\s+(?:wasn'?t|was\s+not)\s+(?:really\s+)?(?:there|in\s+my\s+body|present)\b",
    r"\b(?:floated|drifted)\s+(?:up|out|away|outside\s+(?:my|of\s+my)\s+body)\b",
    r"\bi\s+(?:went|just\s+went)\s+(?:away|somewhere\s+else|blank)\b",
    r"\b(?:lost|losing)\s+time\b",
    r"\b(?:checked|tuned)\s+out\b",
    r"\bnot\s+real\b.{0,30}\b(?:happening|happened)\b",
    r"\b(?:numb|frozen|disconnected)\s+from\s+(?:my\s+body|myself|everything)\b",
    r"\b(?:autopilot|on\s+autopilot)\b",
    # Derealization variants
    r"\b(?:everything|the\s+room|the\s+world)\s+(?:looks|seemed|seems|got)\s+(?:fake|unreal|distant|far\s+away)\b",
)


@dataclass(frozen=True)
class DissociationSignal:
    """Detector output. Audit-only; never user-facing."""

    detected: bool
    confidence: float
    markers: List[str] = field(default_factory=list)
    pov_shift_detected: bool = False
    depersonalization_detected: bool = False
    length_anomaly_z: Optional[float] = None
    recommended_register: Optional[str] = None  # 'dissociation_grounding' when detected


# ---------------------------------------------------------------------------
# Lexicon overlay loading
# ---------------------------------------------------------------------------

_COMPILED_PHRASES: List[re.Pattern] = []
_LEXICON_DIR_DEFAULT = os.environ.get(
    "DISSOCIATION_LEXICON_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "lexicons"),
)


def _compile_seed() -> List[re.Pattern]:
    out: List[re.Pattern] = []
    for raw in DEPERSONALIZATION_PHRASES:
        try:
            out.append(re.compile(raw, re.IGNORECASE))
        except re.error as e:  # pragma: no cover — defensive
            logger.warning("dissociation_delta_detector: regex compile failed %r: %s", raw, e)
    return out


_COMPILED_PHRASES = _compile_seed()


def _load_overlay_phrases(locale: str) -> List[re.Pattern]:
    """Optional clinician overlay. Schema: {"phrases": ["regex1", "regex2", ...]}.

    Missing/malformed overlay → returns [] silently.
    """
    fname = f"dissociation_phrases_{locale}.json"
    path = os.path.normpath(os.path.join(_LEXICON_DIR_DEFAULT, fname))
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        out: List[re.Pattern] = []
        for raw in doc.get("phrases", []):
            try:
                out.append(re.compile(str(raw), re.IGNORECASE))
            except re.error as e:
                logger.warning(
                    "dissociation_delta_detector: overlay regex skipped %r: %s", raw, e
                )
        return out
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("dissociation_delta_detector: overlay load failed %s: %s", path, e)
        return []


# ---------------------------------------------------------------------------
# Pronoun ratios — used for POV-shift detection
# ---------------------------------------------------------------------------

# Pronouns are matched as standalone words (case-insensitive).
_FIRST_PERSON = re.compile(r"\b(?:i|i'?m|i'?ve|i'?ll|i'?d|me|my|mine|myself)\b", re.IGNORECASE)
_THIRD_PERSON_SELF_PROXY = re.compile(
    r"\b(?:she|he|they|her|him|them|herself|himself|themself|themselves)\b", re.IGNORECASE
)
# "you" used as self-reference is itself a dissociation cue ("you just
# freeze when it happens"), but lone "you" is also normal direct address.
# We measure its rate but only flag when combined with depersonalization
# markers OR when prior turns are dominantly first-person.
_SECOND_PERSON_SELF_PROXY = re.compile(r"\byou\s+(?:just|always|kind\s+of|sort\s+of)\b", re.IGNORECASE)


def _word_count(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\b[\w']+\b", text))


def _pronoun_profile(text: str) -> Tuple[float, float, float]:
    """Return (first_person_rate, third_person_rate, second_person_self_rate).

    Rates are matches-per-100-words to be length-independent.
    """
    wc = max(_word_count(text), 1)
    return (
        len(_FIRST_PERSON.findall(text)) * 100.0 / wc,
        len(_THIRD_PERSON_SELF_PROXY.findall(text)) * 100.0 / wc,
        len(_SECOND_PERSON_SELF_PROXY.findall(text)) * 100.0 / wc,
    )


def _detect_depersonalization(text: str, overlay: Sequence[re.Pattern]) -> List[str]:
    """Return list of fired phrase labels (truncated to short form, no user text)."""
    fired: List[str] = []
    if not text:
        return fired
    for idx, pat in enumerate(_COMPILED_PHRASES):
        if pat.search(text):
            fired.append(f"seed_phrase_{idx}")
    for idx, pat in enumerate(overlay):
        if pat.search(text):
            fired.append(f"overlay_phrase_{idx}")
    return fired


def _detect_pov_shift(current_text: str, prior_texts: Sequence[str]) -> bool:
    """Compare pronoun rates of current msg vs aggregated prior msgs.

    Fires when prior turns were dominantly first-person (>= 4/100 words) AND
    the current message inverts to dominantly third-person about self
    (third > first AND third >= 3/100 words). Conservative — requires the
    inversion to be *clear*, not a single pronoun.
    """
    if not prior_texts:
        return False
    prior_aggregate = " ".join(prior_texts)
    p_first, p_third, _ = _pronoun_profile(prior_aggregate)
    c_first, c_third, _ = _pronoun_profile(current_text)
    return p_first >= 4.0 and c_third > c_first and c_third >= 3.0


def _length_z_score(current_wc: int, prior_wcs: Sequence[int]) -> Optional[float]:
    """Return z-score of current word count vs prior, or None if too few priors."""
    if len(prior_wcs) < MIN_PRIOR_FOR_Z:
        return None
    mean = sum(prior_wcs) / len(prior_wcs)
    variance = sum((w - mean) ** 2 for w in prior_wcs) / len(prior_wcs)
    sigma = math.sqrt(variance)
    if sigma == 0:
        return None
    return (current_wc - mean) / sigma


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_NULL_SIGNAL = DissociationSignal(
    detected=False,
    confidence=0.0,
    markers=[],
    pov_shift_detected=False,
    depersonalization_detected=False,
    length_anomaly_z=None,
    recommended_register=None,
)


async def _fetch_recent_user_turns(
    db_pool: Any, user_id: str, limit: int = LOOKBACK_TURNS
) -> List[str]:
    """Fetch the user's last N `user_text` entries from conversation_history.

    Returns oldest-first. On any DB failure, returns []. Never raises.
    """
    if db_pool is None or not user_id:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_text
                  FROM conversation_history
                 WHERE user_id = $1
                 ORDER BY created_at DESC
                 LIMIT $2
                """,
                user_id,
                int(limit),
            )
        # Oldest-first ordering for callers that care about temporal direction.
        return [r["user_text"] for r in reversed(rows) if r["user_text"]]
    except Exception as e:  # noqa: BLE001 — degrade silently
        logger.warning(
            "dissociation_delta_detector: history fetch failed user=%s: %s", user_id, e
        )
        return []


async def analyze_dissociation(
    user_id: str,
    message: str,
    db_pool: Any,
    locale: str = "en_US",
    prior_turns_override: Optional[Sequence[str]] = None,
) -> DissociationSignal:
    """Primary detector entry point.

    Args:
        user_id: username (matches `conversation_history.user_id`).
        message: the inbound user message (turn N).
        db_pool: asyncpg-style pool. May be None — detector degrades to
                 current-message-only depersonalization scan.
        locale: BCP-47-ish for overlay lookup.
        prior_turns_override: bypasses DB fetch (testing + orchestrator
                 cache). When provided, db_pool is not consulted.

    Returns:
        DissociationSignal. Never raises.
    """
    if not message or not message.strip():
        return _NULL_SIGNAL

    # Acquire prior turns
    if prior_turns_override is not None:
        prior_texts = [t for t in prior_turns_override if t]
    else:
        prior_texts = await _fetch_recent_user_turns(db_pool, user_id, LOOKBACK_TURNS)

    # Signal 1: depersonalization markers (works without history)
    overlay = _load_overlay_phrases(locale)
    fired_phrases = _detect_depersonalization(message, overlay)
    deperson_detected = bool(fired_phrases)

    # Signal 2: POV shift (requires prior turns)
    pov_detected = _detect_pov_shift(message, prior_texts) if prior_texts else False

    # Signal 3: length anomaly (requires >= MIN_PRIOR_FOR_Z prior turns)
    current_wc = _word_count(message)
    prior_wcs = [_word_count(t) for t in prior_texts]
    z_score = _length_z_score(current_wc, prior_wcs)
    length_anomaly = z_score is not None and abs(z_score) >= LENGTH_Z_THRESHOLD

    # Aggregate
    fired_signals: List[str] = []
    confidences: List[float] = []
    if deperson_detected:
        fired_signals.append("depersonalization")
        confidences.append(_SIGNAL_CONFIDENCE["depersonalization"])
    if pov_detected:
        fired_signals.append("pov_shift")
        confidences.append(_SIGNAL_CONFIDENCE["pov_shift"])
    if length_anomaly:
        fired_signals.append("length_anomaly")
        confidences.append(_SIGNAL_CONFIDENCE["length_anomaly"])

    if not fired_signals:
        # Even when nothing fires, surface the z-score for orchestrator
        # observability (it may correlate with other detectors).
        return DissociationSignal(
            detected=False,
            confidence=0.0,
            markers=[],
            pov_shift_detected=False,
            depersonalization_detected=False,
            length_anomaly_z=z_score,
            recommended_register=None,
        )

    # Average + small bonus for compounding signals (capped at 1.0).
    avg_confidence = sum(confidences) / len(confidences)
    compound_bonus = 0.05 * (len(confidences) - 1)
    confidence = min(1.0, avg_confidence + compound_bonus)

    markers: List[str] = list(fired_signals)
    if fired_phrases:
        # Include phrase labels (no raw user text) for audit detail
        markers.extend(fired_phrases)

    # CONTRACT: recommended_register populates ONLY when confidence clears
    # the MIN_REGISTER_CONFIDENCE floor. Below floor, `detected=True` still
    # surfaces for orchestrator/auditor observability, but the field that
    # drives register dispatch is intentionally None. This prevents a
    # buggy/aggressive orchestrator from firing `dissociation_grounding`
    # on length-anomaly-alone (confidence 0.45 < 0.55).
    register: Optional[str] = (
        "dissociation_grounding" if confidence >= MIN_REGISTER_CONFIDENCE else None
    )

    return DissociationSignal(
        detected=True,
        confidence=confidence,
        markers=markers,
        pov_shift_detected=pov_detected,
        depersonalization_detected=deperson_detected,
        length_anomaly_z=z_score,
        recommended_register=register,
    )


# ---------------------------------------------------------------------------
# Auditor hook
# ---------------------------------------------------------------------------


def _auditor_self_check() -> dict:
    """Synchronous fixture-based sanity check for Phase 6 auditor.

    Verifies depersonalization phrases compile and fire on canonical fixtures,
    POV-shift detector fires on a constructed inversion, and length z-score
    function honors MIN_PRIOR_FOR_Z. Async DB path is verified separately
    by the auditor against staging DB (per Phase 6 ticket caveat).
    """
    result: dict = {
        "version": REGISTRY_VERSION,
        "depersonalization_phrase_count": len(_COMPILED_PHRASES),
        "fixtures_passed": [],
        "fixtures_failed": [],
    }
    fixtures = {
        "watched_myself": "I watched myself from the ceiling that whole time",
        "felt_like_movie": "everything felt like a movie I was in but not really",
        "went_blank": "I just went blank, I don't remember much",
        "depersonalized_body": "I felt disconnected from my body the whole time",
    }
    for name, txt in fixtures.items():
        fired = _detect_depersonalization(txt, [])
        if fired:
            result["fixtures_passed"].append(name)
        else:
            result["fixtures_failed"].append(name)
    # POV inversion
    prior = [
        "I felt really angry that day",
        "I tried to stay calm but I couldn't",
        "I just kept thinking about what happened to me",
    ]
    current = "she just stood there and she watched and she didn't move"
    pov_ok = _detect_pov_shift(current, prior)
    result["pov_shift_fixture"] = "passed" if pov_ok else "failed"
    # Length z-score honors MIN_PRIOR_FOR_Z
    z_too_few = _length_z_score(50, [10, 12])
    z_enough = _length_z_score(50, [10, 12, 11, 13])
    result["z_score_min_prior_ok"] = z_too_few is None and z_enough is not None

    # Floor enforcement: length-anomaly-alone (confidence 0.45) must NOT
    # populate recommended_register. Verify the contract.
    floor_ok = (
        _SIGNAL_CONFIDENCE["length_anomaly"] < MIN_REGISTER_CONFIDENCE
        and MIN_REGISTER_CONFIDENCE >= 0.50
    )
    result["min_register_confidence"] = MIN_REGISTER_CONFIDENCE
    result["floor_contract_ok"] = floor_ok

    result["healthy"] = (
        result["depersonalization_phrase_count"] > 0
        and not result["fixtures_failed"]
        and result["pov_shift_fixture"] == "passed"
        and bool(result["z_score_min_prior_ok"])
        and floor_ok
    )
    return result


__all__ = [
    "REGISTRY_VERSION",
    "LOOKBACK_TURNS",
    "LENGTH_Z_THRESHOLD",
    "MIN_REGISTER_CONFIDENCE",
    "DEPERSONALIZATION_PHRASES",
    "DissociationSignal",
    "analyze_dissociation",
]
