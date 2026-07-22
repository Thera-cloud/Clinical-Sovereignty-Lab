"""Clinical citation relevance gate for Little Nate Dispatch.

# QUANTUM-CRYSTAL-ARCH — topic-matched cites (universal across CBT/DBT/ACT/…)
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Normalize modality / domain synonyms onto a shared tag vocabulary.
_TAG_ALIASES = {
    "cognitive": "cbt",
    "cognitive_behavioral": "cbt",
    "thought": "cbt",
    "thoughts": "cbt",
    "thought_record": "cbt",
    "thought_records": "cbt",
    "behavioral_activation": "cbt",
    "exposure": "cbt",
    "exposure_ladder": "cbt",
    "dialectical": "dbt",
    "distress_tolerance": "dbt",
    "dear_man": "dbt",
    "tipp": "dbt",
    "acceptance": "act",
    "defusion": "act",
    "values": "act",
    "parts": "ifs",
    "parts_work": "ifs",
    "internal_family": "ifs",
    "attachment": "adep",
    "eft": "adep",
    "emotionally_focused": "adep",
    "polyvagal": "somatic",
    "grounding": "somatic",
    "nervous_system": "somatic",
    "motivational": "mi",
    "motivational_interviewing": "mi",
    "change_talk": "mi",
    "gottman": "relationships",
    "gottman_informed": "relationships",
    "repair": "relationships",
    "listening": "relationships",
    "self-compassion": "self_compassion",
    "self_compassion": "self_compassion",
    "shame": "self_compassion",
    "nate": "nate_usage",
    "little_nate": "nate_usage",
    "neurodiverg": "neurodivergence",
    "autism": "neurodivergence",
    "adhd": "neurodivergence",
    "veteran": "military",
    "ptsd": "military",
    "fitness": "fitness",
    "sleep": "sleep",
    "grief": "grief",
    "burnout": "burnout",
    "parenting": "parenting",
    "arts": "arts",
    "curiosity": "curiosity",
    "help": "help_seeking",
    "help_seeking": "help_seeking",
    "safety": "safety",
}

_STOP_TOKENS = frozenset(
    {
        "and",
        "the",
        "for",
        "with",
        "your",
        "you",
        "this",
        "that",
        "week",
        "catching",
        "before",
        "runs",
        "tiny",
        "actions",
        "that",
        "reopen",
        "stuck",
        "day",
    }
)


def normalize_tag(raw: str) -> str:
    t = re.sub(r"[^a-z0-9]+", "_", (raw or "").strip().lower()).strip("_")
    if not t:
        return ""
    if t in _TAG_ALIASES:
        return _TAG_ALIASES[t]
    for key, canon in _TAG_ALIASES.items():
        if key in t or t in key:
            return canon
    return t


def normalize_tag_set(values: Iterable[Any]) -> Set[str]:
    out: Set[str] = set()
    for v in values or ():
        n = normalize_tag(str(v))
        if n and n not in _STOP_TOKENS and len(n) >= 2:
            out.add(n)
    return out


def issue_topic_tags(topic: Optional[Dict[str, Any]]) -> Set[str]:
    """Universal tag set for any Dispatch topic (curriculum + freeform)."""
    topic = topic or {}
    tags: Set[str] = set()
    tags |= normalize_tag_set([topic.get("domain")])
    tags |= normalize_tag_set(topic.get("modalities") or [])
    tags |= normalize_tag_set(topic.get("topic_tags") or [])

    key = str(topic.get("topic_key") or "")
    if key:
        tags |= normalize_tag_set(key.split("_"))

    title = str(topic.get("title") or "")
    if title:
        tags |= normalize_tag_set(re.findall(r"[A-Za-z]{3,}", title))

    # Curriculum enrichment happens in build_research_bundle / select_topic —
    # do not import curriculum here (keeps gate free of heavy service-package imports).

    # Drop ultra-generic leftovers that would match everything
    tags.discard("general")
    return tags


def citation_topic_tags(cite: Dict[str, Any]) -> Set[str]:
    tags = normalize_tag_set(cite.get("topic_tags") or ())
    if not tags:
        tags = normalize_tag_set(cite.get("domains") or ())
    tags |= normalize_tag_set(cite.get("technique_tags") or ())
    return tags


def citation_technique_tags(cite: Dict[str, Any]) -> Set[str]:
    return normalize_tag_set(cite.get("technique_tags") or ())


def _norm_label(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(
        r"\b(apa|nimh|nih|cdc|who|samhsa|va|nea|chadd|nhs|ifs|acbs|gottman)\b",
        " ",
        t,
    )
    return re.sub(r"\s+", " ", t).strip()


def labels_match(link_text: str, page_title: str) -> bool:
    """(b) Link/source label must describe the destination page title."""
    a = _norm_label(link_text)
    b = _norm_label(page_title)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    ta = set(a.split())
    tb = set(b.split())
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / float(max(len(ta), len(tb)))
    return overlap >= 0.45


def tags_overlap(a: Set[str], b: Set[str]) -> bool:
    return bool(a & b)


def score_citation_for_issue(cite: Dict[str, Any], issue_tags: Set[str]) -> int:
    """Higher = better match. Zero means do not include (except help_seeking later)."""
    c_tags = citation_topic_tags(cite)
    if not issue_tags or not c_tags:
        return 0
    overlap = c_tags & issue_tags
    if not overlap:
        return 0
    score = 10 * len(overlap)
    tech = citation_technique_tags(cite) & issue_tags
    if tech or cite.get("supports_technique"):
        score += 25
    if cite.get("modality") == "help_seeking":
        score -= 5  # prefer technique cites first
    return score


def select_relevant_citations(
    allowlist: Sequence[Dict[str, Any]],
    topic: Dict[str, Any],
    *,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Order allowlist by topic relevance. Never pads with unrelated domains."""
    issue_tags = issue_topic_tags(topic)
    scored: List[Tuple[int, Dict[str, Any]]] = []
    help_pool: List[Dict[str, Any]] = []
    for c in allowlist:
        if int(c.get("year") or 0) < 2024:
            continue
        s = score_citation_for_issue(c, issue_tags)
        if s > 0:
            scored.append((s, c))
        elif (c.get("modality") or "") == "help_seeking" or "help_seeking" in citation_topic_tags(c):
            help_pool.append(c)
    scored.sort(key=lambda x: (-x[0], x[1].get("source_name") or ""))
    chosen = [c for _, c in scored[:limit]]
    # Optional help directory only after a technique-supporting cite is present
    has_technique = any(
        citation_technique_tags(c) & issue_tags or c.get("supports_technique") for c in chosen
    )
    if has_technique and len(chosen) < limit:
        for h in help_pool:
            if h not in chosen:
                chosen.append(h)
            if len(chosen) >= limit:
                break
    return chosen


def validate_clinical_citations(
    draft: Dict[str, Any],
    bundle: Dict[str, Any],
    topic: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """(a) tag overlap (b) label↔title (c) ≥1 technique-supporting cite."""
    errors: List[str] = []
    topic = topic or (bundle.get("topic") if isinstance(bundle.get("topic"), dict) else {}) or {}
    if not topic.get("title") and draft.get("topic"):
        topic = {**topic, "title": draft.get("topic")}
    if not topic.get("domain") and bundle.get("domain"):
        topic = {**topic, "domain": bundle.get("domain")}

    issue_tags = issue_topic_tags(topic)
    cites = list(draft.get("citations") or bundle.get("citations") or [])
    if not cites:
        errors.append("no_citations")
        return errors

    technique_hits = 0
    for c in cites:
        if not isinstance(c, dict):
            errors.append("malformed_citation")
            continue
        c_tags = citation_topic_tags(c)
        if issue_tags and not tags_overlap(c_tags, issue_tags):
            # help_seeking may ride along only when technique cite already present
            is_help = (c.get("modality") or "") == "help_seeking" or "help_seeking" in c_tags
            if not (is_help and technique_hits > 0):
                errors.append(f"cite_topic_mismatch:{c.get('source_name') or c.get('url')}")
        page_title = (c.get("page_title") or "").strip()
        link_text = (c.get("source_name") or "").strip()
        if page_title and link_text and not labels_match(link_text, page_title):
            errors.append(f"cite_label_mismatch:{link_text}")
        tech = citation_technique_tags(c)
        if (tech & issue_tags) or (c.get("supports_technique") and tags_overlap(c_tags, issue_tags)):
            technique_hits += 1

    if technique_hits < 1:
        errors.append("missing_technique_supporting_cite")

    return errors
