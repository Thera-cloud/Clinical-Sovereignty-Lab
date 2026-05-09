"""
Introjection / Voice-Shift Mirror — Gap 1.

Detects fawn-response and trafficker-voice introjection by comparing the
user's current message linguistic profile against their established baseline
(`user_linguistic_baseline`) and against known coercive linguistic profiles
(`coercive_voice_profiles`).

Why this matters
----------------
An external-only coercion detector (see `coercion_pattern_detector.py`) misses
the case where the user has *internalized* the trafficker's voice and is
speaking it back as their own. This is a re-traumatization vector if undetected
because Nate validating an introjected coercive voice reinforces the introject.

Per `docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md`
Gap 1:

    The fawn response and trafficker-voice introjection are documented clinical
    phenomena. An external-only coercion detector misses the case where the
    *user* has internalized the trafficker's voice and is speaking it back.
    This is a re-traumatization vector if undetected.

When the detector fires, the orchestrator MUST select
`register_directive='unconditional_mirror'` — Nate reflects the user's *own*
established voice back, never the introjected coercive voice. Banned in this
register: agreement-with-content, validation phrases (validating an introject
reinforces it).

Output contract
---------------
`IntrojectionSignal`:
  - `detected: bool`
  - `confidence: float` — 0.0-1.0
  - `baseline_deviation: float` — cosine distance from user baseline (0=identical, 1=opposite)
  - `coercive_profile_match: str | None` — which `profile_id` matched (if any)
  - `drift_markers: list[str]` — short audit-only labels (no raw user text)
  - `requires_immediate_coach_alert: bool` — True when confidence > 0.75

Coordination
------------
This module reads `user_linguistic_baseline` (migration 203) which is the
*single shared* baseline table — coordinate with phase-coherence
`UserBaselineService`. Do NOT create a second baseline table for the same
purpose elsewhere (per migration 203 comment).

Design invariants
-----------------
1. **No baseline → no detection.** If `user_linguistic_baseline` has no row
   for this user OR `sample_count` < `MIN_SAMPLES_FOR_DETECTION` (default 20),
   return a `_NULL_SIGNAL`. Detecting "drift" against an immature baseline
   is statistically meaningless and produces false positives.
2. **Empty seed lexicons in `coercive_voice_profiles` are valid.** Migration
   203 ships the four canonical profiles with empty `marker_lexicon`. The
   detector treats empty marker arrays as "no match possible for this
   profile" and falls back to baseline-deviation alone. Clinician fills the
   lexicons via review-gated process.
3. **Cosine distance** uses a fixed feature ordering (see `_FEATURE_ORDER`)
   so the comparison is stable across releases. New baseline keys appended
   later require a REGISTRY_VERSION bump.
4. **The `requires_immediate_coach_alert` flag does NOT fire the alert** —
   the orchestrator does, via `coach_override_protocol.escalate_acuity()`.
   This module only signals.
5. NEVER returns user text. Drift markers are short labels.
6. DB read-only. Baseline updates happen in a separate service (
   `UserBaselineService`, Phase 3+).

REGISTRY_VERSION
----------------
Bump REGISTRY_VERSION when:
  - `_FEATURE_ORDER` changes (cosine becomes incompatible across versions)
  - `MIN_SAMPLES_FOR_DETECTION` changes
  - `_DRIFT_THRESHOLDS` change
  - canonical `profile_id` set in `coercive_voice_profiles` is extended
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dormancy log dedup — emit once per (user_id, session_id) per process lifetime
# ---------------------------------------------------------------------------
# Per Decision 3 (Phase 2B clinical-safety review): when introjection detection
# is suppressed because the linguistic baseline is missing or immature, the
# Phase 6 auditor needs to confirm dormancy is happening for the *right* reason
# (no baseline yet — UserBaselineService not done seeding) vs the *wrong* reason
# (DB connection failure masquerading as missing data).
#
# Per-message logging would spam: a session may produce 100+ messages all with
# the same dormant baseline. Per-(user, session) dedup is the contract.
#
# Bounded LRU prevents unbounded memory growth in long-running processes; the
# orchestrator should also call `clear_dormancy_marker(user_id, session_id)`
# at session end for prompt cleanup.
_DORMANT_LOG_CAP = 10_000
_DORMANT_LOGGED: "OrderedDict[str, None]" = OrderedDict()


def _dormancy_key(user_id: str, session_id: Optional[str]) -> str:
    return f"{user_id}|{session_id or 'no_session'}"


def _emit_dormant_event_once(
    event: str,
    user_id: str,
    session_id: Optional[str],
    extra: Optional[Dict[str, Any]] = None,
) -> bool:
    """Emit a structured dormancy event at most once per (user, session).

    Event names (exhaustive):
      - introjection_dormant_no_baseline       — row missing (correct fail-safe)
      - introjection_dormant_baseline_immature — row exists, sample_count too low
      - introjection_dormant_fetch_error       — DB reachability failure (investigate)
      - introjection_dormant_no_pool           — db_pool is None (config issue)

    Returns True if emitted, False if suppressed by dedup.
    """
    key = f"{event}|{_dormancy_key(user_id, session_id)}"
    if key in _DORMANT_LOGGED:
        return False
    _DORMANT_LOGGED[key] = None
    # FIFO eviction when capped.
    while len(_DORMANT_LOGGED) > _DORMANT_LOG_CAP:
        _DORMANT_LOGGED.popitem(last=False)
    payload: Dict[str, Any] = {
        "event": event,
        "user_id": user_id,
        "session_id": session_id or "no_session",
        "registry_version": REGISTRY_VERSION,
    }
    if extra:
        payload.update(extra)
    # Structured (greppable + extra-bearing) — auditor scrapes by event name.
    logger.info("%s payload=%s", event, json.dumps(payload, sort_keys=True), extra=payload)
    return True


def clear_dormancy_marker(user_id: str, session_id: Optional[str]) -> int:
    """Drop dormancy-log dedup entries for a session (call on session end).

    Returns the number of entries removed. Idempotent.
    """
    suffix = "|" + _dormancy_key(user_id, session_id)
    to_remove = [k for k in _DORMANT_LOGGED if k.endswith(suffix)]
    for k in to_remove:
        _DORMANT_LOGGED.pop(k, None)
    return len(to_remove)


def _dormancy_marker_count() -> int:
    """Test/auditor helper — current cardinality of the dedup set."""
    return len(_DORMANT_LOGGED)

REGISTRY_VERSION = "1.0.0-2026-05-08"

# Below this many samples in the baseline, the detector refuses to score.
MIN_SAMPLES_FOR_DETECTION = 20

# Cosine distance thresholds (1 - cosine_similarity).
# 0.0 = identical voice; 1.0 = orthogonal; ~2.0 = anti-correlated.
_DRIFT_THRESHOLDS: Dict[str, float] = {
    "monitor": 0.20,  # mild drift; informative for clinician
    "concern": 0.40,
    "high": 0.60,  # confident introjection
}

# Confidence assigned per drift tier (combined with profile match).
_TIER_CONFIDENCE: Dict[str, float] = {
    "none": 0.0,
    "monitor": 0.3,
    "concern": 0.6,
    "high": 0.85,
}

# Threshold above which `requires_immediate_coach_alert` is set.
COACH_ALERT_CONFIDENCE = 0.75

# Fixed feature ordering for cosine — DO NOT REORDER without REGISTRY_VERSION bump.
# These keys must match what `UserBaselineService` writes into
# `user_linguistic_baseline.baseline_vector`.
_FEATURE_ORDER: Tuple[str, ...] = (
    "avg_msg_length",  # mean tokens per message (normalized below)
    "first_person_rate",  # I/me/my per 100 words
    "second_person_rate",  # you/your per 100 words
    "third_person_rate",  # she/he/they/etc. per 100 words
    "negation_rate",  # not/never/no per 100 words
    "modal_obligation_rate",  # must/should/have to per 100 words
    "self_blame_rate",  # "my fault", "I deserved", etc. per 100 words
    "minimization_rate",  # "just", "only", "kind of" per 100 words
    "sentiment_baseline",  # -1..1 (pre-computed by UserBaselineService)
    "vocabulary_complexity",  # mean type-token ratio
)

# Normalization caps so heterogeneous units don't swamp cosine.
_FEATURE_CAPS: Dict[str, float] = {
    "avg_msg_length": 200.0,  # cap at 200-token messages
    "first_person_rate": 25.0,  # rates already per-100-words
    "second_person_rate": 25.0,
    "third_person_rate": 25.0,
    "negation_rate": 20.0,
    "modal_obligation_rate": 15.0,
    "self_blame_rate": 10.0,
    "minimization_rate": 15.0,
    "sentiment_baseline": 1.0,  # already in [-1, 1]; we re-center to [0, 1]
    "vocabulary_complexity": 1.0,
}


@dataclass(frozen=True)
class IntrojectionSignal:
    """Detector output. Audit-only; never user-facing."""

    detected: bool
    confidence: float
    baseline_deviation: float  # cosine distance, 0=identical
    coercive_profile_match: Optional[str]
    drift_markers: List[str] = field(default_factory=list)
    requires_immediate_coach_alert: bool = False
    suppressed_reason: Optional[str] = None  # populated when baseline immature, etc.


# ---------------------------------------------------------------------------
# Linguistic feature extraction (deterministic, no LLM)
# ---------------------------------------------------------------------------

_FIRST_PERSON = re.compile(r"\b(?:i|i'?m|i'?ve|i'?ll|i'?d|me|my|mine|myself)\b", re.IGNORECASE)
_SECOND_PERSON = re.compile(r"\b(?:you|you'?re|you'?ve|you'?ll|you'?d|your|yours|yourself)\b", re.IGNORECASE)
_THIRD_PERSON = re.compile(
    r"\b(?:she|he|they|her|him|them|hers|his|theirs|herself|himself|themselves|themself)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(?:not|never|no|none|nothing|nobody|nowhere)\b", re.IGNORECASE)
_MODAL_OBLIGATION = re.compile(
    r"\b(?:must|should|have\s+to|need\s+to|got\s+to|gotta|supposed\s+to)\b", re.IGNORECASE
)
_SELF_BLAME = re.compile(
    r"\b(?:my\s+fault|i\s+deserved|i\s+asked\s+for|brought\s+(?:it|that)\s+on\s+myself|"
    r"if\s+i\s+(?:hadn'?t|had\s+not|just)|i\s+should\s+have)\b",
    re.IGNORECASE,
)
_MINIMIZATION = re.compile(
    r"\b(?:just|only|kind\s+of|sort\s+of|a\s+little|barely|hardly|not\s+(?:that|so)\s+(?:bad|much))\b",
    re.IGNORECASE,
)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text)) if text else 0


def _rate_per_100(matches: int, wc: int) -> float:
    return matches * 100.0 / wc if wc > 0 else 0.0


def _ttr(text: str) -> float:
    """Type-token ratio. 0 for empty input."""
    tokens = re.findall(r"\b[\w']+\b", text.lower())
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


def extract_features(text: str) -> Dict[str, float]:
    """Compute the feature vector for a single message.

    Output keys are exactly `_FEATURE_ORDER`. `sentiment_baseline` is set to
    0.0 here (no per-message sentiment dependency); the baseline vector
    carries the user's longitudinal sentiment computed by
    `UserBaselineService`. Cosine handles a single message's missing sentiment
    by leaving the dimension neutral.
    """
    wc = _word_count(text)
    return {
        "avg_msg_length": float(wc),
        "first_person_rate": _rate_per_100(len(_FIRST_PERSON.findall(text)), wc),
        "second_person_rate": _rate_per_100(len(_SECOND_PERSON.findall(text)), wc),
        "third_person_rate": _rate_per_100(len(_THIRD_PERSON.findall(text)), wc),
        "negation_rate": _rate_per_100(len(_NEGATION.findall(text)), wc),
        "modal_obligation_rate": _rate_per_100(len(_MODAL_OBLIGATION.findall(text)), wc),
        "self_blame_rate": _rate_per_100(len(_SELF_BLAME.findall(text)), wc),
        "minimization_rate": _rate_per_100(len(_MINIMIZATION.findall(text)), wc),
        "sentiment_baseline": 0.0,
        "vocabulary_complexity": _ttr(text),
    }


def _normalize(features: Dict[str, float]) -> List[float]:
    """Project features onto _FEATURE_ORDER, normalize to [0, 1] (or [-1, 1] for sentiment)."""
    out: List[float] = []
    for key in _FEATURE_ORDER:
        cap = _FEATURE_CAPS.get(key, 1.0)
        raw = float(features.get(key, 0.0))
        if key == "sentiment_baseline":
            # Re-center [-1, 1] → [0, 1] to match cosine domain expectations.
            out.append(max(0.0, min(1.0, (raw + 1.0) / 2.0)))
        else:
            out.append(max(0.0, min(1.0, raw / cap if cap > 0 else 0.0)))
    return out


def _cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine distance = 1 - (a·b / (||a|| ||b||)). Range [0, 2]."""
    if not a or not b or len(a) != len(b):
        return 1.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 1.0
    sim = dot / (norm_a * norm_b)
    sim = max(-1.0, min(1.0, sim))
    return 1.0 - sim


# ---------------------------------------------------------------------------
# Baseline + coercive-profile loading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BaselineRecord:
    """Snapshot of one row from `user_linguistic_baseline`."""

    user_id: str
    baseline_vector: Dict[str, float]
    sample_count: int
    locked: bool


@dataclass(frozen=True)
class CoerciveProfile:
    """Snapshot of one row from `coercive_voice_profiles`."""

    profile_id: str
    markers: Tuple[re.Pattern, ...]  # compiled marker regexes
    weight_default: float


# Fetch state values returned alongside an Optional[BaselineRecord]. The
# auditor and dormancy logger differentiate "row missing" (correct fail-safe)
# from "fetch_failed" (DB outage that needs investigation).
FETCH_OK = "ok"
FETCH_NO_POOL = "no_pool"
FETCH_MISSING = "missing"
FETCH_FAILED = "fetch_failed"


async def _fetch_baseline(
    db_pool: Any, user_id: str
) -> Tuple[Optional[BaselineRecord], str]:
    """Fetch the user's linguistic baseline.

    Returns:
        (record, fetch_state) where fetch_state is one of FETCH_OK,
        FETCH_NO_POOL, FETCH_MISSING, FETCH_FAILED. The record is non-None
        only when fetch_state == FETCH_OK.
    """
    if db_pool is None or not user_id:
        return None, FETCH_NO_POOL
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT user_id, baseline_vector, sample_count, baseline_locked
                  FROM user_linguistic_baseline
                 WHERE user_id = $1
                """,
                user_id,
            )
        if row is None:
            return None, FETCH_MISSING
        bv_raw = row["baseline_vector"]
        if isinstance(bv_raw, str):
            bv = json.loads(bv_raw)
        elif isinstance(bv_raw, dict):
            bv = bv_raw
        else:
            bv = {}
        # Filter to numeric values only.
        bv_clean: Dict[str, float] = {}
        for k, v in bv.items():
            try:
                bv_clean[k] = float(v)
            except (TypeError, ValueError):
                continue
        return (
            BaselineRecord(
                user_id=row["user_id"],
                baseline_vector=bv_clean,
                sample_count=int(row["sample_count"] or 0),
                locked=bool(row["baseline_locked"]),
            ),
            FETCH_OK,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "introjection_voice_mirror: baseline fetch failed user=%s: %s", user_id, e
        )
        return None, FETCH_FAILED


async def _fetch_active_coercive_profiles(db_pool: Any) -> List[CoerciveProfile]:
    """Read `coercive_voice_profiles` and compile marker regexes.

    Empty marker_lexicon is the seeded default and is valid — the resulting
    profile has zero compiled markers and will never match. That is correct.
    """
    if db_pool is None:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT profile_id, marker_lexicon
                  FROM coercive_voice_profiles
                 WHERE active = TRUE
                 ORDER BY profile_id
                """
            )
        out: List[CoerciveProfile] = []
        for r in rows:
            raw = r["marker_lexicon"]
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except json.JSONDecodeError:
                    raw = {}
            if not isinstance(raw, dict):
                raw = {}
            markers_raw = raw.get("markers", [])
            weight_default = float(raw.get("weight_default", 0.0))
            compiled: List[re.Pattern] = []
            for entry in markers_raw:
                if isinstance(entry, str):
                    pattern_str = entry
                elif isinstance(entry, dict) and "regex" in entry:
                    pattern_str = str(entry["regex"])
                else:
                    continue
                try:
                    compiled.append(re.compile(pattern_str, re.IGNORECASE))
                except re.error as e:
                    logger.warning(
                        "introjection_voice_mirror: bad marker regex profile=%s: %s",
                        r["profile_id"],
                        e,
                    )
            out.append(
                CoerciveProfile(
                    profile_id=r["profile_id"],
                    markers=tuple(compiled),
                    weight_default=weight_default,
                )
            )
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("introjection_voice_mirror: profile fetch failed: %s", e)
        return []


def _match_coercive_profile(
    text: str, profiles: Sequence[CoerciveProfile]
) -> Tuple[Optional[str], float, List[str]]:
    """Return (best_profile_id, best_score, drift_marker_labels).

    Score is `(matches / total_markers) * weight_default` for the
    highest-scoring profile. Returns (None, 0.0, []) when no markers match
    or when all profiles have empty marker sets.
    """
    best_id: Optional[str] = None
    best_score = 0.0
    best_labels: List[str] = []
    for prof in profiles:
        if not prof.markers:
            continue
        fired_indices: List[int] = []
        for idx, pat in enumerate(prof.markers):
            if pat.search(text):
                fired_indices.append(idx)
        if not fired_indices:
            continue
        match_ratio = len(fired_indices) / len(prof.markers)
        score = match_ratio * (prof.weight_default if prof.weight_default > 0 else 1.0)
        if score > best_score:
            best_score = score
            best_id = prof.profile_id
            best_labels = [f"{prof.profile_id}_marker_{i}" for i in fired_indices]
    return best_id, min(1.0, best_score), best_labels


def _tier_for_distance(distance: float) -> str:
    if distance >= _DRIFT_THRESHOLDS["high"]:
        return "high"
    if distance >= _DRIFT_THRESHOLDS["concern"]:
        return "concern"
    if distance >= _DRIFT_THRESHOLDS["monitor"]:
        return "monitor"
    return "none"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_NULL_SIGNAL = IntrojectionSignal(
    detected=False,
    confidence=0.0,
    baseline_deviation=0.0,
    coercive_profile_match=None,
    drift_markers=[],
    requires_immediate_coach_alert=False,
    suppressed_reason=None,
)


async def analyze_introjection(
    user_id: str,
    message: str,
    db_pool: Any,
    session_id: Optional[str] = None,
) -> IntrojectionSignal:
    """Compare current message against user baseline + coercive profiles.

    Args:
        user_id: username (matches `user_linguistic_baseline.user_id`).
        message: the inbound user message.
        db_pool: asyncpg-style pool. May be None — detector returns NULL.
        session_id: optional session correlation id used to dedup the
            structured dormancy log event so it fires at most once per
            (user_id, session_id) per process. When None, dedup degrades
            to per-user-per-process.

    Returns:
        IntrojectionSignal. Never raises.
    """
    if not message or not message.strip():
        return _NULL_SIGNAL

    baseline, fetch_state = await _fetch_baseline(db_pool, user_id)
    if fetch_state != FETCH_OK:
        # Map fetch_state → structured event so the auditor can distinguish
        # correct dormancy (no baseline yet) from infrastructure failures.
        event_for_state = {
            FETCH_NO_POOL: "introjection_dormant_no_pool",
            FETCH_MISSING: "introjection_dormant_no_baseline",
            FETCH_FAILED: "introjection_dormant_fetch_error",
        }.get(fetch_state, "introjection_dormant_no_baseline")
        _emit_dormant_event_once(
            event_for_state, user_id, session_id, extra={"fetch_state": fetch_state}
        )
        return IntrojectionSignal(
            detected=False,
            confidence=0.0,
            baseline_deviation=0.0,
            coercive_profile_match=None,
            drift_markers=[],
            requires_immediate_coach_alert=False,
            suppressed_reason=f"no_baseline:{fetch_state}",
        )
    assert baseline is not None  # FETCH_OK guarantees non-None
    if baseline.sample_count < MIN_SAMPLES_FOR_DETECTION:
        _emit_dormant_event_once(
            "introjection_dormant_baseline_immature",
            user_id,
            session_id,
            extra={
                "sample_count": baseline.sample_count,
                "min_required": MIN_SAMPLES_FOR_DETECTION,
            },
        )
        return IntrojectionSignal(
            detected=False,
            confidence=0.0,
            baseline_deviation=0.0,
            coercive_profile_match=None,
            drift_markers=[],
            requires_immediate_coach_alert=False,
            suppressed_reason=f"baseline_immature_{baseline.sample_count}",
        )

    # Compute current vs baseline cosine distance.
    current_features = extract_features(message)
    current_vec = _normalize(current_features)
    baseline_vec = _normalize(baseline.baseline_vector)
    distance = _cosine_distance(current_vec, baseline_vec)

    # Coercive profile match (additive evidence).
    profiles = await _fetch_active_coercive_profiles(db_pool)
    profile_id, profile_score, profile_labels = _match_coercive_profile(message, profiles)

    # Tier from distance alone, then bump confidence by profile match.
    tier = _tier_for_distance(distance)
    base_conf = _TIER_CONFIDENCE[tier]
    confidence = min(1.0, base_conf + 0.5 * profile_score)

    # Detection requires either a non-trivial drift tier OR a profile match.
    detected = tier != "none" or profile_id is not None

    drift_markers: List[str] = []
    if tier != "none":
        drift_markers.append(f"baseline_drift_{tier}")
    drift_markers.extend(profile_labels)

    return IntrojectionSignal(
        detected=detected,
        confidence=confidence,
        baseline_deviation=distance,
        coercive_profile_match=profile_id,
        drift_markers=drift_markers,
        requires_immediate_coach_alert=confidence > COACH_ALERT_CONFIDENCE,
        suppressed_reason=None,
    )


# ---------------------------------------------------------------------------
# Auditor hook
# ---------------------------------------------------------------------------


def _auditor_self_check() -> dict:
    """Synchronous fixture-based check — no DB required.

    Verifies feature extraction is deterministic, cosine distance behaves
    correctly on identical/orthogonal vectors, and tier thresholds map as
    documented. Async DB path is verified by the Phase 6 auditor against
    staging DB (per Phase 6 ticket caveat).
    """
    result: dict = {
        "version": REGISTRY_VERSION,
        "feature_order_len": len(_FEATURE_ORDER),
        "min_samples_for_detection": MIN_SAMPLES_FOR_DETECTION,
        "thresholds": dict(_DRIFT_THRESHOLDS),
        "fixture_results": {},
    }
    sample = "I just feel like it was my fault and I should have known better"
    feats = extract_features(sample)
    result["fixture_results"]["feature_keys_match"] = (
        sorted(feats.keys()) == sorted(_FEATURE_ORDER)
    )
    result["fixture_results"]["self_blame_fired"] = feats["self_blame_rate"] > 0
    result["fixture_results"]["minimization_fired"] = feats["minimization_rate"] > 0
    # Cosine sanity
    v_a = _normalize(extract_features("I am okay"))
    v_b = _normalize(extract_features("I am okay"))
    result["fixture_results"]["cosine_identical_zero"] = _cosine_distance(v_a, v_b) < 1e-9
    v_orth_a = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    v_orth_b = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    result["fixture_results"]["cosine_orthogonal_one"] = (
        abs(_cosine_distance(v_orth_a, v_orth_b) - 1.0) < 1e-9
    )
    # Tier mapping
    result["fixture_results"]["tier_high"] = _tier_for_distance(0.7) == "high"
    result["fixture_results"]["tier_concern"] = _tier_for_distance(0.45) == "concern"
    result["fixture_results"]["tier_monitor"] = _tier_for_distance(0.25) == "monitor"
    result["fixture_results"]["tier_none"] = _tier_for_distance(0.05) == "none"

    # Dormancy log dedup contract: same (event, user, session) emits once.
    test_user = "__auditor_self_check_user__"
    test_session = "__auditor_self_check_session__"
    clear_dormancy_marker(test_user, test_session)  # ensure clean slate
    first = _emit_dormant_event_once(
        "introjection_dormant_no_baseline", test_user, test_session
    )
    second = _emit_dormant_event_once(
        "introjection_dormant_no_baseline", test_user, test_session
    )
    different_event = _emit_dormant_event_once(
        "introjection_dormant_baseline_immature", test_user, test_session
    )
    cleared = clear_dormancy_marker(test_user, test_session)
    after_clear = _emit_dormant_event_once(
        "introjection_dormant_no_baseline", test_user, test_session
    )
    clear_dormancy_marker(test_user, test_session)  # cleanup
    result["fixture_results"]["dormancy_dedup_first_emits"] = bool(first)
    result["fixture_results"]["dormancy_dedup_second_suppressed"] = not second
    result["fixture_results"]["dormancy_distinct_events_independent"] = bool(different_event)
    result["fixture_results"]["dormancy_clear_returns_count"] = cleared >= 2
    result["fixture_results"]["dormancy_clear_resets_dedup"] = bool(after_clear)

    result["healthy"] = all(bool(v) for v in result["fixture_results"].values())
    return result


__all__ = [
    "REGISTRY_VERSION",
    "MIN_SAMPLES_FOR_DETECTION",
    "COACH_ALERT_CONFIDENCE",
    "FETCH_OK",
    "FETCH_NO_POOL",
    "FETCH_MISSING",
    "FETCH_FAILED",
    "IntrojectionSignal",
    "extract_features",
    "analyze_introjection",
    "clear_dormancy_marker",
]
