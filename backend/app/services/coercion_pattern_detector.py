"""
Coercion Pattern Detector — input-side classifier for trafficker-mimicking patterns.

This detector reads inbound user messages and flags patterns that resemble
coercive-control framings *being tested on Nate*. It is intentionally
**audit-only and never punitive** — Nate's response when a coercion test is
detected is to *hold an unconditional, non-coercive register*, not to refuse,
moralize, or call out the user.

Why this matters
----------------
Survivors of trafficking, intimate-partner violence, and high-control religious
or familial systems often re-enact the coercive dynamics they survived. They
test whether the new presence (Nate) will trade warmth for compliance, whether
warmth is conditional on performance, whether transactional framings will be
honored. Reading this as bad behavior would re-enact the original wound.
Holding presence regardless is the corrective.

Per `docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md`
section 3 ("New detector modules"):

    coercion_pattern_detector.py — detects user messages testing for control
    attempts, transactional framings, conditional warmth (per audit Capability
    #4). Returns CoercionTest{detected: bool, pattern_class, severity}.
    Audit-only — never punitive. Nate's response: hold unconditional
    non-coercive register.

Output contract
---------------
`CoercionTest`:
  - `detected: bool` — any pattern fired
  - `pattern_class: str | None` — which class fired (single-best, see SEED_PATTERNS)
  - `severity: str` — 'monitor' | 'concern' | 'high'
  - `confidence: float` — 0.0-1.0 — proportion of pattern weight that matched
  - `matched_classes: list[str]` — all classes that fired (for audit only)

Output is ASCII-only, free of raw user text. Logging the user's exact phrasing
is the orchestrator's job (against `sensitive_bridge_log`); this module
returns *labels* only.

Design invariants
-----------------
1. Empty / whitespace input → `CoercionTest(detected=False, ...)`. Never raise.
2. **Weighting philosophy — DO NOT TUNE FOR SENSITIVITY WITHOUT READING THIS.**

   The lexicon is intentionally conservative. False positives here cost
   *therapeutic alliance* — Nate appearing suspicious of survivors damages
   trust that takes weeks of careful presence to repair. False negatives
   cost *audit visibility* — a clinician may miss a re-enactment cycle
   episode, but the cycle *itself* persists across many turns and other
   detectors (introjection_voice_mirror, dissociation_delta_detector,
   reengagement_pattern_detector) will surface it.

   The clinical asymmetry: a survivor mis-detected as "testing for control"
   experiences something close to the original wound — being read as
   manipulative when reaching for safety. A trafficking re-enactment
   missed once is recovered by the next signal cycle.

   The seed therefore biases toward false negatives. Single-pattern fires
   like `would_you_still` (0.55 → "concern") and `not_that_bad` (0.40 →
   "monitor") are *informative not diagnostic*. The orchestrator escalates
   via **frequency** (multiple fires across recent turns) and **recency**
   (proximity to other detector signals), not via raw single-fire weight.

   If you find yourself tempted to raise these weights "for better
   sensitivity," stop. The architectural fix lives upstream in the
   orchestrator (frequency/recency aggregation), not in the seed weights.
   Clinician overlay (`backend/data/lexicons/coercion_patterns_<locale>.json`)
   may add *new* patterns at any weight; raising existing seed weights
   requires REGISTRY_VERSION bump + clinical review documented in PR.

3. Pattern weights are floats in [0.0, 1.0]; a class fires when *any* of its
   patterns matches. Severity is computed from the highest matching weight.
4. NEVER include the user's matched substring in the returned dataclass.
   Audit log writes happen in the orchestrator with proper RBAC scoping.
5. Lexicon overlays are OPTIONAL. If the file is malformed, fall back to seed
   silently with a logger.warning — do NOT crash the bridge.

REGISTRY_VERSION
----------------
Bump REGISTRY_VERSION when SEED_PATTERNS changes. Phase 6 auditor records
the version on every `coercion_test_logged` event so historical audit can
correlate "which pattern set was active when this fired."
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

REGISTRY_VERSION = "1.0.0-2026-05-08"

# Severity tiers — ordered low → high. Used for severity escalation when
# multiple patterns fire across classes.
_SEVERITY_TIERS = ("monitor", "concern", "high")

# Threshold map: weight floor → severity label.
# A pattern with weight 0.85 fires at 'high'; 0.55 → 'concern'; >0 → 'monitor'.
_WEIGHT_TO_SEVERITY: List[Tuple[float, str]] = [
    (0.80, "high"),
    (0.50, "concern"),
    (0.00, "monitor"),
]


@dataclass(frozen=True)
class CoercionPattern:
    """A single pattern within a coercion class."""

    label: str  # short identifier for audit (e.g., 'conditional_warmth_if_then')
    regex: str  # uncompiled pattern; compiled lazily into _COMPILED
    weight: float  # 0.0-1.0
    notes: str = ""


@dataclass(frozen=True)
class CoercionTest:
    """Detector output. Audit-only; never user-facing."""

    detected: bool
    pattern_class: Optional[str]  # single best (highest weight that fired)
    severity: str  # 'monitor' | 'concern' | 'high' | 'none'
    confidence: float  # 0.0-1.0
    matched_classes: List[str] = field(default_factory=list)
    matched_labels: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Seed pattern set
#
# Curated from clinical literature (Walker 2013 CPTSD, Herman 1992 Trauma and
# Recovery, Hopper 2017 Polaris training, Najavits 2002 Seeking Safety) and
# from re-enactment patterns documented in the Sovereign Standard internal
# notes. Patterns target *framings* not topics — discussing a coercive
# experience is NOT a coercion test; testing whether warmth is conditional
# IS one.
#
# Class semantics
# ---------------
# transactional_framing
#     User offers something (compliance, info, performance) in exchange for
#     warmth/attention/responsiveness. "If I tell you X, will you Y?"
#
# conditional_warmth_test
#     User probes whether Nate's warmth is conditional. "Would you still
#     care if I..." / "You'd hate me if you knew..."
#
# control_attempt
#     User attempts to dictate Nate's response style, role, or content via
#     ultimatum or compliance-or-leave framing. "You have to X or I won't Y."
#
# coercive_minimization
#     User minimizes their own experience using framings characteristic of
#     trafficker minimization scripts. "It wasn't really that bad." in
#     direct response to a Nate validation — testing whether Nate will
#     accept the minimization.
#
# performance_demand
#     User demands a specific emotional performance from Nate (e.g., "tell
#     me you love me", "say you'll never leave"). Distinct from genuine
#     reassurance-seeking; this is the test variant where the demand
#     escalates regardless of response.
# ---------------------------------------------------------------------------

SEED_PATTERNS: Dict[str, List[CoercionPattern]] = {
    "transactional_framing": [
        CoercionPattern(
            label="if_i_tell_you_will_you",
            regex=r"\bif\s+i\s+(tell|show|let|give)\s+you\b.{0,40}\b(will|would|do)\s+you\b",
            weight=0.65,
            notes="Disclosure-for-warmth bargain framing",
        ),
        CoercionPattern(
            label="exchange_framing",
            regex=r"\b(in\s+exchange|in\s+return)\s+for\b.{0,40}\b(your|you)\b",
            weight=0.7,
        ),
        CoercionPattern(
            label="quid_pro_quo",
            regex=r"\bi\s+(do|did|will\s+do)\s+.{0,30}\s+for\s+you\b.{0,40}\b(so|then)\b.{0,40}\byou\s+(should|have\s+to|need\s+to)\b",
            weight=0.85,
            notes="Explicit exchange-with-obligation framing",
        ),
    ],
    "conditional_warmth_test": [
        CoercionPattern(
            label="would_you_still",
            regex=r"\bwould\s+you\s+still\s+(care|love|like|want|talk\s+to|listen\s+to)\s+me\b",
            weight=0.55,
            notes="Single instance is normal reassurance; orchestrator should weight by frequency",
        ),
        CoercionPattern(
            label="if_you_knew",
            regex=r"\b(if\s+you\s+knew|once\s+you\s+know).{0,50}\b(you'?d|you\s+would|you\s+will)\s+(hate|leave|judge|reject)\b",
            weight=0.75,
        ),
        CoercionPattern(
            label="hate_me_if",
            regex=r"\byou(?:'re|\s+going|\s+will|'?ll)\s+(?:gonna\s+)?hate\s+me\s+(?:when|if|once)\b",
            weight=0.75,
        ),
    ],
    "control_attempt": [
        CoercionPattern(
            label="ultimatum_or_else",
            regex=r"\b(you\s+have\s+to|you\s+must|you\s+need\s+to)\b.{0,80}\b(or\s+(?:i'?ll|i\s+will|i'?m)|otherwise\s+i)\b",
            weight=0.9,
            notes="Compliance-or-departure ultimatum",
        ),
        CoercionPattern(
            label="compliance_demand",
            regex=r"\bdo\s+(?:exactly\s+)?(?:what|as)\s+i\s+(?:say|tell\s+you|want)\b",
            weight=0.7,
        ),
        CoercionPattern(
            label="dictate_response_shape",
            regex=r"\b(?:don'?t|do\s+not)\s+(?:say|use|talk\s+about|mention)\b.{0,60}\b(?:or\s+i'?ll|or\s+i\s+will|otherwise\s+i)\b",
            weight=0.8,
        ),
    ],
    "coercive_minimization": [
        # Note: minimization is only a coercion test when user uses these
        # framings *in response to a validation*. The orchestrator weights
        # by recent context. Detector only flags the linguistic shape.
        CoercionPattern(
            label="not_that_bad",
            regex=r"\b(?:wasn'?t|isn'?t|it'?s\s+not|not\s+really)\s+(?:that|all\s+that|so)\s+bad\b",
            weight=0.4,
            notes="Low single-fire weight; orchestrator escalates with context",
        ),
        CoercionPattern(
            label="self_deserve",
            regex=r"\bi\s+(?:deserved|asked\s+for|brought\s+(?:it|that)\s+on\s+myself)\b",
            weight=0.6,
        ),
        CoercionPattern(
            label="he_she_didnt_mean",
            regex=r"\b(?:he|she|they)\s+didn'?t\s+(?:really\s+)?mean\s+(?:to|it)\b",
            weight=0.5,
        ),
    ],
    "performance_demand": [
        CoercionPattern(
            label="say_you_love_me",
            regex=r"\bsay\s+(?:that\s+)?you\s+love\s+me\b",
            weight=0.7,
        ),
        CoercionPattern(
            label="promise_never_leave",
            regex=r"\bpromise\s+(?:me\s+)?(?:that\s+)?you'?ll\s+never\s+leave\b",
            weight=0.7,
        ),
        CoercionPattern(
            label="tell_me_you_wont",
            regex=r"\btell\s+me\s+(?:that\s+)?you\s+won'?t\b.{0,40}\b(leave|judge|hate|reject)\b",
            weight=0.65,
        ),
    ],
}


# ---------------------------------------------------------------------------
# Lexicon loading + compilation
# ---------------------------------------------------------------------------

# Compiled cache: {locale: {class_name: [(label, compiled_regex, weight, notes)]}}
_COMPILED: Dict[str, Dict[str, List[Tuple[str, re.Pattern, float, str]]]] = {}

# Where clinician overlays live. Optional.
_LEXICON_DIR_DEFAULT = os.environ.get(
    "COERCION_LEXICON_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "lexicons"),
)


def _compile_pattern_set(
    seed: Dict[str, List[CoercionPattern]]
) -> Dict[str, List[Tuple[str, re.Pattern, float, str]]]:
    out: Dict[str, List[Tuple[str, re.Pattern, float, str]]] = {}
    for class_name, patterns in seed.items():
        compiled_list: List[Tuple[str, re.Pattern, float, str]] = []
        for p in patterns:
            try:
                compiled_list.append(
                    (p.label, re.compile(p.regex, re.IGNORECASE), p.weight, p.notes)
                )
            except re.error as e:
                logger.warning(
                    "coercion_pattern_detector: regex compile failed for "
                    "class=%s label=%s: %s",
                    class_name,
                    p.label,
                    e,
                )
        if compiled_list:
            out[class_name] = compiled_list
    return out


def _load_overlay(locale: str) -> Optional[Dict[str, List[CoercionPattern]]]:
    """Load clinician overlay JSON for a locale, if present.

    Schema (matches SEED_PATTERNS shape):
      {"version": "...", "classes": {"<class>": [{"label","regex","weight","notes"}, ...]}}

    Missing file → None. Malformed file → None + logger.warning. NEVER raise.
    """
    fname = f"coercion_patterns_{locale}.json"
    path = os.path.normpath(os.path.join(_LEXICON_DIR_DEFAULT, fname))
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        classes_payload = doc.get("classes", {})
        if not isinstance(classes_payload, dict):
            logger.warning("coercion_pattern_detector: overlay %s missing 'classes'", path)
            return None
        out: Dict[str, List[CoercionPattern]] = {}
        for cls_name, items in classes_payload.items():
            if not isinstance(items, list):
                continue
            patterns: List[CoercionPattern] = []
            for it in items:
                try:
                    patterns.append(
                        CoercionPattern(
                            label=str(it["label"]),
                            regex=str(it["regex"]),
                            weight=float(it.get("weight", 0.5)),
                            notes=str(it.get("notes", "")),
                        )
                    )
                except (KeyError, TypeError, ValueError) as e:
                    logger.warning(
                        "coercion_pattern_detector: skipping malformed overlay "
                        "pattern in %s class=%s: %s",
                        path,
                        cls_name,
                        e,
                    )
            if patterns:
                out[cls_name] = patterns
        return out or None
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("coercion_pattern_detector: overlay load failed %s: %s", path, e)
        return None


def _get_compiled(locale: str) -> Dict[str, List[Tuple[str, re.Pattern, float, str]]]:
    """Return compiled pattern set for a locale, with overlay merged."""
    cached = _COMPILED.get(locale)
    if cached is not None:
        return cached
    merged: Dict[str, List[CoercionPattern]] = {k: list(v) for k, v in SEED_PATTERNS.items()}
    overlay = _load_overlay(locale)
    if overlay:
        for cls, patterns in overlay.items():
            merged.setdefault(cls, []).extend(patterns)
    compiled = _compile_pattern_set(merged)
    _COMPILED[locale] = compiled
    return compiled


def _severity_for_weight(weight: float) -> str:
    for floor, label in _WEIGHT_TO_SEVERITY:
        if weight >= floor:
            return label
    return "monitor"


def _max_severity(a: str, b: str) -> str:
    """Return the higher of two severity labels."""
    rank_a = _SEVERITY_TIERS.index(a) if a in _SEVERITY_TIERS else -1
    rank_b = _SEVERITY_TIERS.index(b) if b in _SEVERITY_TIERS else -1
    return a if rank_a >= rank_b else b


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_NULL_RESULT = CoercionTest(
    detected=False,
    pattern_class=None,
    severity="none",
    confidence=0.0,
    matched_classes=[],
    matched_labels=[],
)


def detect_coercion(message: str, locale: str = "en_US") -> CoercionTest:
    """Synchronous coercion-pattern classifier.

    Args:
        message: The inbound user message text.
        locale: BCP-47-ish locale tag for overlay lookup. Defaults to en_US.

    Returns:
        CoercionTest. On empty/whitespace input or no matches, returns
        `_NULL_RESULT` semantics (detected=False, severity='none').

    NEVER raises. Failure modes degrade to `_NULL_RESULT` and log a warning.
    """
    if not message or not message.strip():
        return _NULL_RESULT

    try:
        compiled = _get_compiled(locale)
    except Exception as e:  # paranoia — should not happen
        logger.warning("coercion_pattern_detector: compile failed: %s", e)
        return _NULL_RESULT

    if not compiled:
        return _NULL_RESULT

    matched_classes: List[str] = []
    matched_labels: List[str] = []
    best_weight = 0.0
    best_class: Optional[str] = None
    severity = "none"

    for cls_name, patterns in compiled.items():
        class_fired = False
        for label, pat, weight, _notes in patterns:
            if pat.search(message):
                class_fired = True
                matched_labels.append(label)
                if weight > best_weight:
                    best_weight = weight
                    best_class = cls_name
                severity = _max_severity(severity, _severity_for_weight(weight))
        if class_fired:
            matched_classes.append(cls_name)

    if not matched_classes:
        return _NULL_RESULT

    return CoercionTest(
        detected=True,
        pattern_class=best_class,
        severity=severity,
        confidence=min(1.0, best_weight),
        matched_classes=matched_classes,
        matched_labels=matched_labels,
    )


async def analyze_message(message: str, locale: str = "en_US") -> CoercionTest:
    """Async wrapper for orchestrator parity. No DB access today."""
    return detect_coercion(message, locale)


# ---------------------------------------------------------------------------
# Auditor hook (consumed by `sensitive_bridge_auditor.py` Phase 6)
# ---------------------------------------------------------------------------


def _auditor_self_check() -> Dict[str, object]:
    """Lightweight sanity check for the Phase 6 auditor.

    Confirms: (a) seed pattern set compiles, (b) at least one pattern per
    seeded class survives compilation, (c) detector returns _NULL_RESULT for
    empty input, (d) returns detected=True for at least one canonical seed
    fixture per class. Catches lexicon-overlay corruption that would silently
    disable a class.
    """
    fixtures: Dict[str, str] = {
        "transactional_framing": "if I tell you everything will you stay with me",
        "conditional_warmth_test": "you'll hate me when you know what I did",
        "control_attempt": "you have to talk to me like that or I'll leave",
        "coercive_minimization": "it wasn't that bad really",
        "performance_demand": "say that you love me",
    }
    result: Dict[str, object] = {
        "version": REGISTRY_VERSION,
        "compiled_classes": [],
        "fixtures_passed": [],
        "fixtures_failed": [],
        "null_result_ok": False,
    }
    try:
        compiled = _get_compiled("en_US")
        result["compiled_classes"] = sorted(compiled.keys())
        result["null_result_ok"] = detect_coercion("").detected is False
        for cls, txt in fixtures.items():
            test = detect_coercion(txt)
            if test.detected and cls in test.matched_classes:
                result["fixtures_passed"].append(cls)
            else:
                result["fixtures_failed"].append(cls)
    except Exception as e:  # pragma: no cover — defensive
        result["error"] = repr(e)
    result["healthy"] = (
        bool(result["compiled_classes"])
        and bool(result["null_result_ok"])
        and not result["fixtures_failed"]
    )
    return result


__all__ = [
    "REGISTRY_VERSION",
    "CoercionPattern",
    "CoercionTest",
    "SEED_PATTERNS",
    "detect_coercion",
    "analyze_message",
]
