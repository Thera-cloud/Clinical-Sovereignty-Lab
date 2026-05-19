"""
Phase 1.5 — Per-turn semantic classifier for adaptive mode detection.

Calls a cheap, fast LLM (GPT-4o-mini via Azure) to extract structured
signals that regex patterns cannot catch: indirect self-blame, smooth
escalation, semantic domain detection, and dissatisfaction without
keyword overlap.

Outputs feed the SAME SessionState accumulators that regex feeds.
Mode-selection logic does not know or care which detector contributed.

Closes plan Gaps 11 (indirect distress), 12 (static thresholds),
14 (arc memory input), 15 (scope coverage), 16 (dissatisfaction lag).

Gap 13 (masking co-occurrence) is already fixed in regex Phase 1.

Design constraints:
    - 300 ms hard timeout — on timeout, fall back to regex-only.
    - Circuit breaker — 60 s cooldown after 3 consecutive failures.
    - Skip messages < 12 chars, GUEST sessions, rate-limit 1 call / 1.5 s.
    - LRU cache (16 entries) deduplicates identical messages within session.
    - This module is ASYNC — it must be awaited from prepare_response.
    - ENABLE_CLASSIFIER_LAYER env flag (default false) gates accumulator
      writes; shadow logging always runs.
"""
# QUANTUM-CRYSTAL-ARCH — Phase 1.5 classifier layer

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ENABLE_CLASSIFIER_LAYER: bool = os.getenv(
    "ENABLE_CLASSIFIER_LAYER", "false"
).lower() in ("true", "1", "yes")

# ============================================================
# TUNABLE CONSTANTS
# ============================================================

def _timeout_s() -> float:
    """Foundry chat p50 ~1.5s from BLUE; 300ms only viable on co-located mini deploy."""
    return float(os.getenv("CLASSIFIER_TIMEOUT_S", "2.5"))


def _rate_limit_s() -> float:
    return float(os.getenv("CLASSIFIER_RATE_LIMIT_S", "1.5"))


_MIN_MSG_LEN: int = 12
_CACHE_SIZE: int = 16
_CIRCUIT_BREAK_FAILURES: int = 3
_CIRCUIT_BREAK_COOLDOWN_S: float = 60.0

_CLASSIFIER_DEPLOYMENT = os.getenv(
    "CLASSIFIER_LLM_DEPLOYMENT", "gpt-4o-mini"
)


def reset_classifier_circuit() -> None:
    """Test harness: clear circuit breaker and rate-limit state."""
    global _consecutive_failures, _circuit_open_until
    _consecutive_failures = 0
    _circuit_open_until = 0.0
    _last_call_ts.clear()

# ============================================================
# PROMPT (versioned — bump suffix on semantic changes)
# ============================================================

_CLASSIFIER_PROMPT_V1 = """\
You are analyzing one message from a coaching conversation.
Return JSON with these fields:

  distress_intensity: 0-3
    (0 = neutral, 1 = some difficulty, 2 = sustained difficulty,
     3 = severe distress)

  indirect_self_blame: true | false
    (does the message express that something is wrong with the user,
     even without using the words "wrong with me"?)

  escalation_from_calm: true | false
    (does this message represent emotional escalation from a
     neutral baseline?)

  request_shape: emotional_processing | action_request | \
information_seeking | venting | redirect | social

  domains_present: [list from: identity_struggle, social_cognition, \
marital_conflict, family_of_origin, trauma_abuse, grief_loss, \
addiction_compulsion, work_stress, parenting, shame_worthlessness, \
sexuality_intimacy, faith_spirituality]

  weight: 0.0-1.0
    (how heavy is this message relative to ordinary conversation)

Return ONLY one valid JSON object.
No markdown fences.
No prose before or after JSON.\
"""

_CLASSIFIER_PROMPT_V1_STRICT = """\
Return ONLY a valid JSON object for the requested schema.
No markdown.
No code fences.
No extra text.
"""

# ============================================================
# OUTPUT DATACLASS
# ============================================================

_VALID_SHAPES = frozenset({
    "emotional_processing", "action_request", "information_seeking",
    "venting", "redirect", "social",
})

_VALID_DOMAINS = frozenset({
    "identity_struggle", "social_cognition", "marital_conflict",
    "family_of_origin", "trauma_abuse", "grief_loss",
    "addiction_compulsion", "work_stress", "parenting",
    "shame_worthlessness", "sexuality_intimacy", "faith_spirituality",
})


@dataclass(frozen=True)
class ClassifierResult:
    distress_intensity: int = 0
    indirect_self_blame: bool = False
    escalation_from_calm: bool = False
    request_shape: str = "emotional_processing"
    domains_present: tuple = ()
    weight: float = 0.0
    raw_json: Optional[str] = None
    error: Optional[str] = None
    latency_ms: float = 0.0


_EMPTY = ClassifierResult()

# ============================================================
# CIRCUIT BREAKER STATE (module-level, per-process)
# ============================================================

_consecutive_failures: int = 0
_circuit_open_until: float = 0.0

# ============================================================
# LRU CACHE (per-session, keyed by user_id)
# ============================================================

_session_caches: Dict[str, Dict[str, ClassifierResult]] = {}


def _get_cache(user_id: str) -> Dict[str, ClassifierResult]:
    if user_id not in _session_caches:
        _session_caches[user_id] = {}
    return _session_caches[user_id]


def clear_session_cache(user_id: str) -> None:
    _session_caches.pop(user_id, None)


# Per-user rate limit tracking
_last_call_ts: Dict[str, float] = {}

# ============================================================
# PARSE
# ============================================================

def _parse_classifier_json(raw: str) -> ClassifierResult:
    """Parse LLM JSON response into a validated ClassifierResult."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    if "{" in raw:
        start = raw.find("{")
        depth = 0
        end = -1
        for i, ch in enumerate(raw[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            raw = raw[start : end + 1]

    data = json.loads(raw)

    intensity = int(data.get("distress_intensity", 0))
    intensity = max(0, min(3, intensity))

    weight = float(data.get("weight", 0.0))
    weight = max(0.0, min(1.0, weight))

    shape = str(data.get("request_shape", "emotional_processing")).lower()
    if shape not in _VALID_SHAPES:
        shape = "emotional_processing"

    raw_domains = data.get("domains_present", [])
    if isinstance(raw_domains, list):
        domains = tuple(d for d in raw_domains if d in _VALID_DOMAINS)
    else:
        domains = ()

    return ClassifierResult(
        distress_intensity=intensity,
        indirect_self_blame=bool(data.get("indirect_self_blame", False)),
        escalation_from_calm=bool(data.get("escalation_from_calm", False)),
        request_shape=shape,
        domains_present=domains,
        weight=weight,
        raw_json=raw,
    )


# ============================================================
# ASYNC LLM CALL
# ============================================================

def _classifier_model() -> str:
    return (
        os.getenv("CLASSIFIER_LLM_MODEL", "").strip()
        or os.getenv("CLASSIFIER_LLM_DEPLOYMENT", "").strip()
        or os.getenv("NATE_CHAT_MODEL", "").strip()
        or "grok-4-1-fast-non-reasoning"
    )


def _classifier_request_config() -> tuple:
    """Return (url, api_key, use_foundry_body). Prefer Foundry URL over legacy deploy path."""
    custom_url = os.getenv("CLASSIFIER_LLM_URL", "").strip()
    if custom_url:
        key = os.getenv("CLASSIFIER_LLM_KEY", "").strip() or os.getenv("NATE_CHAT_KEY", "")
        return custom_url, key, True

    nate_url = os.getenv("NATE_CHAT_URL", "").strip()
    if nate_url:
        key = os.getenv("NATE_CHAT_KEY", "")
        return nate_url, key, True

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_key = os.getenv("AZURE_API_KEY", "")
    if not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"
    url = (
        f"{endpoint}/openai/deployments/{_CLASSIFIER_DEPLOYMENT}"
        f"/chat/completions?api-version=2024-06-01"
    )
    return url, api_key, False


async def _call_classifier_llm(user_msg: str) -> ClassifierResult:
    """Call classifier LLM (Foundry chat URL preferred). Returns parsed result."""
    global _consecutive_failures, _circuit_open_until

    url, api_key, foundry = _classifier_request_config()
    if not url or not api_key:
        return ClassifierResult(error="azure_not_configured")

    headers = {"Content-Type": "application/json", "api-key": api_key}
    def _payload(system_prompt: str) -> Dict[str, object]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]
        if foundry:
            return {
                "model": _classifier_model(),
                "messages": messages,
                "max_completion_tokens": 200,
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            }
        return {
            "messages": messages,
            "max_completion_tokens": 200,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }

    async def _post_once(system_prompt: str):
        import httpx

        async with httpx.AsyncClient(timeout=_timeout_s()) as client:
            return await client.post(url, json=_payload(system_prompt), headers=headers)

    t0 = time.monotonic()
    try:
        resp = await _post_once(_CLASSIFIER_PROMPT_V1)
        latency = (time.monotonic() - t0) * 1000

        if resp.status_code != 200:
            _consecutive_failures += 1
            if _consecutive_failures >= _CIRCUIT_BREAK_FAILURES:
                _circuit_open_until = time.monotonic() + _CIRCUIT_BREAK_COOLDOWN_S
                logger.warning("[CLASSIFIER] circuit OPEN for %.0fs after %d failures",
                               _CIRCUIT_BREAK_COOLDOWN_S, _consecutive_failures)
            return ClassifierResult(
                error=f"http_{resp.status_code}", latency_ms=latency,
            )

        data = resp.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if not content:
            _consecutive_failures += 1
            return ClassifierResult(error="empty_response", latency_ms=latency)

        try:
            result = _parse_classifier_json(content)
        except json.JSONDecodeError:
            retry = await _post_once(f"{_CLASSIFIER_PROMPT_V1}\n\n{_CLASSIFIER_PROMPT_V1_STRICT}")
            latency = (time.monotonic() - t0) * 1000
            if retry.status_code != 200:
                _consecutive_failures += 1
                return ClassifierResult(error=f"http_{retry.status_code}", latency_ms=latency)
            rj = retry.json()
            rcontent = (rj.get("choices") or [{}])[0].get("message", {}).get("content", "")
            if not rcontent:
                _consecutive_failures += 1
                return ClassifierResult(error="empty_response", latency_ms=latency)
            result = _parse_classifier_json(rcontent)

        result = ClassifierResult(
            distress_intensity=result.distress_intensity,
            indirect_self_blame=result.indirect_self_blame,
            escalation_from_calm=result.escalation_from_calm,
            request_shape=result.request_shape,
            domains_present=result.domains_present,
            weight=result.weight,
            raw_json=result.raw_json,
            latency_ms=latency,
        )
        _consecutive_failures = 0
        return result

    except json.JSONDecodeError:
        latency = (time.monotonic() - t0) * 1000
        # Parsing issues are content-shape problems, not transport outages.
        # Do not open the circuit for these; fall back to regex for this turn.
        return ClassifierResult(error="json_parse_failed", latency_ms=latency)
    except ValueError as exc:
        latency = (time.monotonic() - t0) * 1000
        if "Expecting value" in str(exc) or "JSON" in str(exc):
            return ClassifierResult(error="json_parse_failed", latency_ms=latency)
        exc_name = type(exc).__name__
        _consecutive_failures += 1
        if _consecutive_failures >= _CIRCUIT_BREAK_FAILURES:
            _circuit_open_until = time.monotonic() + _CIRCUIT_BREAK_COOLDOWN_S
            logger.warning("[CLASSIFIER] circuit OPEN for %.0fs (%s)",
                           _CIRCUIT_BREAK_COOLDOWN_S, exc_name)
        return ClassifierResult(error=exc_name, latency_ms=latency)
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        exc_name = type(exc).__name__
        _consecutive_failures += 1
        if _consecutive_failures >= _CIRCUIT_BREAK_FAILURES:
            _circuit_open_until = time.monotonic() + _CIRCUIT_BREAK_COOLDOWN_S
            logger.warning("[CLASSIFIER] circuit OPEN for %.0fs (%s)",
                           _CIRCUIT_BREAK_COOLDOWN_S, exc_name)
        if "timeout" in exc_name.lower() or "Timeout" in exc_name:
            return ClassifierResult(error="timeout", latency_ms=latency)
        return ClassifierResult(error=exc_name, latency_ms=latency)


# ============================================================
# PUBLIC API
# ============================================================

async def classify_message(
    user_msg: str,
    user_id: str = "unknown",
) -> ClassifierResult:
    """Run the classifier with all cost gates and failure protections.

    Returns ClassifierResult. On any failure or skip, returns _EMPTY
    (all-zero/false fields) — caller treats it as "no classifier signal."
    """
    global _circuit_open_until

    if len(user_msg.strip()) < _MIN_MSG_LEN:
        return _EMPTY

    if user_id.upper() == "GUEST":
        return _EMPTY

    now = time.monotonic()

    if now < _circuit_open_until:
        logger.debug("[CLASSIFIER] circuit open, skipping")
        return ClassifierResult(error="circuit_open")

    last = _last_call_ts.get(user_id, 0.0)
    if _rate_limit_s() > 0 and now - last < _rate_limit_s():
        return ClassifierResult(error="rate_limited")
    _last_call_ts[user_id] = now

    cache = _get_cache(user_id)
    cache_key = user_msg.strip()[:200]
    if cache_key in cache:
        return cache[cache_key]

    result = await _call_classifier_llm(user_msg)

    if not result.error:
        if len(cache) >= _CACHE_SIZE:
            oldest_key = next(iter(cache))
            del cache[oldest_key]
        cache[cache_key] = result

    logger.info(
        "[CLASSIFIER] user=%s intensity=%d blame=%s shape=%s "
        "domains=%s weight=%.2f latency_ms=%.0f err=%s",
        user_id,
        result.distress_intensity,
        result.indirect_self_blame,
        result.request_shape,
        result.domains_present,
        result.weight,
        result.latency_ms,
        result.error,
    )

    return result


# ============================================================
# ACCUMULATOR MERGE
# ============================================================

_DISTRESS_SCORE_DECAY: float = 0.92


def merge_classifier_into_state(
    result: ClassifierResult,
    state: "SessionState",  # type: ignore[name-defined]
) -> dict:
    """Merge classifier outputs into SessionState accumulators.

    Returns a signals dict with classifier-derived keys (for telemetry /
    disagreement tracking). Does NOT modify mode — that stays in select_mode.

    Decay: distress_score *= 0.92 per turn since last classifier hit.
    """
    signals: dict = {}

    if not hasattr(state, "distress_score"):
        state.distress_score = 0.0
    if not hasattr(state, "_last_classifier_distress_turn"):
        state._last_classifier_distress_turn = 0

    turns_since = max(0, state.turn_count - state._last_classifier_distress_turn)
    if turns_since > 0 and state.distress_score > 0:
        state.distress_score *= _DISTRESS_SCORE_DECAY ** turns_since

    if result.error or (result.distress_intensity == 0 and not result.indirect_self_blame):
        return signals

    if result.distress_intensity >= 2:
        state.distress_hits += 1
        state.distress_score += result.distress_intensity * result.weight
        state._last_classifier_distress_turn = state.turn_count
        signals["classifier_distress"] = True

    if result.indirect_self_blame:
        state.distress_score += 1.0 * result.weight
        state._last_classifier_distress_turn = state.turn_count
        signals["classifier_indirect_blame"] = True

    if result.escalation_from_calm:
        state.consecutive_distress_turns += 1
        signals["classifier_escalation"] = True

    if result.request_shape == "redirect":
        signals["classifier_dissatisfaction"] = True

    if result.request_shape == "action_request":
        signals["classifier_action_request"] = True

    if result.domains_present:
        signals["classifier_domains"] = list(result.domains_present)

    return signals


def compute_classifier_handoff(state: "SessionState") -> bool:  # type: ignore[name-defined]
    """Check if classifier-derived distress_score warrants handoff.

    Returns True if distress_score >= 4.5. This is a logical OR with
    the existing integer-threshold handoff in detect_distress.
    """
    score = getattr(state, "distress_score", 0.0)
    return score >= 4.5


# ============================================================
# DISAGREEMENT TRACKING
# ============================================================

def detect_disagreements(
    classifier_result: ClassifierResult,
    regex_signals: dict,
) -> List[str]:
    """Compare classifier output to regex signals, return disagreement labels.

    Each label describes one axis where the two detectors disagree.
    This feeds shadow-log telemetry so operators can spot drift.
    """
    disagreements: List[str] = []

    if classifier_result.error:
        return disagreements

    regex_distress = regex_signals.get("distress", False)
    cl_distress = classifier_result.distress_intensity >= 2
    if cl_distress and not regex_distress:
        disagreements.append("classifier_sees_distress_regex_missed")
    elif regex_distress and not cl_distress:
        disagreements.append("regex_sees_distress_classifier_missed")

    regex_dissatisfaction = regex_signals.get("dissatisfaction", False)
    cl_dissatisfaction = classifier_result.request_shape == "redirect"
    if cl_dissatisfaction and not regex_dissatisfaction:
        disagreements.append("classifier_sees_dissatisfaction_regex_missed")
    elif regex_dissatisfaction and not cl_dissatisfaction:
        disagreements.append("regex_sees_dissatisfaction_classifier_missed")

    cl_blame = classifier_result.indirect_self_blame
    if cl_blame and not regex_distress:
        disagreements.append("classifier_indirect_blame_regex_silent")

    cl_action = classifier_result.request_shape == "action_request"
    regex_mismatch = regex_signals.get("mismatch", False)
    if cl_action and not regex_mismatch:
        disagreements.append("classifier_action_request_regex_no_mismatch")

    return disagreements
