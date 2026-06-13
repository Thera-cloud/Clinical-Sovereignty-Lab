"""IFS Parts Auto-Extraction from chat (Sensitive Bridge v1.4 extension).

# QUANTUM-CRYSTAL-ARCH — auto-ingests named IFS parts (also called "alters")
# from client free-text into `user_parts_registry`, gated by Sensitive Bridge
# enrollment. Fire-and-forget side effect of the therapeutic context pre-flight.

Patterns are conservative and capitalization-gated to avoid false positives.
Only fires when:
  - client is enrolled in Sensitive Bridge (cohort != 'unenrolled')
  - `gap_codeword_enabled` OR `v1_4_codeword_listener_enabled` is true
  - canonical username resolves
Inserts use ON CONFLICT (user_id, part_name) DO NOTHING. Audit row written to
`sensitive_bridge_log` as `part_client_initiated` with `auto_extracted: true`.

Never raises into the caller's hot path.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Per migration 217 part_category CHECK constraint
_VALID_CATEGORIES = {
    "protector",
    "exile",
    "firefighter",
    "manager",
    "addict_part",
    "self",
    "other",
}

# Stop-words that look like names but are pronouns / discourse markers.
_NAME_STOPLIST = {
    "her", "him", "them", "it", "myself", "ourselves", "you", "me", "us",
    "this", "that", "those", "these", "the", "a", "an", "my", "your", "our",
    "and", "or", "but", "so", "because", "when", "while", "after", "before",
    "today", "yesterday", "tomorrow", "tonight",
    "out", "up", "down", "back", "off", "on", "in", "to", "by", "of", "for",
    "good", "bad", "ok", "okay", "fine", "ready", "done", "here", "there",
    "is", "was", "are", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should",
    "really", "very", "just", "now", "then", "still", "always", "never",
    "name", "named", "called", "part", "parts", "thing", "way", "kind",
    "myself", "many", "all", "some", "any", "one", "two", "three",
    "she", "he", "we", "they",
}

# Names that clearly map to a category from context inside the same sentence.
_CATEGORY_KEYWORDS = (
    # category, [keywords]
    ("protector", [
        r"\bprotector\b", r"\bguardian\b", r"\bdefender\b", r"\bwatcher\b",
        r"\bgatekeeper\b", r"\bsilence(?:r|d|s)?\b", r"\bcritic\b",
        r"\bperfection(?:ist)?\b", r"\bcontrol(?:ler)?\b",
        r"\bangry (?:with|at) the others?\b", r"\bstand(?:s|ing)? watch\b",
    ]),
    ("exile", [
        r"\bexile(?:d|s)?\b", r"\bunwanted\b", r"\babandoned\b",
        r"\bhid (?:and|away|in)\b", r"\bhidden\b", r"\bscar(?:ed|y)\b",
        r"\bashamed\b", r"\blonely\b", r"\bunloved\b", r"\binvisible\b",
        r"\byounger (?:self|part|girl|boy|me)\b", r"\binner child\b",
        r"\bfelt unwanted\b", r"\bshrank from\b", r"\bsmall (?:one|girl|boy)\b",
    ]),
    ("firefighter", [
        r"\bfirefighter\b", r"\bdistract(?:s|er)?\b", r"\bnumbs?\b",
        r"\baddict(?:ion|ed|s)?\b", r"\bbinge(?:s|d|r)?\b", r"\brage(?:s|d)?\b",
        r"\bimpuls(?:e|ive)\b", r"\breactive\b",
    ]),
    ("manager", [
        r"\bmanager\b", r"\barchiv(?:ist|e|er)\b", r"\bplanner\b",
        r"\borganiz(?:er|ing)\b", r"\baccount(?:ant|able)\b",
        r"\bkeeper\b", r"\bstrategist\b", r"\bcaretaker\b",
        r"\bnarrator\b",
    ]),
    ("addict_part", [
        r"\baddict\b", r"\busing part\b", r"\bcraving part\b",
    ]),
    ("self", [
        r"\bself energy\b", r"\bcuriou(?:s|sity)\b", r"\bcompassion\b",
        r"\bcalm part\b", r"\bgrounded self\b",
    ]),
)

# Primary extraction patterns. Each must capture group 1 = candidate part name.
# We require capitalized first letter to avoid generic noun matches.
_PATTERNS: Tuple[re.Pattern, ...] = (
    # "I called her Lonely Girl" / "I called that one the Silencer"
    re.compile(
        r"(?:I (?:call|called|named|name)|we (?:call|called))\s+"
        r"(?:her|him|it|them|that(?: one| part)?|this(?: one| part)?)\s+"
        r"(?:the\s+)?([A-Z][A-Za-z]{2,20}(?:\s+[A-Za-z][A-Za-z]{1,20}){0,2})",
        re.IGNORECASE | re.UNICODE,
    ),
    # "a protector who ... so I called that one the Silencer" — backup with "the X"
    re.compile(
        r"\bso\s+I\s+(?:call|called|named)\s+(?:that\s+(?:one|part)\s+)?"
        r"the\s+([A-Z][A-Za-z]{2,20}(?:\s+[A-Za-z][A-Za-z]{1,20}){0,2})",
        re.UNICODE,
    ),
    # "I have a part (called|named) X" / "there's a part called X"
    re.compile(
        r"(?:I (?:have|had|got)|there'?s|there was|there is)\s+"
        r"(?:a|another|an)\s+(?:part|protector|exile|firefighter|manager|alter)"
        r"\s+(?:called|named|that I (?:call|named|named as))\s+"
        r"(?:the\s+)?([A-Z][A-Za-z]{2,20}(?:\s+[A-Za-z][A-Za-z]{1,20}){0,2})",
        re.IGNORECASE | re.UNICODE,
    ),
    # "the Archivist as a part" / "the Silencer is a part"
    re.compile(
        r"\bthe\s+([A-Z][A-Za-z]{2,20})\s+(?:as|is|was)\s+a\s+part\b",
        re.UNICODE,
    ),
)


def _infer_category(part_name: str, surrounding_text: str) -> str:
    """Infer category from name + nearby context. Default 'other'."""
    name_lower = part_name.lower()
    ctx_lower = surrounding_text.lower()

    # Direct embedding of category in name
    if any(w in name_lower for w in ("protector", "guardian", "silencer", "critic", "watcher")):
        return "protector"
    if any(w in name_lower for w in ("exile", "child", "younger", "lonely", "scolded", "scared", "invisible")):
        return "exile"
    if any(w in name_lower for w in ("firefighter", "addict", "binge", "rage")):
        return "firefighter"
    if any(w in name_lower for w in ("manager", "archivist", "planner", "narrator", "keeper", "caretaker")):
        return "manager"

    for category, patterns in _CATEGORY_KEYWORDS:
        for pat in patterns:
            if re.search(pat, ctx_lower):
                return category
    return "other"


def _is_valid_name(candidate: str) -> bool:
    """Reject pronouns, stop-words, and structurally odd candidates."""
    if not candidate:
        return False
    parts = candidate.strip().split()
    if not parts:
        return False
    # All tokens must not be stop-words.
    if all(tok.lower() in _NAME_STOPLIST for tok in parts):
        return False
    # First token must be capitalized.
    if not parts[0][0].isupper():
        return False
    # Reject pure all-caps if too short (likely an acronym, not a name).
    if candidate.upper() == candidate and len(candidate) <= 3:
        return False
    # Length cap (DB column is varchar(64))
    if len(candidate) > 50:
        return False
    return True


def extract_named_parts(user_text: str) -> List[Dict[str, str]]:
    """Return list of {part_name, part_category, evidence} dicts.

    Conservative: deduplicates and only emits names that pass `_is_valid_name`.
    """
    if not user_text or len(user_text) < 12:
        return []

    found: Dict[str, Dict[str, str]] = {}
    for pat in _PATTERNS:
        for m in pat.finditer(user_text):
            candidate = (m.group(1) or "").strip().rstrip(".,;:!?\"'")
            if not _is_valid_name(candidate):
                continue
            # Title-case normalize: "Lonely girl" -> "Lonely Girl"
            normalized = " ".join(
                tok if tok.isupper() else tok.capitalize()
                for tok in candidate.split()
            )
            if normalized in found:
                continue
            # Surrounding sentence (60 chars before, 80 after) for category cue.
            start = max(0, m.start() - 60)
            end = min(len(user_text), m.end() + 80)
            ctx = user_text[start:end]
            category = _infer_category(normalized, ctx)
            found[normalized] = {
                "part_name": normalized,
                "part_category": category,
                "evidence": ctx.strip()[:240],
            }
    return list(found.values())


# ───────────────────────────────────────────────────────────────────
# DB persistence (gated by enrollment + feature flag)
# ───────────────────────────────────────────────────────────────────

_AUTO_EXTRACT_CREATED_BY = "auto_extract_from_chat"


async def _is_enrolled(db_pool, username: str) -> Tuple[bool, Dict[str, Any]]:
    """Return (enrolled, gap_flags_dict). Fail-soft on errors."""
    if not db_pool or not username:
        return False, {}
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT cohort_label, gap_features_enabled
                  FROM sensitive_bridge_enrollment
                 WHERE user_id = $1
                """,
                username,
            )
        if not row:
            return False, {}
        cohort = (row["cohort_label"] or "").strip().lower()
        if cohort in ("unenrolled", ""):
            return False, {}
        flags_raw = row["gap_features_enabled"]
        if isinstance(flags_raw, str):
            try:
                flags = json.loads(flags_raw)
            except Exception:
                flags = {}
        elif isinstance(flags_raw, dict):
            flags = flags_raw
        else:
            flags = {}
        return True, flags
    except Exception as e:
        logger.warning("parts_auto_extractor: enrollment check failed: %s", e)
        return False, {}


async def _emit_audit(
    db_pool,
    *,
    username: str,
    session_id: Optional[str],
    part_name: str,
    part_category: str,
    evidence: str,
    inserted_id: Optional[int],
) -> None:
    if not db_pool:
        return
    try:
        payload = {
            "event_type": "part_client_initiated",
            "part_name": part_name,
            "part_category": part_category,
            "auto_extracted": True,
            "extraction_method": "regex_v1",
            "evidence_excerpt": evidence[:180],
            "registry_id": inserted_id,
        }
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sensitive_bridge_log (
                    user_id, session_id, event_type, event_severity,
                    payload_json, access_classification, recorded_by,
                    pii_screened_at, redaction_pass_count
                ) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, NOW(), 1)
                """,
                username,
                session_id,
                "part_client_initiated",
                "info",
                json.dumps(payload),
                "clinician_and_admin",
                "parts_auto_extractor",
            )
    except Exception as e:
        logger.warning(
            "parts_auto_extractor: audit emit failed for %s/%s: %s",
            username, part_name, e,
        )


async def auto_extract_and_register(
    db_pool,
    *,
    canonical_username: str,
    user_text: str,
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extract named parts from user_text and upsert into user_parts_registry.

    Returns list of dicts describing what was inserted (id, part_name,
    part_category). Empty list when not enrolled or nothing extracted. Never
    raises.
    """
    if not db_pool or not canonical_username or not user_text:
        return []

    enrolled, flags = await _is_enrolled(db_pool, canonical_username)
    if not enrolled:
        return []

    # Gate by either codeword listener flag (v1.3) or v1.4 codeword flag.
    if not (
        bool(flags.get("gap_codeword_enabled"))
        or bool(flags.get("v1_4_codeword_listener_enabled"))
    ):
        return []

    candidates = extract_named_parts(user_text)
    if not candidates:
        return []

    inserted: List[Dict[str, Any]] = []
    for cand in candidates:
        name = cand["part_name"]
        category = cand["part_category"]
        if category not in _VALID_CATEGORIES:
            category = "other"
        evidence = cand.get("evidence", "")
        description = (
            f"Auto-extracted from chat. Evidence: {evidence[:200]}"
            if evidence else "Auto-extracted from chat."
        )
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO user_parts_registry (
                        user_id, part_name, part_number, part_category,
                        addiction_link, description, protected_exile_part_id,
                        is_active, created_by, client_initiated
                    ) VALUES ($1, $2, NULL, $3, NULL, $4, NULL, TRUE, $5, TRUE)
                    ON CONFLICT (user_id, part_name) DO NOTHING
                    RETURNING id
                    """,
                    canonical_username,
                    name[:64],
                    category,
                    description,
                    _AUTO_EXTRACT_CREATED_BY,
                )
            if row is None:
                # Already registered — skip audit to avoid noise.
                continue
            new_id = int(row["id"])
            inserted.append({
                "id": new_id,
                "part_name": name,
                "part_category": category,
            })
            await _emit_audit(
                db_pool,
                username=canonical_username,
                session_id=session_id,
                part_name=name,
                part_category=category,
                evidence=evidence,
                inserted_id=new_id,
            )
        except Exception as e:
            logger.warning(
                "parts_auto_extractor: insert failed for %s/%s: %s",
                canonical_username, name, e,
            )
            continue

    if inserted:
        logger.info(
            "parts_auto_extractor: registered %d parts for %s: %s",
            len(inserted), canonical_username,
            ", ".join(f"{p['part_name']}({p['part_category']})" for p in inserted),
        )
    return inserted


__all__ = [
    "extract_named_parts",
    "auto_extract_and_register",
]
