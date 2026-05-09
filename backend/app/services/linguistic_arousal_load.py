"""Linguistic Arousal Load — clinical-vocabulary saturation detector (Gap 3).

Sensitive Clinical Bridge — Phase 2C.

Why this module exists
----------------------
Clinical vocabulary can re-trigger nervous-system activation even inside a
validating, well-intentioned therapeutic context. A flat keyword count misses
two clinically important cases:

  (a) A **single highly-charged term** ("rape", "buyer", "branded") landing
      without somatic-resource buffering. One such word at high weight in a
      response can spike physiological arousal regardless of surrounding tone.
  (b) **Clinically-legitimate conversation** that uses charged terms
      appropriately and at low cumulative load (e.g. a coach naming what
      happened in plain language during a grounded check-in). Flat counts
      over-trigger here.

Arousal-weighted scoring is the correct algorithm: each term carries a
clinician-authored weight in [0.0, 1.0]; the cumulative score per response is
compared against a per-user (or population-default) threshold; when triggered,
the orchestrator forces a **pre-buffer** (a Somatic Resource sentence) at the
**start** of Nate's planned response. Pre-buffer placement matters because the
nervous system reads early tokens first and sets state from them.

Per Gap S (locale fallback): production lexicon files live in
`backend/data/lexicons/<lexicon_name>_<locale>.json` and follow the chain
``<requested_locale> → <language> → en-US → fail-safe block``. This module ships
**empty** schema-valid stubs (committed) so that:

  1. The loader exercises the real parse path in production from day one (not
     just the missing-file branch).
  2. The auditor can distinguish three operationally-distinct states:
        - LEXICON_OK                       — file present, parses, has patterns
        - LEXICON_EMPTY_AWAITING_AUTHORING — file present, parses, zero patterns
                                             (expected pre-clinician state)
        - LEXICON_MISSING_OR_CORRUPT       — file missing OR unparseable
                                             (alert)
     All three fail-close to ``triggered=False, cumulative_score=0.0`` (no
     pre-buffer forced), but their audit-log signals differ and Phase 6
     auditor uses the distinction to alert vs. confirm-expected-state.
  3. CI version-bump enforcement (mirroring `specialized_resources.py`)
     attaches to the production stub immediately — first hash captured at the
     empty state, any future content bump requires REGISTRY_VERSION + content
     hash bump together, preserving forensic correlation across the 7-year
     audit retention window.

Public contract (Phase 4 orchestrator imports these symbols)
-----------------------------------------------------------
  - REGISTRY_VERSION                       — version string; bump on data change
  - REGISTRY_CONTENT_HASH                  — sha256 of seed + on-disk lexicon bytes
  - assert_version_aligned()               — CI guard
  - ArousalLoad                            — return dataclass
  - LexiconStatus / status code constants  — for orchestrator audit dispatch
  - measure_response_load(...)             — score Nate's planned response
  - measure_user_disclosure_load(...)      — score user's incoming message
  - LEXICON_OK / LEXICON_EMPTY_AWAITING_AUTHORING / LEXICON_MISSING_OR_CORRUPT
  - clear_lexicon_cache()                  — test/restart hook
  - _auditor_self_check()                  — Phase 6 auditor entry

Stem matching
-------------
The plan calls for a Snowball English stemmer. Pulling NLTK in solely for one
limited lexicon is over-weight (NLTK requires runtime data downloads and adds
~50MB to the image). For Phase 2 we implement **prefix-based stem
approximation**: when ``stem=True``, the term matches at a word boundary plus
any English suffix tail (``\\bmolest\\w*\\b`` matches molest, molested,
molester, molesting, molestation). This is conservative — it never under-matches
relative to Snowball for the clinical roots in scope (verb/noun pairs sharing a
common prefix). If a future lexicon entry needs *true* stem normalization
(e.g. irregular forms), Snowball can be added without changing the public API.
The decision is documented in the seed and surfaces in the auditor self-check.

Threshold resolution
--------------------
The measure functions are SYNC and PURE. Per-user threshold lookup
(``users.profile_data->>'arousal_load_threshold'``) requires DB access, which
the orchestrator handles before invoking us. Threshold precedence:

  1. ``threshold_override`` parameter (orchestrator-resolved per-user value)
  2. ``default_threshold`` field in lexicon JSON (if present)
  3. Module constant ``_DEFAULT_THRESHOLD = 1.5`` (last resort)

The ``user_id`` parameter is accepted for audit/log correlation only — it is
NOT used to fetch user state inside this module.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# REGISTRY VERSION CONTRACT
# ---------------------------------------------------------------------------
# Same pattern as specialized_resources.py and the *_detector.py modules.
# Bump REGISTRY_VERSION whenever the seed code, lexicon-file naming, parse
# rules, or scoring algorithm change. The content hash covers (seed-string +
# on-disk lexicon files); CI test enforces alignment.
#
# When a clinician PR edits backend/data/lexicons/clinical_arousal_lexicon_*.json
# or backend/data/lexicons/somatic_resource_prebuffers_*.json, the content hash
# changes; CI requires REGISTRY_VERSION to bump in the same PR.
REGISTRY_VERSION = "1.0.0-2026-05-08"

# ---------------------------------------------------------------------------
# Status codes (orchestrator + auditor consume these)
# ---------------------------------------------------------------------------
LEXICON_OK = "lexicon_ok"
LEXICON_EMPTY_AWAITING_AUTHORING = "lexicon_empty_awaiting_authoring"
LEXICON_MISSING_OR_CORRUPT = "lexicon_missing_or_corrupt"

_STATUS_CODES = frozenset(
    {LEXICON_OK, LEXICON_EMPTY_AWAITING_AUTHORING, LEXICON_MISSING_OR_CORRUPT}
)

# ---------------------------------------------------------------------------
# Defaults / constants
# ---------------------------------------------------------------------------
_DEFAULT_THRESHOLD = 1.5
_DEFAULT_LOCALE = "en-US"
_FAILSAFE_LOCALES: Tuple[str, ...] = ("en-US",)  # absolute floor of fallback chain

# Lexicon file locations (production stubs committed; loader fails closed if absent).
_REPO_ROOT = Path(__file__).resolve().parents[3]  # backend/app/services -> repo root
_LEXICON_DIR = _REPO_ROOT / "backend" / "data" / "lexicons"

_AROUSAL_FILENAME_TMPL = "clinical_arousal_lexicon_{locale}.json"
_PREBUFFER_FILENAME_TMPL = "somatic_resource_prebuffers_{locale}.json"

# Files included in REGISTRY_CONTENT_HASH (the production stubs in en-US baseline).
# Other locale overlays added later will need to be appended here AND bump
# REGISTRY_VERSION, mirroring the Gap 5 / Gap 9 convention.
_HASHED_FILES: Tuple[Path, ...] = (
    _LEXICON_DIR / _AROUSAL_FILENAME_TMPL.format(locale=_DEFAULT_LOCALE),
    _LEXICON_DIR / _PREBUFFER_FILENAME_TMPL.format(locale=_DEFAULT_LOCALE),
)

# Seed string contributing to the content hash. Captures algorithm/schema
# decisions baked into this module so non-data drift also forces a version bump.
_SEED_FOR_HASH = (
    "linguistic_arousal_load.v1.0.0"
    "|schema=patterns_flat_with_domain_field"
    "|stem_strategy=prefix_word_boundary"
    "|threshold_default=1.5"
    "|status_codes=ok,empty_awaiting,missing_or_corrupt"
    "|locale_fallback=requested_then_language_then_en-US"
)


# ---------------------------------------------------------------------------
# REGISTRY_CONTENT_HASH (HARDCODED LITERAL — DO NOT WRAP IN compute_*())
# ---------------------------------------------------------------------------
# Pinned hex literal of the LAST AUTHORIZED state (seed string + on-disk
# lexicon bytes). Changing the lexicon files OR the seed string above without
# also updating this literal in the same PR will cause `assert_version_aligned`
# (and the CI version-lock test) to fail.
#
# This MUST be a literal — wrapping it in `compute_content_hash()` at import
# time would make the pinned value always equal the live value, defeating the
# tamper-detection. (We caught this exact bug during 2C smoke testing.)
#
# To rotate after an authorized clinician PR:
#   python -c "from backend.app.services.linguistic_arousal_load import \
#              compute_content_hash; print(compute_content_hash())"
# Then bump REGISTRY_VERSION above + paste the new digest below in the SAME PR.
REGISTRY_CONTENT_HASH = (
    "2d8439ca371d8b506243f27b580bafd9"
    "f7ba5571f262165b21bc2dd206c448b4"
)


def compute_content_hash() -> str:
    """SHA256 over the seed string and bytes of every hashed lexicon file.

    Missing files contribute the literal token ``MISSING:<path>`` so a deletion
    is itself a content change (forces REGISTRY_VERSION bump on rollback PRs).
    Stable across platforms (no file metadata, just bytes + sorted path order).
    """
    h = hashlib.sha256()
    h.update(_SEED_FOR_HASH.encode("utf-8"))
    for path in _HASHED_FILES:
        h.update(b"\n--FILE--\n")
        h.update(str(path.relative_to(_REPO_ROOT)).encode("utf-8"))
        h.update(b"\n")
        try:
            h.update(path.read_bytes())
        except FileNotFoundError:
            h.update(f"MISSING:{path.name}".encode("utf-8"))
        except OSError as e:
            h.update(f"ERROR:{path.name}:{e.__class__.__name__}".encode("utf-8"))
    return h.hexdigest()


def assert_version_aligned() -> None:
    """Raise AssertionError if the on-disk hash drifted from REGISTRY_CONTENT_HASH.

    The CI pytest in ``backend/tests/test_specialized_resources_version_lock.py``
    pattern is mirrored for this module (see
    ``test_linguistic_arousal_load_version_lock.py``). Failure means a PR
    edited a hashed lexicon file without bumping REGISTRY_VERSION and
    REGISTRY_CONTENT_HASH together.
    """
    actual = compute_content_hash()
    if actual != REGISTRY_CONTENT_HASH:
        raise AssertionError(
            f"linguistic_arousal_load: content hash drift detected.\n"
            f"  REGISTRY_VERSION       = {REGISTRY_VERSION}\n"
            f"  REGISTRY_CONTENT_HASH  = {REGISTRY_CONTENT_HASH}\n"
            f"  actual_hash            = {actual}\n"
            "If you edited a hashed lexicon file, bump both REGISTRY_VERSION "
            "and REGISTRY_CONTENT_HASH (recompute via "
            "`python -c 'from backend.app.services.linguistic_arousal_load "
            "import compute_content_hash; print(compute_content_hash())'`) "
            "in the same PR."
        )


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LexiconPattern:
    """One clinician-authored pattern entry."""

    term: str
    weight: float
    domain: str
    stem: bool


@dataclass(frozen=True)
class LexiconStatus:
    """Loader outcome for one (lexicon, locale) pair.

    The orchestrator dispatches different audit events based on ``status_code``;
    Phase 6 auditor uses the distinction to separate expected-empty-pre-clinician
    state (info) from missing/corrupt state (alert).
    """

    file_path: str  # absolute path attempted (for audit trail)
    file_present: bool
    parse_ok: bool
    pattern_count: int
    status_code: str  # one of _STATUS_CODES
    message: str  # human-readable detail (for audit log payload)
    locale_used: str  # locale actually loaded (after fallback chain resolution)
    requested_locale: str  # what the caller asked for


@dataclass(frozen=True)
class ArousalLoad:
    """Return type for measure_*() functions.

    ``triggering_terms`` contains LEXICON ENTRIES THAT MATCHED — never the
    surrounding user-text. Safe to include in audit_log payloads (lexicon data,
    not user data). Capped at 25 entries to prevent log inflation on
    pathologically dense inputs.
    """

    cumulative_score: float
    threshold: float
    triggered: bool
    triggering_terms: List[Tuple[str, float]]  # (matched_term, weight) — capped
    recommended_buffer: Optional[str]  # somatic resource pre-buffer text, if any
    lexicon_status: LexiconStatus
    domain: str
    locale_used: str
    # Diagnostic fields:
    distinct_match_count: int  # how many unique terms hit (pre-cap)
    total_match_events: int  # how many fires across the text (with repeats)


_TRIGGERING_TERMS_CAP = 25  # audit-log inflation guard


# ---------------------------------------------------------------------------
# Lexicon loader (mtime-keyed cache)
# ---------------------------------------------------------------------------
@dataclass
class _CacheEntry:
    patterns: List[LexiconPattern]
    file_default_threshold: Optional[float]
    status: LexiconStatus
    mtime: Optional[float]  # None if file missing
    compiled_regex_by_domain: Dict[str, "re.Pattern[str]"]
    weight_by_term_lower: Dict[str, Tuple[float, str]]  # term_lower -> (weight, domain)
    stem_terms_lower: List[Tuple[str, float, str]]  # (root_lower, weight, domain)


_CACHE_LOCK = threading.RLock()
_LEXICON_CACHE: Dict[str, _CacheEntry] = {}  # key: absolute path string
_PREBUFFER_CACHE: Dict[str, Tuple[Optional[float], Dict[Tuple[str, str], str]]] = {}


def clear_lexicon_cache() -> None:
    """Drop all cached lexicon and prebuffer state. Hot-path test/restart hook."""
    with _CACHE_LOCK:
        _LEXICON_CACHE.clear()
        _PREBUFFER_CACHE.clear()


def _locale_chain(requested: str) -> List[str]:
    """Apply Gap S locale fallback: requested -> language -> en-US.

    Examples:
      "fr-FR" -> ["fr-FR", "fr", "en-US"]
      "en-GB" -> ["en-GB", "en", "en-US"]
      "en-US" -> ["en-US"]                    (already at floor; no duplicate)
      "es"    -> ["es", "en-US"]
    """
    seen: List[str] = []

    def _add(loc: str) -> None:
        if loc and loc not in seen:
            seen.append(loc)

    _add(requested)
    if "-" in requested:
        _add(requested.split("-", 1)[0])
    for failsafe in _FAILSAFE_LOCALES:
        _add(failsafe)
    return seen


def _load_arousal_lexicon(locale: str) -> _CacheEntry:
    """Load the clinical arousal lexicon for ``locale``, applying fallback.

    Returns a `_CacheEntry`; on missing/corrupt, returns an entry whose
    ``status.status_code`` indicates the failure mode and whose ``patterns``
    list is empty. NEVER raises; the failure mode IS the return value.
    """
    chain = _locale_chain(locale)
    last_status: Optional[LexiconStatus] = None
    for candidate in chain:
        path = _LEXICON_DIR / _AROUSAL_FILENAME_TMPL.format(locale=candidate)
        path_str = str(path)
        with _CACHE_LOCK:
            cached = _LEXICON_CACHE.get(path_str)
        try:
            current_mtime = path.stat().st_mtime if path.exists() else None
        except OSError:
            current_mtime = None
        if cached and cached.mtime == current_mtime and cached.status.status_code != LEXICON_MISSING_OR_CORRUPT:
            # Cache hit, still valid; only return if it represents a healthy/empty file
            # (we keep iterating fallback for missing/corrupt cases)
            return cached

        # File-level load
        if not path.exists():
            last_status = LexiconStatus(
                file_path=path_str,
                file_present=False,
                parse_ok=False,
                pattern_count=0,
                status_code=LEXICON_MISSING_OR_CORRUPT,
                message=f"lexicon file missing for locale '{candidate}'",
                locale_used=candidate,
                requested_locale=locale,
            )
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as e:
            entry = _CacheEntry(
                patterns=[],
                file_default_threshold=None,
                status=LexiconStatus(
                    file_path=path_str,
                    file_present=True,
                    parse_ok=False,
                    pattern_count=0,
                    status_code=LEXICON_MISSING_OR_CORRUPT,
                    message=f"parse failed: {e.__class__.__name__}: {e}",
                    locale_used=candidate,
                    requested_locale=locale,
                ),
                mtime=current_mtime,
                compiled_regex_by_domain={},
                weight_by_term_lower={},
                stem_terms_lower=[],
            )
            with _CACHE_LOCK:
                _LEXICON_CACHE[path_str] = entry
            return entry

        patterns_raw = data.get("patterns")
        if not isinstance(patterns_raw, list):
            entry = _CacheEntry(
                patterns=[],
                file_default_threshold=None,
                status=LexiconStatus(
                    file_path=path_str,
                    file_present=True,
                    parse_ok=False,
                    pattern_count=0,
                    status_code=LEXICON_MISSING_OR_CORRUPT,
                    message="schema invalid: 'patterns' field missing or not a list",
                    locale_used=candidate,
                    requested_locale=locale,
                ),
                mtime=current_mtime,
                compiled_regex_by_domain={},
                weight_by_term_lower={},
                stem_terms_lower=[],
            )
            with _CACHE_LOCK:
                _LEXICON_CACHE[path_str] = entry
            return entry

        # Schema-valid file (may still be empty)
        compiled_patterns: List[LexiconPattern] = []
        invalid: List[str] = []
        for idx, raw_p in enumerate(patterns_raw):
            try:
                term = str(raw_p["term"]).strip()
                weight = float(raw_p["weight"])
                domain = str(raw_p["domain"]).strip()
                stem = bool(raw_p.get("stem", False))
            except (KeyError, TypeError, ValueError) as e:
                invalid.append(f"pattern[{idx}]: {e.__class__.__name__}")
                continue
            if not term or not domain:
                invalid.append(f"pattern[{idx}]: empty term or domain")
                continue
            if not (0.0 <= weight <= 1.0):
                invalid.append(f"pattern[{idx}]: weight {weight} out of [0.0, 1.0]")
                continue
            compiled_patterns.append(
                LexiconPattern(term=term, weight=weight, domain=domain, stem=stem)
            )

        if invalid:
            # Schema-level validation failure: treat as corrupt; do NOT silently load partial.
            entry = _CacheEntry(
                patterns=[],
                file_default_threshold=None,
                status=LexiconStatus(
                    file_path=path_str,
                    file_present=True,
                    parse_ok=False,
                    pattern_count=0,
                    status_code=LEXICON_MISSING_OR_CORRUPT,
                    message=f"{len(invalid)} invalid pattern entries (first: {invalid[0]})",
                    locale_used=candidate,
                    requested_locale=locale,
                ),
                mtime=current_mtime,
                compiled_regex_by_domain={},
                weight_by_term_lower={},
                stem_terms_lower=[],
            )
            with _CACHE_LOCK:
                _LEXICON_CACHE[path_str] = entry
            return entry

        # Optional default_threshold
        file_default = data.get("default_threshold")
        if file_default is not None:
            try:
                file_default = float(file_default)
                if file_default <= 0:
                    file_default = None
            except (TypeError, ValueError):
                file_default = None

        # Build matchers
        compiled_regex_by_domain, weight_by_term_lower, stem_terms_lower = (
            _build_matchers(compiled_patterns)
        )

        if not compiled_patterns:
            status_code = LEXICON_EMPTY_AWAITING_AUTHORING
            message = (
                "schema-valid empty stub — awaiting clinician authoring per Gap D"
            )
        else:
            status_code = LEXICON_OK
            message = f"loaded {len(compiled_patterns)} patterns"

        entry = _CacheEntry(
            patterns=compiled_patterns,
            file_default_threshold=file_default,
            status=LexiconStatus(
                file_path=path_str,
                file_present=True,
                parse_ok=True,
                pattern_count=len(compiled_patterns),
                status_code=status_code,
                message=message,
                locale_used=candidate,
                requested_locale=locale,
            ),
            mtime=current_mtime,
            compiled_regex_by_domain=compiled_regex_by_domain,
            weight_by_term_lower=weight_by_term_lower,
            stem_terms_lower=stem_terms_lower,
        )
        with _CACHE_LOCK:
            _LEXICON_CACHE[path_str] = entry
        return entry

    # Fallback chain exhausted with no usable file (every candidate missing).
    if last_status is None:
        last_status = LexiconStatus(
            file_path="",
            file_present=False,
            parse_ok=False,
            pattern_count=0,
            status_code=LEXICON_MISSING_OR_CORRUPT,
            message="locale chain produced no candidates",
            locale_used=locale,
            requested_locale=locale,
        )
    return _CacheEntry(
        patterns=[],
        file_default_threshold=None,
        status=last_status,
        mtime=None,
        compiled_regex_by_domain={},
        weight_by_term_lower={},
        stem_terms_lower=[],
    )


def _build_matchers(
    patterns: List[LexiconPattern],
) -> Tuple[
    Dict[str, "re.Pattern[str]"],
    Dict[str, Tuple[float, str]],
    List[Tuple[str, float, str]],
]:
    """Compile per-domain alternation regexes for fast scanning.

    For each domain we build:
      * one combined regex of literal-match terms (stem=False), word-boundary
      * one combined regex of stem-prefix terms (stem=True), suffix-tolerant

    We also build a flat (term_lower -> (weight, domain)) lookup for literal
    hits so the scoring loop can resolve weight by the matched substring.
    For stem entries we keep an explicit list because the matched substring
    differs from the lexicon root (e.g. "molested" matched by root "molest").
    """
    literal_terms_by_domain: Dict[str, List[str]] = {}
    stem_terms_by_domain: Dict[str, List[str]] = {}
    weight_by_term_lower: Dict[str, Tuple[float, str]] = {}
    stem_terms_lower: List[Tuple[str, float, str]] = []

    for p in patterns:
        term_lower = p.term.lower()
        if p.stem:
            stem_terms_by_domain.setdefault(p.domain, []).append(term_lower)
            stem_terms_lower.append((term_lower, p.weight, p.domain))
        else:
            literal_terms_by_domain.setdefault(p.domain, []).append(term_lower)
            # Last write wins on duplicates within a domain; flag dup at load time
            # is a clinician-review concern handled via lexicon REGISTRY_VERSION review.
            weight_by_term_lower[term_lower] = (p.weight, p.domain)

    compiled: Dict[str, "re.Pattern[str]"] = {}
    for domain in set(list(literal_terms_by_domain.keys()) + list(stem_terms_by_domain.keys())):
        parts: List[str] = []
        # Literal: word-boundary on both sides, escape special chars, match phrases too
        lits = literal_terms_by_domain.get(domain, [])
        if lits:
            # Sort by length desc so longer phrases match before shorter prefixes
            lits_sorted = sorted(lits, key=len, reverse=True)
            esc = "|".join(re.escape(t) for t in lits_sorted)
            parts.append(rf"(?:(?<![\w])(?:{esc})(?![\w]))")
        # Stem: word-boundary start, suffix tolerance, ASCII word chars
        stems = stem_terms_by_domain.get(domain, [])
        if stems:
            stems_sorted = sorted(stems, key=len, reverse=True)
            esc = "|".join(re.escape(t) for t in stems_sorted)
            parts.append(rf"(?:\b(?:{esc})\w*)")
        if parts:
            compiled[domain] = re.compile("|".join(parts), re.IGNORECASE)

    return compiled, weight_by_term_lower, stem_terms_lower


def _load_prebuffers(locale: str) -> Tuple[Optional[float], Dict[Tuple[str, str], str]]:
    """Load somatic-resource prebuffer text. Returns (mtime, {(domain, register): text}).

    Empty/missing/corrupt all yield empty dict; orchestrator falls back to
    register-level default with no prepended buffer (still emits audit event).
    """
    chain = _locale_chain(locale)
    for candidate in chain:
        path = _LEXICON_DIR / _PREBUFFER_FILENAME_TMPL.format(locale=candidate)
        path_str = str(path)
        try:
            current_mtime = path.stat().st_mtime if path.exists() else None
        except OSError:
            current_mtime = None
        with _CACHE_LOCK:
            cached = _PREBUFFER_CACHE.get(path_str)
        if cached is not None and cached[0] == current_mtime and cached[1]:
            return cached
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            buffers_raw = data.get("buffers")
            if not isinstance(buffers_raw, list):
                with _CACHE_LOCK:
                    _PREBUFFER_CACHE[path_str] = (current_mtime, {})
                continue
            mapping: Dict[Tuple[str, str], str] = {}
            for raw_b in buffers_raw:
                try:
                    domain = str(raw_b["domain"]).strip()
                    register = str(raw_b["register"]).strip()
                    text = str(raw_b["text"]).strip()
                except (KeyError, TypeError, ValueError):
                    continue
                if domain and register and text:
                    mapping[(domain, register)] = text
            with _CACHE_LOCK:
                _PREBUFFER_CACHE[path_str] = (current_mtime, mapping)
            if mapping:
                return current_mtime, mapping
            # Empty prebuffers — keep iterating fallback (next-language overlay may have content)
            continue
        except (OSError, json.JSONDecodeError):
            with _CACHE_LOCK:
                _PREBUFFER_CACHE[path_str] = (current_mtime, {})
            continue
    return None, {}


def _resolve_prebuffer(
    domain: str, register: str, prebuffers: Dict[Tuple[str, str], str]
) -> Optional[str]:
    """Look up (domain, register) -> register='default' -> None."""
    if (domain, register) in prebuffers:
        return prebuffers[(domain, register)]
    if (domain, "default") in prebuffers:
        return prebuffers[(domain, "default")]
    return None


# ---------------------------------------------------------------------------
# Scoring core
# ---------------------------------------------------------------------------
def _score_text(
    text: str,
    domain: str,
    cache_entry: _CacheEntry,
) -> Tuple[float, List[Tuple[str, float]], int, int]:
    """Score ``text`` against patterns scoped to ``domain``.

    Returns (cumulative_score, triggering_terms_capped, distinct_match_count,
    total_match_events).
    """
    if not text or not domain:
        return 0.0, [], 0, 0
    pattern = cache_entry.compiled_regex_by_domain.get(domain)
    if pattern is None:
        return 0.0, [], 0, 0

    cumulative = 0.0
    distinct_terms_seen: Dict[str, float] = {}  # matched_lower -> weight
    total_events = 0

    for match in pattern.finditer(text):
        matched = match.group(0).lower()
        total_events += 1
        # Resolve weight: literal hit -> direct lookup; stem hit -> match by root prefix
        weight: Optional[float] = None
        lit = cache_entry.weight_by_term_lower.get(matched)
        if lit is not None and lit[1] == domain:
            weight = lit[0]
        else:
            # Stem resolution: find longest root that ``matched`` starts with
            best_root_len = -1
            best_weight = None
            for root, w, d in cache_entry.stem_terms_lower:
                if d != domain:
                    continue
                if matched.startswith(root) and len(root) > best_root_len:
                    best_root_len = len(root)
                    best_weight = w
            weight = best_weight

        if weight is None:
            continue
        cumulative += weight
        # Track distinct hits with their first-seen weight (for audit log)
        if matched not in distinct_terms_seen:
            distinct_terms_seen[matched] = weight

    distinct_count = len(distinct_terms_seen)
    triggering = sorted(distinct_terms_seen.items(), key=lambda kv: kv[1], reverse=True)
    triggering_capped = triggering[:_TRIGGERING_TERMS_CAP]
    return cumulative, triggering_capped, distinct_count, total_events


def _resolve_threshold(
    threshold_override: Optional[float],
    cache_entry: _CacheEntry,
) -> float:
    """Threshold precedence: explicit override > file default > module default."""
    if threshold_override is not None:
        try:
            override = float(threshold_override)
            if override > 0:
                return override
        except (TypeError, ValueError):
            pass
    if cache_entry.file_default_threshold is not None:
        return cache_entry.file_default_threshold
    return _DEFAULT_THRESHOLD


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def measure_response_load(
    planned_response: str,
    user_id: str,
    domain: str,
    register: str = "default",
    locale: str = _DEFAULT_LOCALE,
    threshold_override: Optional[float] = None,
) -> ArousalLoad:
    """Score Nate's planned response and recommend a pre-buffer if triggered.

    Args:
        planned_response: Text Nate is about to send. Scored as-written.
        user_id: For audit-log correlation only; NOT used to fetch user state.
        domain: Lexicon domain to score against (e.g. "sexual_trauma",
            "trafficking_trauma"). Patterns from other domains are ignored.
        register: Active therapeutic register (e.g. "default",
            "predictability_continuity"). Selects which prebuffer text to
            recommend if triggered.
        locale: BCP-47 locale; loader applies Gap S fallback chain.
        threshold_override: Per-user threshold resolved by orchestrator from
            ``users.profile_data->>'arousal_load_threshold'``. Wins over
            file/module defaults.

    Returns:
        ArousalLoad with scoring outcome and recommended buffer (if triggered).
    """
    return _measure(
        text=planned_response,
        user_id=user_id,
        domain=domain,
        register=register,
        locale=locale,
        threshold_override=threshold_override,
    )


def measure_user_disclosure_load(
    message: str,
    user_id: str,
    domain: str,
    register: str = "default",
    locale: str = _DEFAULT_LOCALE,
    threshold_override: Optional[float] = None,
) -> ArousalLoad:
    """Score the USER's incoming message (not Nate's planned response).

    Use case: orchestrator estimates incoming activation level to inform
    register selection BEFORE composing a response. Same algorithm; identical
    return shape; ``recommended_buffer`` is still populated (it would be
    pre-pended to Nate's response).
    """
    return _measure(
        text=message,
        user_id=user_id,
        domain=domain,
        register=register,
        locale=locale,
        threshold_override=threshold_override,
    )


def _measure(
    text: str,
    user_id: str,
    domain: str,
    register: str,
    locale: str,
    threshold_override: Optional[float],
) -> ArousalLoad:
    cache_entry = _load_arousal_lexicon(locale)
    threshold = _resolve_threshold(threshold_override, cache_entry)

    # Fail-closed: any non-OK lexicon status produces zero score, no trigger.
    # Status code differentiation lets the orchestrator distinguish expected-empty
    # state from missing/corrupt state in the audit log.
    if cache_entry.status.status_code != LEXICON_OK:
        # Touch user_id to silence linter while preserving the param for future use
        _ = user_id
        return ArousalLoad(
            cumulative_score=0.0,
            threshold=threshold,
            triggered=False,
            triggering_terms=[],
            recommended_buffer=None,
            lexicon_status=cache_entry.status,
            domain=domain,
            locale_used=cache_entry.status.locale_used,
            distinct_match_count=0,
            total_match_events=0,
        )

    cumulative, triggering, distinct, total = _score_text(text, domain, cache_entry)
    triggered = cumulative >= threshold
    recommended_buffer: Optional[str] = None
    if triggered:
        _, prebuffers = _load_prebuffers(locale)
        recommended_buffer = _resolve_prebuffer(domain, register, prebuffers)

    return ArousalLoad(
        cumulative_score=round(cumulative, 4),
        threshold=threshold,
        triggered=triggered,
        triggering_terms=triggering,
        recommended_buffer=recommended_buffer,
        lexicon_status=cache_entry.status,
        domain=domain,
        locale_used=cache_entry.status.locale_used,
        distinct_match_count=distinct,
        total_match_events=total,
    )


# ---------------------------------------------------------------------------
# Auditor entry point (Phase 6 will call this)
# ---------------------------------------------------------------------------
def _auditor_self_check() -> Dict[str, Any]:
    """Confirm production stubs load, fail-closed semantics intact, version aligned.

    Phase 6 ``sensitive_bridge_auditor.py`` invokes this and treats:
      - status='ok'    -> module healthy
      - status='warn'  -> non-fatal regression (e.g. version misaligned)
      - status='fail'  -> blocker for trust score

    Returns a dict with status + per-check diagnostics.
    """
    diagnostics: Dict[str, Any] = {
        "module": "linguistic_arousal_load",
        "registry_version": REGISTRY_VERSION,
        "registry_content_hash": REGISTRY_CONTENT_HASH,
        "checks": {},
    }

    # 1. Version-hash alignment
    try:
        assert_version_aligned()
        diagnostics["checks"]["version_aligned"] = {"status": "ok"}
    except AssertionError as e:
        diagnostics["checks"]["version_aligned"] = {"status": "fail", "error": str(e)}

    # 2. Production stubs load and are recognised as empty-awaiting-authoring
    clear_lexicon_cache()
    entry = _load_arousal_lexicon(_DEFAULT_LOCALE)
    if entry.status.status_code == LEXICON_EMPTY_AWAITING_AUTHORING:
        diagnostics["checks"]["en_us_stub_loads_as_empty_awaiting"] = {
            "status": "ok",
            "file_path": entry.status.file_path,
            "message": entry.status.message,
        }
    else:
        diagnostics["checks"]["en_us_stub_loads_as_empty_awaiting"] = {
            "status": "fail",
            "expected_status_code": LEXICON_EMPTY_AWAITING_AUTHORING,
            "actual_status_code": entry.status.status_code,
            "message": entry.status.message,
            "file_path": entry.status.file_path,
        }

    # 3. Empty lexicon yields fail-closed score
    fail_closed = measure_response_load(
        planned_response="rape molestation buyer trick branded penetration",
        user_id="audit_synthetic_user",
        domain="trafficking_trauma",
        locale=_DEFAULT_LOCALE,
    )
    if (
        fail_closed.cumulative_score == 0.0
        and not fail_closed.triggered
        and fail_closed.recommended_buffer is None
        and fail_closed.lexicon_status.status_code == LEXICON_EMPTY_AWAITING_AUTHORING
    ):
        diagnostics["checks"]["empty_lexicon_fails_closed"] = {"status": "ok"}
    else:
        diagnostics["checks"]["empty_lexicon_fails_closed"] = {
            "status": "fail",
            "cumulative_score": fail_closed.cumulative_score,
            "triggered": fail_closed.triggered,
            "recommended_buffer": fail_closed.recommended_buffer,
            "lexicon_status_code": fail_closed.lexicon_status.status_code,
        }

    # 4. Missing-file path produces LEXICON_MISSING_OR_CORRUPT (synthetic locale)
    clear_lexicon_cache()
    missing_entry = _load_arousal_lexicon("zz-XX")  # absent locale; chain falls to en-US
    # zz-XX -> zz -> en-US; the en-US stub IS present, so chain returns empty-awaiting.
    # Truly-missing test requires a synthetic locale whose chain has no on-disk file.
    # We test the missing branch via direct path inspection:
    missing_path = _LEXICON_DIR / _AROUSAL_FILENAME_TMPL.format(locale="zz-XX")
    if not missing_path.exists():
        diagnostics["checks"]["missing_locale_file_does_not_exist"] = {"status": "ok"}
    else:
        diagnostics["checks"]["missing_locale_file_does_not_exist"] = {
            "status": "warn",
            "message": "zz-XX path unexpectedly exists; cannot verify missing branch",
        }
    # Verify fallback to en-US succeeded
    if missing_entry.status.status_code in (
        LEXICON_EMPTY_AWAITING_AUTHORING,
        LEXICON_OK,
    ) and missing_entry.status.locale_used == _DEFAULT_LOCALE:
        diagnostics["checks"]["locale_fallback_to_en_us"] = {
            "status": "ok",
            "locale_used": missing_entry.status.locale_used,
        }
    else:
        diagnostics["checks"]["locale_fallback_to_en_us"] = {
            "status": "fail",
            "locale_used": missing_entry.status.locale_used,
            "status_code": missing_entry.status.status_code,
        }

    # 5. Test fixture loads + scoring works end-to-end
    fixture_status = _check_fixture_scoring(diagnostics)
    diagnostics["checks"]["fixture_scoring_end_to_end"] = fixture_status

    # 6. Status code constants are non-overlapping
    if len(_STATUS_CODES) == 3:
        diagnostics["checks"]["status_codes_distinct"] = {"status": "ok"}
    else:
        diagnostics["checks"]["status_codes_distinct"] = {
            "status": "fail",
            "count": len(_STATUS_CODES),
        }

    # 7. Default threshold sanity
    if _DEFAULT_THRESHOLD > 0:
        diagnostics["checks"]["default_threshold_positive"] = {
            "status": "ok",
            "value": _DEFAULT_THRESHOLD,
        }
    else:
        diagnostics["checks"]["default_threshold_positive"] = {"status": "fail"}

    # Aggregate
    statuses = [c["status"] for c in diagnostics["checks"].values()]
    if any(s == "fail" for s in statuses):
        diagnostics["status"] = "fail"
    elif any(s == "warn" for s in statuses):
        diagnostics["status"] = "warn"
    else:
        diagnostics["status"] = "ok"
    return diagnostics


def _check_fixture_scoring(diagnostics: Dict[str, Any]) -> Dict[str, Any]:
    """Run the test fixture through the full scoring path. Pure-Python, no DB."""
    fixture_path = (
        _REPO_ROOT
        / "backend"
        / "tests"
        / "fixtures"
        / "clinical_arousal_lexicon_test.json"
    )
    if not fixture_path.exists():
        return {
            "status": "warn",
            "message": f"fixture not present at {fixture_path}",
        }
    try:
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"status": "fail", "error": f"fixture parse failed: {e}"}

    # Build a synthetic cache entry from the fixture (do not pollute the real cache)
    patterns_raw = data.get("patterns", [])
    patterns: List[LexiconPattern] = []
    for raw_p in patterns_raw:
        try:
            patterns.append(
                LexiconPattern(
                    term=str(raw_p["term"]),
                    weight=float(raw_p["weight"]),
                    domain=str(raw_p["domain"]),
                    stem=bool(raw_p.get("stem", False)),
                )
            )
        except (KeyError, TypeError, ValueError):
            return {"status": "fail", "error": "fixture pattern shape invalid"}
    if not patterns:
        return {"status": "fail", "error": "fixture has no patterns"}

    compiled_regex, weight_by_term, stem_terms = _build_matchers(patterns)
    fixture_entry = _CacheEntry(
        patterns=patterns,
        file_default_threshold=float(data.get("default_threshold", 1.0)),
        status=LexiconStatus(
            file_path=str(fixture_path),
            file_present=True,
            parse_ok=True,
            pattern_count=len(patterns),
            status_code=LEXICON_OK,
            message="fixture loaded",
            locale_used="en-US",
            requested_locale="en-US",
        ),
        mtime=fixture_path.stat().st_mtime,
        compiled_regex_by_domain=compiled_regex,
        weight_by_term_lower=weight_by_term,
        stem_terms_lower=stem_terms,
    )

    # Score: literal alpha (0.6) + literal beta (0.9) = 1.5, threshold 1.0 -> triggered
    test_text = "synthetic_marker_alpha appears, then synthetic_marker_beta arrives."
    score, triggering, distinct, total = _score_text(test_text, "fixture_domain_a", fixture_entry)
    expected_min = 1.4  # allow rounding wiggle
    if score < expected_min:
        diagnostics["fixture_score_observed"] = score
        return {
            "status": "fail",
            "expected_min_score": expected_min,
            "observed_score": score,
            "distinct_match_count": distinct,
            "total_match_events": total,
        }

    # Stem: "syntheticstems" (with -s) should match root "syntheticstem"
    stem_text = "the syntheticstems abound here."
    s_score, _, s_distinct, s_total = _score_text(stem_text, "fixture_domain_b", fixture_entry)
    if s_score < 0.4:
        return {
            "status": "fail",
            "stem_match_failed": True,
            "stem_score": s_score,
            "stem_distinct": s_distinct,
            "stem_total": s_total,
        }

    return {
        "status": "ok",
        "literal_score": score,
        "literal_distinct": distinct,
        "literal_total": total,
        "stem_score": s_score,
        "triggering_count": len(triggering),
    }


# ---------------------------------------------------------------------------
# Module-load assertions (fail-fast on misconfigured deploy)
# ---------------------------------------------------------------------------
# Per Phase 2A precedent (jurisdiction_compliance.py), hard-fail at import
# surfaces deployment errors at start time rather than at runtime in front of
# a survivor. The lexicon stubs are part of the repo; if they're missing in
# production, the deploy is broken and we want the worker to fail to start.
def _module_load_invariants() -> None:
    if not isinstance(REGISTRY_VERSION, str) or not REGISTRY_VERSION:
        raise AssertionError("linguistic_arousal_load: REGISTRY_VERSION must be a non-empty string")
    if not isinstance(REGISTRY_CONTENT_HASH, str) or len(REGISTRY_CONTENT_HASH) != 64:
        raise AssertionError("linguistic_arousal_load: REGISTRY_CONTENT_HASH must be sha256 hex")
    if _DEFAULT_THRESHOLD <= 0:
        raise AssertionError("linguistic_arousal_load: _DEFAULT_THRESHOLD must be positive")
    # Ensure the production en-US stubs ship with the repo. If a future deploy
    # accidentally excludes backend/data/lexicons/, fail at import — better than
    # silently failing-closed forever in production.
    for required in _HASHED_FILES:
        if not required.exists():
            raise AssertionError(
                f"linguistic_arousal_load: required production stub missing: {required}. "
                "Ensure backend/data/lexicons/ is included in the deploy bundle."
            )


_module_load_invariants()


__all__ = [
    "REGISTRY_VERSION",
    "REGISTRY_CONTENT_HASH",
    "compute_content_hash",
    "assert_version_aligned",
    "ArousalLoad",
    "LexiconPattern",
    "LexiconStatus",
    "LEXICON_OK",
    "LEXICON_EMPTY_AWAITING_AUTHORING",
    "LEXICON_MISSING_OR_CORRUPT",
    "measure_response_load",
    "measure_user_disclosure_load",
    "clear_lexicon_cache",
    "_auditor_self_check",
]
