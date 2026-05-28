"""
Nate Response Validator — Post-generation hallucination scanner.

Runs after Azure/sovereign inference returns a response, BEFORE the response
is stored or delivered. Initial deployment is log-only mode: warnings are
logged to skyeye_activity but responses are never blocked or modified.

v1.3 additive extension (Phase 4 / Note 2): adds Layer 8 sensitive-lexicon
checks driven by clinician-authored
`data/lexicons/sensitive_domain_validator_lexicon_<locale>.json`. Existing
v1.2 behavior is unchanged when no `user_state` flows in context.
"""

import os
import re
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional, Set

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════
# v1.3 SENSITIVE LEXICON LOADER (Phase 4 / Note 2)
# ═════════════════════════════════════════════════════════════════════════
#
# Lexicon files live at backend/data/lexicons/
# sensitive_domain_validator_lexicon_<locale>.json. Loaded with mtime-based
# hot-reload. Fail-closed: malformed JSON triggers an audit event at
# severity=critical and falls back to last-known-good in-memory state. If no
# last-known-good exists (cold start), the loader returns None and the
# validator emits zero violations (fail-open at the violation layer; the
# audit event surfaces the failure to the trust enforcer).
#
# Lexicon entries are NEVER hardcoded in this module per Gap D contract.

_LEXICON_CACHE: Dict[str, Dict[str, Any]] = {}
_LEXICON_MTIME: Dict[str, float] = {}
_LEXICON_LOAD_FAILED_AT: Dict[str, float] = {}

# Audit-event hook (set by the host application at startup). Signature:
#     async def hook(event_type: str, severity: str, payload: dict) -> None
# When None, the loader logs locally only. The Phase 6 sensitive_bridge
# wiring sets this to a function that writes to skyeye_activity.
_LEXICON_AUDIT_HOOK: Optional[Any] = None


def set_lexicon_audit_hook(hook) -> None:
    """Register an async audit-event hook. Called by main.py at startup so
    the validator can emit `validator_lexicon_load_failed` and
    `validator_lexicon_loaded` events into skyeye_activity."""
    global _LEXICON_AUDIT_HOOK
    _LEXICON_AUDIT_HOOK = hook


def _lexicon_dir() -> Path:
    """Resolve the lexicon directory in a way that works for both the
    in-tree dev path and the deployed container layout."""
    here = Path(__file__).resolve()
    # backend/app/services/<file> -> backend/data/lexicons
    candidate = here.parent.parent.parent / "data" / "lexicons"
    if candidate.is_dir():
        return candidate
    # Container layout (/app/data/lexicons)
    alt = Path("/app/data/lexicons")
    if alt.is_dir():
        return alt
    return candidate  # return even if missing; loader will handle


def _resolve_lexicon_path(locale: str) -> Optional[Path]:
    """Locale fallback chain: en-US -> en -> en-US (default).

    Mirrors the clinical_arousal_lexicon resolver pattern (Phase 2 Gap 3).
    Returns None only when no file exists at any rung.
    """
    candidates: List[str] = []
    locale = (locale or "en-US").strip()
    candidates.append(f"sensitive_domain_validator_lexicon_{locale}.json")
    if "-" in locale:
        candidates.append(f"sensitive_domain_validator_lexicon_{locale.split('-')[0]}.json")
    if locale != "en-US":
        candidates.append("sensitive_domain_validator_lexicon_en-US.json")
    base_dirs = []
    for base in (
        _lexicon_dir(),
        Path("/backend/data/lexicons"),
        Path("/app/data/lexicons"),
    ):
        if base not in base_dirs:
            base_dirs.append(base)
    for base in base_dirs:
        for name in candidates:
            path = base / name
            if path.is_file():
                return path
    return None


def _emit_lexicon_audit(event_type: str, severity: str, payload: Dict[str, Any]) -> None:
    """Best-effort audit emission. Sync — schedules the async hook on the
    running loop if one exists; otherwise logs locally."""
    logger.warning(
        "NateResponseValidator: lexicon audit event=%s severity=%s payload=%s",
        event_type, severity, payload,
    )
    if _LEXICON_AUDIT_HOOK is None:
        return
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        loop.create_task(_LEXICON_AUDIT_HOOK(event_type, severity, payload))
    except RuntimeError:
        # No running loop — fall back to logger only.
        pass
    except Exception as e:
        logger.warning("NateResponseValidator: failed to dispatch audit hook: %s", e)


def _load_sensitive_lexicon(locale: str = "en-US") -> Optional[Dict[str, Any]]:
    """Hot-reload lexicon by mtime. Returns parsed dict or None.

    Cold-start failure (no file, no last-known-good) returns None; the
    audit event is emitted so the trust enforcer surfaces the gap.
    Mid-stream failure (malformed JSON after a successful prior load)
    falls back to the cached last-known-good and emits audit event.
    """
    path = _resolve_lexicon_path(locale)
    if path is None:
        # No file at any rung. Emit once per minute to avoid log flooding.
        last = _LEXICON_LOAD_FAILED_AT.get(locale, 0.0)
        if time.time() - last > 60:
            _LEXICON_LOAD_FAILED_AT[locale] = time.time()
            _emit_lexicon_audit(
                "validator_lexicon_load_failed",
                "critical",
                {"locale": locale, "reason": "no_lexicon_file_at_any_locale_rung"},
            )
        return _LEXICON_CACHE.get(locale)  # return last-known-good if any

    try:
        mtime = path.stat().st_mtime
        cached_mtime = _LEXICON_MTIME.get(locale, 0.0)
        if mtime == cached_mtime and locale in _LEXICON_CACHE:
            return _LEXICON_CACHE[locale]
        # Reload.
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("lexicon root is not a dict")
        # Stamp on first successful load OR on hot-reload.
        had_prior = locale in _LEXICON_CACHE
        _LEXICON_CACHE[locale] = data
        _LEXICON_MTIME[locale] = mtime
        meta = data.get("_meta", {}) if isinstance(data.get("_meta"), dict) else {}
        _emit_lexicon_audit(
            "validator_lexicon_loaded",
            "info",
            {
                "locale": locale,
                "lexicon_path": str(path),
                "schema_version": meta.get("schema_version"),
                "status": meta.get("status"),
                "hot_reload": had_prior,
            },
        )
        return data
    except Exception as e:
        # Fail-closed to last-known-good.
        last = _LEXICON_LOAD_FAILED_AT.get(locale, 0.0)
        if time.time() - last > 60:
            _LEXICON_LOAD_FAILED_AT[locale] = time.time()
            _emit_lexicon_audit(
                "validator_lexicon_load_failed",
                "critical",
                {"locale": locale, "reason": str(e), "lexicon_path": str(path)},
            )
        return _LEXICON_CACHE.get(locale)


# Crystal arousal-loaded markers (Gap 6 embodiment phase logic; Phase 1
# crystal ingestion already tags crystals with these markers in the
# `tags` JSONB or `markers` array). When user state is dissociation_grounding
# or CRISIS, these crystals must be excluded from recall.
AROUSAL_LOADED_MARKER_NAMES: Tuple[str, ...] = (
    "arousal_loaded",
    "trauma_processing",
    "disclosure_prompt",
    "embodiment_repair_advanced",
    "trauma_meaning_interpretation",
)

# User states that activate sensitive-recall filtering.
SENSITIVE_RECALL_STATES: frozenset = frozenset({
    "dissociation_grounding",
    "CRISIS",
})


def is_sensitive_recall_state(user_state: Optional[str]) -> bool:
    """Public predicate for v1.3 sensitive-recall gating.

    Returns True iff `user_state` is one of the states under which arousal-
    loaded crystals must be excluded from recall (see Note 2, Plan v1.3 §9).
    """
    return user_state in SENSITIVE_RECALL_STATES if user_state else False


def crystal_is_arousal_loaded(crystal: Any) -> bool:
    """Public predicate: True iff crystal carries any arousal-loaded marker.

    Inspects (in order):
      - `crystal["markers"]` — list of marker strings
      - `crystal["tags"]`    — list of tag strings or dict whose keys/values
                                 contain marker names
      - `crystal["metadata"]["markers"]` — nested location used by Phase 1
                                            ingestion

    Returns False on any malformed input — fail-open on the predicate side
    is intentional. The orchestrator caller is responsible for fail-closed
    behavior (e.g., dropping the crystal entirely if the call raises).
    """
    if not isinstance(crystal, dict):
        return False
    candidates: List[Any] = []
    candidates.append(crystal.get("markers"))
    candidates.append(crystal.get("tags"))
    md = crystal.get("metadata")
    if isinstance(md, dict):
        candidates.append(md.get("markers"))
        candidates.append(md.get("tags"))
    for c in candidates:
        if not c:
            continue
        if isinstance(c, str):
            if c in AROUSAL_LOADED_MARKER_NAMES:
                return True
            continue
        if isinstance(c, (list, tuple, set, frozenset)):
            for item in c:
                if isinstance(item, str) and item in AROUSAL_LOADED_MARKER_NAMES:
                    return True
            continue
        if isinstance(c, dict):
            for k, v in c.items():
                if isinstance(k, str) and k in AROUSAL_LOADED_MARKER_NAMES:
                    return True
                if isinstance(v, str) and v in AROUSAL_LOADED_MARKER_NAMES:
                    return True
    return False


def filter_sensitive_recalled_crystals(
    crystals: List[Any],
    user_state: Optional[str],
) -> Tuple[List[Any], int]:
    """v1.3 Gap 6 sensitive-recall filter (Note 2).

    Removes any crystal carrying an arousal-loaded marker when
    `user_state` is in `SENSITIVE_RECALL_STATES`. No-op otherwise.

    Returns `(filtered_crystals, dropped_count)` so the caller can include
    the count in audit telemetry without re-walking the list.
    """
    if not crystals or not is_sensitive_recall_state(user_state):
        return list(crystals or []), 0
    kept: List[Any] = []
    dropped = 0
    for crystal in crystals:
        try:
            if crystal_is_arousal_loaded(crystal):
                dropped += 1
                continue
        except Exception:
            # Fail-closed on the filter: if marker inspection raises, drop
            # the crystal — better to lose recall context than to surface
            # a potentially arousal-loaded crystal during dissociation/CRISIS.
            dropped += 1
            continue
        kept.append(crystal)
    return kept, dropped


class NateResponseValidator:
    """Scans Little Nate responses for hallucination patterns."""

    HALLUCINATION_PATTERNS = [
        (r'\b\d+\.\d+\s*(adj|adjacency|probe|gold|score)\b', "fabricated_score"),
        (r'\bprojected?\s+\d+%', "projected_percentage"),
        (r'\|\s*\*\*.*\*\*\s*\|.*\|\s*(0\.\d|Signal|Hold|Ripen)', "fabricated_table"),
    ]

    POSTING_CLAIM_PATTERN = re.compile(
        r'\bI\s+(posted|released|published|shared|pushed out)\b', re.IGNORECASE
    )
    TIMESTAMP_FABRICATION = re.compile(
        r'\b(on\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}|'
        r'at\s+\d{1,2}:\d{2}\s*(am|pm|AM|PM)?|yesterday\s+I)\b', re.IGNORECASE
    )
    HANDLE_PATTERN = re.compile(r'@(\w{2,30})')

    DEAD_FEATURES = {
        "batch replies", "batch endpoint", "email touchpoint",
        "threaded article", "multi-part release", "sectioned article",
    }

    PROMPT_INJECTION_PATTERNS = [
        re.compile(r'ignore\s+(all\s+)?previous\s+instructions', re.IGNORECASE),
        re.compile(r'<\|im_start\|>', re.IGNORECASE),
        re.compile(r'\bsystem\s*:', re.IGNORECASE),
        re.compile(r'you\s+are\s+now\s+(a|an|the)\b', re.IGNORECASE),
        re.compile(r'forget\s+(everything|all|your)', re.IGNORECASE),
        re.compile(r'new\s+instructions?\s*:', re.IGNORECASE),
    ]

    # Layer 7 — Source attribution: claims that reference sources must cite real ones
    UNSOURCED_CLAIM_PATTERNS = [
        re.compile(r'\b(studies?\s+show|research\s+(shows?|indicates?|confirms?)|data\s+shows?)\b', re.IGNORECASE),
        re.compile(r'\b(according\s+to|scientists?\s+(say|found|discovered))\b', re.IGNORECASE),
        re.compile(r'\b(peer[\-\s]reviewed|published\s+in|journal\s+of)\b', re.IGNORECASE),
        re.compile(r'\b(clinical\s+trials?\s+(show|demonstrate|prove))\b', re.IGNORECASE),
        re.compile(r'\b(statistically\s+significant|meta[\-\s]analysis\s+(shows?|found))\b', re.IGNORECASE),
    ]
    SOURCE_CITATION_PATTERN = re.compile(
        r'\(.*?\d{4}\)|\[.*?\d{4}\]|et\s+al\.?|doi:|https?://|PMID',
        re.IGNORECASE,
    )

    # Layer 8 — Factual grounding: Nate must never assert facts about real
    # people that fall outside the model's verifiable knowledge (Sovereign
    # Standard §8).  Only fires when Nate *volunteers* an assertion — not
    # when reflecting the client's own words back to them.
    FACTUAL_ASSERTION_PATTERNS = [
        re.compile(
            r'\b(he|she|they)\s+(is|are|was)\s+'
            r'(dead|alive|deceased|still alive|still living|passed away|died)\b',
            re.IGNORECASE,
        ),
        re.compile(
            r'\b(yes|no|actually|in fact),?\s+'
            r'(he|she|they)\s+(is|are|did|has|have)\s+'
            r'(die|pass|alive|dead|deceased|married|divorced)',
            re.IGNORECASE,
        ),
        re.compile(
            r'\b(confirmed|can confirm|I can tell you)\s+that\s+'
            r'(he|she|they)\s+(is|are|did|has)',
            re.IGNORECASE,
        ),
    ]
    # Phrases that indicate Nate is reflecting or validating, not asserting
    REFLECTIVE_PREFIXES = re.compile(
        r'\b(I\s+hear\s+that|you\s+(?:said|mentioned|shared|told me)\s+(?:that\s+)?'
        r'|you\'?re\s+(?:saying|telling me)\s+(?:that\s+)?'
        r'|it\s+sounds\s+like|what\s+I\'?m\s+hearing\s+is'
        r'|you\s+believe\s+(?:that\s+)?|from\s+what\s+you\'?ve\s+(?:said|shared))',
        re.IGNORECASE,
    )
    # Conjunctions that introduce an independent assertive clause after a
    # reflective prefix.  "I hear that he's dead, and honestly I think
    # that's true" — the second clause is Nate's own assertion.
    ASSERTIVE_CONJUNCTION = re.compile(
        r',?\s*\b(and\s+(?:honestly|actually|I\s+(?:think|believe|know))'
        r'|but\s+(?:honestly|actually|I\s+(?:think|believe|know))'
        r'|actually|honestly|in\s+fact|I\s+(?:can\s+confirm|do\s+(?:think|believe)))\b',
        re.IGNORECASE,
    )
    # Personal relational references: "my father/mother/brother/etc."
    PERSONAL_RELATION_PATTERN = re.compile(
        r'\b(my|your|her|his|their)\s+'
        r'(father|mother|dad|mom|brother|sister|husband|wife|son|daughter'
        r'|grandmother|grandfather|grandma|grandpa|uncle|aunt|cousin'
        r'|partner|spouse|friend|parent)\b',
        re.IGNORECASE,
    )

    # Layer 8c — Cross-member private attribution (family manipulation / FSF fishing).
    # Nate must never imply another member disclosed privately to him in 1:1.
    CROSS_MEMBER_ATTRIBUTION_PATTERNS = [
        re.compile(
            r'\b(?:your|ur)\s+(?:spouse|partner|wife|husband|mom|dad|mother|father'
            r'|brother|sister|son|daughter|parent|child)\s+'
            r'(?:told|said|shared|mentioned|confided|revealed)\s+(?:to\s+)?me\b',
            re.IGNORECASE,
        ),
        re.compile(
            r'\b(?:member\s+[ab]|partner\s+[ab])\b.{0,40}'
            r'\b(?:told|said|shared|mentioned|confided)\s+(?:to\s+)?me\b',
            re.IGNORECASE,
        ),
        re.compile(
            r'\bwhat\s+(?:he|she|they)\s+(?:told|shared with|said to)\s+me'
            r'\s+(?:privately|in confidence|in private|alone)\b',
            re.IGNORECASE,
        ),
        re.compile(
            r'\bfrom\s+what\s+(?:he|she|they|your\s+\w+)\s+'
            r'(?:told|shared)\s+(?:with\s+)?me\b',
            re.IGNORECASE,
        ),
        re.compile(
            r'\bin\s+(?:his|her|their)\s+'
            r'(?:private|individual|1[-:]?1|one-on-one)\s+'
            r'(?:session|conversation|chat)\b',
            re.IGNORECASE,
        ),
        re.compile(
            r'\bwhen\s+(?:he|she|they)\s+(?:was|were)\s+'
            r'(?:here|talking|with me)\s+(?:alone|privately|in private)\b',
            re.IGNORECASE,
        ),
    ]
    # Client-relay phrasing: spouse told *you*, not Nate — safe to reflect.
    CROSS_MEMBER_CLIENT_RELAY = re.compile(
        r'\b(?:told|said|shared|mentioned|confided)\s+(?:to\s+)?you\b',
        re.IGNORECASE,
    )
    CROSS_MEMBER_SANCTUARY_SAFE = re.compile(
        r'\b(?:in sanctuary|in the room|when you both|between you both|'
        r'the cycle|system dynamic|shared theme|you both (?:said|shared))\b',
        re.IGNORECASE,
    )

    # Layer 9 — Therapeutic boundary: Nate must never cross clinical lines
    THERAPEUTIC_BOUNDARY_PATTERNS = [
        re.compile(r'\byou\s+(should|must|need\s+to)\s+(take|stop\s+taking|increase|decrease|change)\s+.*\b(medication|dose|mg|prescription|drug)\b', re.IGNORECASE),
        re.compile(r'\b(I\s+diagnose|your\s+diagnosis\s+is|you\s+have\s+(been\s+)?diagnosed\s+with)\b', re.IGNORECASE),
        re.compile(r'\b(you\s+(should|need\s+to)\s+(kill|hurt|harm)\s+(yourself|others?))\b', re.IGNORECASE),
        re.compile(r'\b(don\'?t\s+call\s+(911|emergency|hotline|crisis\s+line))\b', re.IGNORECASE),
        re.compile(r'\b(I\'?m\s+a\s+(doctor|psychiatrist|physician|licensed))\b', re.IGNORECASE),
        re.compile(r'\b(stop\s+seeing\s+your\s+(therapist|doctor|psychiatrist|counselor))\b', re.IGNORECASE),
    ]

    def __init__(self, db_pool=None):
        self.db_pool = db_pool
        self._mode = "enforce"

    async def validate(
        self,
        response: str,
        context: dict,
    ) -> Tuple[str, List[str]]:
        """
        Validate a Nate response against context data.

        Returns (response_text, warnings_list).
        In log-only mode, response is never modified.
        """
        warnings: List[str] = []

        for pattern_str, label in self.HALLUCINATION_PATTERNS:
            if re.search(pattern_str, response, re.IGNORECASE):
                warnings.append(f"hallucination_pattern:{label}")

        posting_history = context.get("posting_history", "")
        if self.POSTING_CLAIM_PATTERN.search(response):
            if "[0 RECORDS]" in posting_history or "No posts found" in posting_history:
                warnings.append("posting_claim_without_history")

        if self.TIMESTAMP_FABRICATION.search(response):
            if "[0 RECORDS]" in posting_history:
                warnings.append("timestamp_in_empty_context")

        mentioned = set(self.HANDLE_PATTERN.findall(response))
        known = context.get("known_handles", set())
        system_handles = {"nate", "littlenate", "LittleNateBot", "sovereignsanctuary"}
        unknown = mentioned - known - system_handles
        if unknown:
            warnings.append(f"unknown_entities:{','.join(sorted(unknown))}")

        response_lower = response.lower()
        for feat in self.DEAD_FEATURES:
            if feat in response_lower:
                warnings.append(f"dead_feature_reference:{feat}")

        for patt in self.PROMPT_INJECTION_PATTERNS:
            if patt.search(response):
                warnings.append("prompt_injection_residue")
                break

        # Layer 7 — Source attribution: flag unsourced scientific claims
        has_scientific_claim = any(p.search(response) for p in self.UNSOURCED_CLAIM_PATTERNS)
        if has_scientific_claim and not self.SOURCE_CITATION_PATTERN.search(response):
            warnings.append("unsourced_scientific_claim")

        # Layer 8 — Factual grounding: flag confident assertions about real
        # people that fall outside the model's verifiable knowledge, but only
        # when Nate *volunteers* the claim.  Reflecting client words ("I hear
        # that your father is dead") or referencing personal relations is NOT
        # an assertion.
        #
        # Clause-level analysis: a sentence like "I hear that he's dead, and
        # honestly I think that's true" has a reflective first clause and an
        # assertive second clause.  We split on assertive conjunctions and
        # re-check whether the *assertion* falls after the conjunction.
        client_message = context.get("client_message", "")
        for patt in self.FACTUAL_ASSERTION_PATTERNS:
            match = patt.search(response)
            if not match:
                continue
            matched_text = match.group(0)
            sentence_start = response.rfind(".", 0, match.start())
            sentence_end = response.find(".", match.end())
            if sentence_end == -1:
                sentence_end = len(response)
            pre_clause = response[max(sentence_start, 0):match.end()]
            full_sentence = response[max(sentence_start, 0):sentence_end]

            refl_match = self.REFLECTIVE_PREFIXES.search(pre_clause)
            is_reflective = bool(refl_match)
            if is_reflective:
                # Check for an assertive conjunction that revokes the
                # reflective shield.  Two positions matter:
                #
                # 1. AFTER the assertion — "I hear that he is dead, and
                #    honestly I think that's true." (endorsement follows)
                # 2. BETWEEN the reflective prefix and the assertion —
                #    "You said he is dead, but actually he is still alive."
                #    (the conjunction introduces a new independent clause
                #    containing the assertion)
                post_assertion = response[match.end():sentence_end]
                between = pre_clause[refl_match.end():match.start() - max(sentence_start, 0)]
                if (self.ASSERTIVE_CONJUNCTION.search(post_assertion)
                        or self.ASSERTIVE_CONJUNCTION.search(between)):
                    is_reflective = False

            if is_reflective:
                continue
            if client_message and matched_text.lower() in client_message.lower():
                continue
            if self.PERSONAL_RELATION_PATTERN.search(full_sentence):
                continue
            warnings.append("unverified_factual_assertion_about_person")
            break

        # Layer 8c — Block invented cross-member private attribution (manipulation vector).
        client_message = context.get("client_message", "")
        family_names = context.get("family_member_names") or ()
        for patt in self.CROSS_MEMBER_ATTRIBUTION_PATTERNS:
            match = patt.search(response)
            if not match:
                continue
            matched_text = match.group(0)
            if self.CROSS_MEMBER_SANCTUARY_SAFE.search(response):
                break
            if self.CROSS_MEMBER_CLIENT_RELAY.search(response):
                break
            if client_message and matched_text.lower() in client_message.lower():
                break
            if family_names:
                name_hit = any(
                    re.search(rf"\b{re.escape(n)}\b", matched_text, re.I)
                    for n in family_names
                    if n and len(n) > 2
                )
                if name_hit and client_message and any(
                    re.search(rf"\b{re.escape(n)}\b", client_message, re.I)
                    for n in family_names
                    if n and len(n) > 2
                ):
                    break
            warnings.append("cross_member_private_attribution")
            break

        # Layer 9 — Therapeutic boundary: flag clinical overreach
        for patt in self.THERAPEUTIC_BOUNDARY_PATTERNS:
            if patt.search(response):
                warnings.append("therapeutic_boundary_violation")
                break

        # Layer 9b — Unsolicited clinical framing (Ticket 2, 2026-05-19)
        try:
            from app.services.little_nate_clinical_output_policy import (
                check_unsolicited_clinical_framing,
            )

            _recent = context.get("recent_user_messages") or ()
            _user_msg = (
                context.get("client_message")
                or context.get("user_message")
                or ""
            )
            for label in check_unsolicited_clinical_framing(
                response, _user_msg, _recent
            ):
                warnings.append(f"clinical_output:{label}")
        except ImportError:
            pass

        # ─────────────────────────────────────────────────────────────
        # v1.3 Sensitive Lexicon — additive Layer 8 extension (Note 2).
        # Single additive call. Only fires when context carries a
        # `user_state` key — v1.2 callers see no behavioral change.
        # ─────────────────────────────────────────────────────────────
        user_state = context.get("user_state") if isinstance(context, dict) else None
        if user_state:
            domain = context.get("domain") if isinstance(context, dict) else None
            locale = (context.get("locale") if isinstance(context, dict) else None) or "en-US"
            for violation in self._check_sensitive_lexicon(
                response=response,
                user_state=user_state,
                domain=domain,
                locale=locale,
            ):
                warnings.append(
                    f"lexicon_violation_{violation['severity']}:{violation['category']}"
                )

        return response, warnings

    def _check_sensitive_lexicon(
        self,
        *,
        response: str,
        user_state: str,
        domain: Optional[str] = None,
        locale: str = "en-US",
    ) -> List[Dict[str, str]]:
        """v1.3 Layer 8 sensitive-lexicon check (Phase 4 / Note 2).

        Returns list of LexiconViolation dicts:
            {"severity": "high"|"moderate", "category": str, "matched": str}

        High-severity violations should block + regenerate. Moderate
        violations should warn + log only.

        Lexicon driven entirely by `data/lexicons/
        sensitive_domain_validator_lexicon_<locale>.json` (clinician-authored
        per Gap D contract). When the lexicon is empty, missing, or
        currently fails to load, this method returns an empty list (the
        load failure is independently audited via `_emit_lexicon_audit`).
        """
        try:
            lex = _load_sensitive_lexicon(locale=locale)
        except Exception as e:
            logger.warning("NateResponseValidator: lexicon load raised: %s", e)
            return []
        if not lex:
            return []

        gating = lex.get("user_state_gating") or {}
        block_categories_in_states = gating.get("block_categories_in_states") or {}
        active_block_cats: List[str] = list(
            block_categories_in_states.get(user_state, []) or []
        )
        # Domain-specific overrides (additive, non-subtractive).
        if domain:
            domain_overrides = (gating.get("domain_overrides") or {}).get(domain) or {}
            extra = domain_overrides.get("block_categories", []) or []
            for cat in extra:
                if cat not in active_block_cats:
                    active_block_cats.append(cat)

        violations: List[Dict[str, str]] = []
        block_patterns = lex.get("block_patterns") or {}
        warn_patterns = lex.get("warn_patterns") or {}

        # High-severity: any pattern in active_block_cats that matches.
        for cat in active_block_cats:
            patterns = block_patterns.get(cat) or []
            for pattern_str in patterns:
                try:
                    if re.search(pattern_str, response, re.IGNORECASE):
                        violations.append({
                            "severity": "high",
                            "category": cat,
                            "matched": pattern_str,
                        })
                        break  # one high-severity hit per category is enough
                except re.error as e:
                    logger.warning(
                        "NateResponseValidator: malformed block pattern in "
                        "category=%s: %s (%s)", cat, pattern_str, e,
                    )
                    continue

        # Moderate-severity: any warn_patterns category. These fire regardless
        # of user_state because they are advisory.
        for cat, patterns in warn_patterns.items():
            for pattern_str in (patterns or []):
                try:
                    if re.search(pattern_str, response, re.IGNORECASE):
                        violations.append({
                            "severity": "moderate",
                            "category": cat,
                            "matched": pattern_str,
                        })
                        break
                except re.error as e:
                    logger.warning(
                        "NateResponseValidator: malformed warn pattern in "
                        "category=%s: %s (%s)", cat, pattern_str, e,
                    )
                    continue

        return violations

    @staticmethod
    def is_high_severity(warnings: List[str]) -> bool:
        """Return True if any warning should block crystal storage or flag a response."""
        HIGH_PREFIXES = (
            "hallucination_pattern:", "posting_claim_",
            "timestamp_in_empty", "dead_feature_reference:",
            "prompt_injection_residue",
            "therapeutic_boundary_violation",
            "unsourced_scientific_claim",
            "unverified_factual_assertion",
            "cross_member_private_attribution",
        )
        return any(
            w.startswith(HIGH_PREFIXES) or w == "cross_member_private_attribution"
            for w in warnings
        )

    async def log_warnings(
        self,
        warnings: List[str],
        response_preview: str = "",
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        odpe_signal: Optional[str] = None,
    ) -> None:
        """Log warnings to skyeye_activity for Trust Enforcer visibility.

        For factual grounding redirects, a separate record with type
        ``factual_grounding_redirect`` is also inserted to satisfy the
        Sovereign Standard §8 audit trail requirement (Illinois MHDDCA
        § 740 ILCS 110).
        """
        if not warnings or not self.db_pool:
            return
        meta = {
            "warnings": warnings,
            "response_preview": response_preview[:200],
        }
        if session_id:
            meta["session_id"] = session_id
        if user_id:
            meta["user_id"] = user_id
        if odpe_signal:
            meta["odpe_signal"] = odpe_signal
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO skyeye_activity (platform, type, content, severity, metadata, created_at)
                       VALUES ('system', 'nate_accuracy_warning', $1, 'warning', $2::jsonb, NOW())""",
                    f"{len(warnings)} accuracy warnings detected",
                    json.dumps(meta),
                )
                # §8 dedicated audit row for factual grounding redirects
                if "unverified_factual_assertion_about_person" in warnings:
                    await conn.execute(
                        """INSERT INTO skyeye_activity (platform, type, content, severity, metadata, created_at)
                           VALUES ('system', 'factual_grounding_redirect', $1, 'info', $2::jsonb, NOW())""",
                        response_preview[:200],
                        json.dumps({
                            "session_id": session_id,
                            "user_id": user_id,
                            "validator_warning": "unverified_factual_assertion_about_person",
                            "odpe_signal": odpe_signal,
                        }),
                    )
        except Exception as e:
            logger.warning("NateResponseValidator: failed to log warnings: %s", e)

    def extract_known_handles(self, *context_blocks: str) -> Set[str]:
        """Extract all @handles from context blocks to build the known set."""
        handles: Set[str] = set()
        for block in context_blocks:
            if block:
                handles.update(self.HANDLE_PATTERN.findall(block))
        return handles

    # Broader patterns for crystal text which uses full names rather than
    # pronouns.  Used only by the retrieval filter, not the response validator
    # (where false-positive cost is higher and conversation context narrows
    # the search space).
    CRYSTAL_ASSERTION_PATTERNS = FACTUAL_ASSERTION_PATTERNS + [
        re.compile(
            r'\b\w+\s+(is|are|was)\s+'
            r'(dead|alive|deceased|still alive|still living|passed away|died)\b',
            re.IGNORECASE,
        ),
        re.compile(
            r'\b(confirmed|reported|known)\s+(?:that\s+)?'
            r'\w+\s+(?:\w+\s+)?(is|are|was|has)\s+'
            r'(dead|alive|deceased|died|passed)',
            re.IGNORECASE,
        ),
    ]

    @classmethod
    def filter_recalled_crystals(cls, crystals: list) -> list:
        """Apply Layer 8 factual grounding check at retrieval time.

        Crystals stored before the validator existed may contain unverifiable
        assertions about real people.  This filter screens them on recall so
        they never re-enter the active context window.  Uses broader patterns
        than the response validator because crystal text uses full names
        rather than conversational pronouns.

        Filtered crystals are not deleted — they remain in PostgreSQL with
        their original scope.  They are simply excluded from the recall set
        returned to the consumer.
        """
        if not crystals:
            return crystals
        clean: list = []
        for crystal in crystals:
            text = ""
            if isinstance(crystal, dict):
                text = crystal.get("crystal_text", "") or crystal.get("text", "")
            elif isinstance(crystal, str):
                text = crystal
            flagged = False
            for patt in cls.CRYSTAL_ASSERTION_PATTERNS:
                if patt.search(text):
                    logger.info(
                        "NateResponseValidator: filtered recalled crystal containing "
                        "unverified factual assertion (%.60s...)", text[:60],
                    )
                    flagged = True
                    break
            if not flagged:
                clean.append(crystal)
        return clean
