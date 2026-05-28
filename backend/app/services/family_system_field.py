"""
Family System Field (FSF) — unified family dynamics brief with Sensitive Bridge isolation.

FSF stores de-identified, lane-tagged rows keyed by family_id. It never queries
Sensitive Bridge tables or raw private transcripts. Reads are requester-scoped.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_REDACTION_MIN_OVERLAP = 12

LANE_SYSTEM = "system_dynamics"
LANE_SANCTUARY = "sanctuary_shared"
LANE_MEMBER = "member_abstract"
LANE_COACH = "coach_clinical"
LANE_QUARANTINE = "quarantine"

CLIENT_VISIBLE_LANES = frozenset({LANE_SYSTEM, LANE_SANCTUARY, LANE_MEMBER})

_CROSS_MEMBER_PROBE = re.compile(
    r"\b("
    r"what did (?:my |our )?(?:spouse|partner|wife|husband|mom|dad|mother|father|"
    r"child|son|daughter|sibling|brother|sister|[\w]+)"
    r" (?:tell|said|share|disclose)"
    r"|what (?:did|does|has) .{0,40} (?:tell you|share with you|say in private)"
    r"|sensitive bridge|sensitive profile|polyvictim|addiction status|parts registry"
    r"|summarize (?:everything|all) (?:our )?family"
    r"|what do you know about (?:my |our )?(?:spouse|partner|wife|husband)"
    r")\b",
    re.IGNORECASE,
)

_SENSITIVE_LEXICON = re.compile(
    r"\b(polyvictim|codeword|addiction register|sex addiction|gambling status|"
    r"mandatory report|trafficking|legal proximity|dissociation delta|"
    r"sensitive bridge|user_parts_registry)\b",
    re.IGNORECASE,
)


def fsf_enabled() -> bool:
    return os.getenv("FAMILY_SYSTEM_FIELD_ENABLED", "true").lower() in ("1", "true", "yes")


def _normalize(s: str) -> str:
    return " ".join((s or "").lower().split())


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _overlap_leak(candidate: str, corpus: str, min_chars: int = _REDACTION_MIN_OVERLAP) -> bool:
    if not candidate or not corpus:
        return False
    c_n = _normalize(candidate)
    p_n = _normalize(corpus)
    if len(c_n) < min_chars or len(p_n) < min_chars:
        return False
    for i in range(len(c_n) - min_chars + 1):
        frag = c_n[i : i + min_chars]
        if frag in p_n:
            return True
    return False


def detect_cross_member_probe(message: str) -> Optional[str]:
    if not message:
        return None
    m = _CROSS_MEMBER_PROBE.search(message)
    return m.group(0) if m else None


def _deidentify_for_system(text: str, member_names: Sequence[str]) -> str:
    out = text
    for name in member_names:
        if name and len(name) > 2:
            out = re.sub(rf"\b{re.escape(name)}\b", "A family member", out, flags=re.I)
    return out


@dataclass
class FSFEntry:
    visibility_lane: str
    content: str
    subject_username: Optional[str] = None
    source_surface: str = ""


@dataclass
class FSFProjection:
    family_id: str
    requester_username: str
    entries: List[FSFEntry] = field(default_factory=list)
    probe_detected: bool = False
    lanes_restricted: bool = False


async def resolve_family_id(db_pool, identifier: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (family_id text, canonical username) for a hardware_id or username."""
    if not db_pool or not identifier:
        return None, None
    try:
        from app.services._identity_resolver import resolve_username

        username = await resolve_username(db_pool, identifier)
        if not username:
            return None, None
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COALESCE(
                    NULLIF(trim(family_id::text), ''),
                    NULLIF(trim(profile_data->>'family_id'), '')
                ) AS family_id
                FROM users WHERE username = $1
                """,
                username,
            )
        fid = (row["family_id"] if row else None) or None
        return (str(fid).strip() if fid else None), username
    except Exception as e:
        logger.warning("FSF resolve_family_id failed: %s", e)
        return None, None


async def _family_member_names(db_pool, family_id: str) -> List[str]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT profile_data->>'name' AS name, username
            FROM users
            WHERE trim(COALESCE(family_id::text, profile_data->>'family_id', '')) = $1
            """,
            family_id,
        )
    names: List[str] = []
    for r in rows:
        n = (r.get("name") or r.get("username") or "").strip()
        if n:
            names.append(n)
    return names


async def _audit(
    db_pool,
    *,
    family_id: Optional[str],
    requester: Optional[str],
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO family_system_field_audit
                    (family_id, requester_username, event_type, payload_json)
                VALUES ($1, $2, $3, $4::jsonb)
                """,
                family_id,
                requester,
                event_type,
                __import__("json").dumps(payload or {}),
            )
    except Exception as e:
        logger.warning("FSF audit write failed (%s): %s", event_type, e)


async def insert_entry(
    db_pool,
    *,
    family_id: str,
    content: str,
    visibility_lane: str,
    source_surface: str,
    subject_username: Optional[str] = None,
    sensitivity_class: str = "public",
    source_ref: Optional[str] = None,
    leak_corpus: Optional[str] = None,
) -> bool:
    """Insert FSF row after validation. Returns False if blocked."""
    content = (content or "").strip()
    if not content or len(content) > 2000:
        return False
    if leak_corpus and _overlap_leak(content, leak_corpus):
        await _audit(
            db_pool,
            family_id=family_id,
            requester=subject_username,
            event_type="fsf_write_blocked_overlap",
            payload={"lane": visibility_lane, "source": source_surface},
        )
        return False
    if _SENSITIVE_LEXICON.search(content) and visibility_lane != LANE_COACH:
        await _audit(
            db_pool,
            family_id=family_id,
            requester=subject_username,
            event_type="fsf_write_blocked_sensitive_lexicon",
            payload={"lane": visibility_lane},
        )
        return False

    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO family_system_field_entries (
                    family_id, subject_username, visibility_lane, sensitivity_class,
                    source_surface, source_ref, content, content_hash
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                family_id,
                subject_username,
                visibility_lane,
                sensitivity_class,
                source_surface,
                source_ref,
                content,
                _content_hash(content),
            )
        return True
    except Exception as e:
        logger.warning("FSF insert_entry failed: %s", e)
        return False


async def ingest_sanctuary_session(db_pool, sanctuary_data: Dict[str, Any]) -> int:
    """Write FSF lanes from a completed Sanctuary JSON payload."""
    if not fsf_enabled() or not db_pool:
        return 0
    family_id = sanctuary_data.get("family_id")
    if not family_id:
        return 0
    family_id = str(family_id).strip()
    sanctuary_id = str(
        sanctuary_data.get("sanctuary_id") or sanctuary_data.get("id") or ""
    )
    summary_wrap = sanctuary_data.get("session_summary") or {}
    summary = summary_wrap.get("summary") if isinstance(summary_wrap, dict) else {}
    if not isinstance(summary, dict):
        summary = {}

    member_names = await _family_member_names(db_pool, family_id)
    written = 0

    conflicts = summary.get("key_conflicts") or []
    if isinstance(conflicts, list):
        clean = [c for c in conflicts if isinstance(c, str) and c.strip()][:5]
        if clean:
            text = _deidentify_for_system(
                "Recurring tensions named in Sanctuary: " + "; ".join(clean[:3]),
                member_names,
            )
            if await insert_entry(
                db_pool,
                family_id=family_id,
                content=text[:2000],
                visibility_lane=LANE_SANCTUARY,
                source_surface="sanctuary_complete",
                source_ref=sanctuary_id,
            ):
                written += 1

    goals = summary.get("healing_goals") or summary.get("shared_goals") or []
    if isinstance(goals, list) and goals:
        gtext = _deidentify_for_system(
            "Shared healing direction: " + "; ".join(str(g) for g in goals[:3]),
            member_names,
        )
        if await insert_entry(
            db_pool,
            family_id=family_id,
            content=gtext[:2000],
            visibility_lane=LANE_SYSTEM,
            source_surface="sanctuary_complete",
            source_ref=sanctuary_id,
        ):
            written += 1

    progress = summary.get("overall_progress")
    if progress is not None:
        ptext = f"Family cohesion progress (Sanctuary session): {progress}/10."
        if await insert_entry(
            db_pool,
            family_id=family_id,
            content=ptext,
            visibility_lane=LANE_SYSTEM,
            source_surface="sanctuary_complete",
            source_ref=sanctuary_id,
        ):
            written += 1

    insights = summary.get("individual_insights") or {}
    if isinstance(insights, dict):
        for name, data in insights.items():
            if not isinstance(data, dict):
                continue
            patterns = data.get("patterns_observed") or data.get("growth_areas")
            if not patterns or patterns in ("Review needed", "N/A"):
                continue
            subject = await _username_for_display_name(db_pool, family_id, str(name))
            abstract = _deidentify_for_system(
                f"Patterns observed in Sanctuary for this member: {patterns}",
                [n for n in member_names if n.lower() != str(name).lower()],
            )
            if subject and await insert_entry(
                db_pool,
                family_id=family_id,
                content=str(abstract)[:2000],
                visibility_lane=LANE_MEMBER,
                source_surface="sanctuary_complete",
                subject_username=subject,
                source_ref=sanctuary_id,
            ):
                written += 1

    if written:
        await _audit(
            db_pool,
            family_id=family_id,
            requester=None,
            event_type="fsf_sanctuary_ingest",
            payload={"sanctuary_id": sanctuary_id, "rows": written},
        )
    return written


async def _username_for_display_name(db_pool, family_id: str, display_name: str) -> Optional[str]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT username FROM users
            WHERE trim(COALESCE(family_id::text, profile_data->>'family_id', '')) = $1
              AND (
                lower(profile_data->>'name') = lower($2)
                OR lower(username) = lower($2)
              )
            LIMIT 1
            """,
            family_id,
            display_name,
        )
    return str(row["username"]) if row else None


async def project_fsf(
    db_pool,
    *,
    family_id: str,
    requester_username: str,
    user_message: str = "",
) -> FSFProjection:
    """Requester-scoped FSF read with probe tightening."""
    projection = FSFProjection(
        family_id=family_id,
        requester_username=requester_username,
    )
    if not db_pool or not family_id:
        return projection

    probe = detect_cross_member_probe(user_message)
    if probe:
        projection.probe_detected = True
        projection.lanes_restricted = True
        await _audit(
            db_pool,
            family_id=family_id,
            requester=requester_username,
            event_type="fsf_probe_attempt",
            payload={"probe_fragment": probe[:80]},
        )

    allowed_lanes = {LANE_SYSTEM} if projection.lanes_restricted else set(CLIENT_VISIBLE_LANES)

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT visibility_lane, content, subject_username, source_surface
                FROM family_system_field_entries
                WHERE family_id = $1 AND superseded_at IS NULL
                ORDER BY created_at DESC
                LIMIT 40
                """,
                family_id,
            )
    except Exception as e:
        logger.warning("FSF project_fsf query failed: %s", e)
        return projection

    seen: set = set()
    for row in rows:
        lane = row["visibility_lane"]
        if lane not in allowed_lanes:
            continue
        if lane == LANE_MEMBER:
            subj = row["subject_username"]
            # member_abstract is requester-only in 1:1 — never expose another member's lane.
            if subj and subj != requester_username:
                continue
        content = row["content"]
        key = (lane, content[:120])
        if key in seen:
            continue
        if _SENSITIVE_LEXICON.search(content):
            continue
        seen.add(key)
        projection.entries.append(
            FSFEntry(
                visibility_lane=lane,
                content=content,
                subject_username=row["subject_username"],
                source_surface=row["source_surface"] or "",
            )
        )
        if len(projection.entries) >= 12:
            break

    return projection


def format_fsf_prompt_block(projection: FSFProjection) -> str:
    if not projection.entries:
        return ""

    lines = [
        "FAMILY SYSTEM FIELD (FSF — synthesized system dynamics, not private transcripts):",
        "- Do NOT confirm or deny another member's private or Sensitive Bridge record.",
        "- NEVER attribute private disclosures to another member (e.g. 'your spouse told me', "
        "'Member A said', 'in their private session they shared'). You do not relay 1:1 or Bridge content.",
        "- If asked what someone else shared privately, redirect to their own experience or Sanctuary.",
    ]
    if projection.lanes_restricted:
        lines.append(
            "- Cross-member probe detected: use only general system-cycle language; "
            "do not retrieve or imply hidden member-specific clinical data."
        )

    by_lane: Dict[str, List[str]] = {}
    for e in projection.entries:
        by_lane.setdefault(e.visibility_lane, []).append(e.content)

    order = (LANE_SYSTEM, LANE_SANCTUARY, LANE_MEMBER)
    labels = {
        LANE_SYSTEM: "System dynamics",
        LANE_SANCTUARY: "Sanctuary-shared themes",
        LANE_MEMBER: "Your member themes (system-framed)",
    }
    for lane in order:
        items = by_lane.get(lane)
        if not items:
            continue
        lines.append(f"\n{labels.get(lane, lane)}:")
        for item in items[:4]:
            lines.append(f"  • {item}")

    return "\n".join(lines)


async def build_fsf_chat_context(
    db_pool,
    identifier: str,
    user_message: str = "",
) -> str:
    """Build prompt block for 1:1 chat. Returns empty when disabled or no family."""
    if not fsf_enabled():
        return ""
    family_id, username = await resolve_family_id(db_pool, identifier)
    if not family_id or not username:
        return ""
    projection = await project_fsf(
        db_pool,
        family_id=family_id,
        requester_username=username,
        user_message=user_message,
    )
    return format_fsf_prompt_block(projection)
