"""Public depth for the live show. No names, no ages, no children. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import logging
import re
from typing import List

logger = logging.getLogger("studio.public_depth")

_CHILD_AGE = re.compile(
    r"\b(?:child|children|kid|kids|son|daughter|boy|girl|teen|minor|infant|"
    r"baby|toddler|newborn|years?\s*old|year-old|\d{1,2}\s*yo|age\s+\d+)\b",
    re.I,
)
_TITLE = re.compile(r"\b(?:Mr|Mrs|Ms|Dr)\.?\s+[A-Z][a-z]+\b")
_PAIR = re.compile(r"\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]\d{4}\b")
_SCORE = re.compile(r"\b\d+\s*/\s*10\b|\bscore\s*[:=]?\s*\d+\b", re.I)
_KEEP_PAIR = {
    "little nate",
    "big nate",
    "sovereign sanctuary",
    "thera world",
}
_KEEP_WORD = {
    "Nate", "Little", "Big", "Sovereign", "Sanctuary", "Thera", "World",
    "Yeah", "Man", "Honestly", "Oh", "Nah", "The", "That", "This", "What",
    "When", "Where", "Alright", "Sorry", "Look", "Here", "There", "Then",
    "And", "But", "Well", "How", "Why", "Let", "Just", "Right", "Good",
}
_MID = re.compile(r"(?<=[a-z]\s)([A-Z][a-z]{2,})\b")
_STOP = {
    "about", "after", "again", "being", "could", "doing", "from", "have",
    "into", "just", "like", "more", "that", "their", "them", "then", "there",
    "these", "they", "this", "what", "when", "with", "would", "your", "really",
    "people", "something", "because", "where", "which", "while", "other",
}


def _refer(sentence: str) -> str:
    low = sentence.lower()
    if re.search(r"\b(?:couple|husband|wife|partner|marriage|married)\b", low):
        who = "a couple"
    elif re.search(r"\b(?:she|her|woman|women)\b", low):
        who = "a woman"
    else:
        who = "a gentleman"
    sentence = _TITLE.sub(who, sentence)

    def _pair(match: re.Match) -> str:
        phrase = f"{match.group(1)} {match.group(2)}".lower()
        if phrase in _KEEP_PAIR:
            return match.group(0)
        return who

    sentence = _PAIR.sub(_pair, sentence)

    def _mid(match: re.Match) -> str:
        if match.group(1) in _KEEP_WORD:
            return match.group(0)
        return who

    sentence = _MID.sub(_mid, sentence)
    parts = sentence.split()
    head = parts[0].rstrip(".,!?:;") if parts else ""
    if head and head not in _KEEP_WORD and re.fullmatch(r"[A-Z][a-z]{2,}", head):
        parts[0] = who + parts[0][len(head):]
        sentence = " ".join(parts)
    return sentence


def guard_onair(text: str) -> str:
    """Drop child and age lines. Hide names as a gentleman, a woman, or a couple."""
    raw = _EMAIL.sub("", _PHONE.sub("", text or ""))
    raw = _SCORE.sub("", raw)
    kept: List[str] = []
    for part in re.split(r"(?<=[.!?])\s+", raw):
        line = " ".join(part.split())
        if not line or _CHILD_AGE.search(line):
            continue
        kept.append(_refer(line))
    return " ".join(kept).strip()


def _terms(query: str) -> List[str]:
    words = re.findall(r"[a-z]{5,}", (query or "").lower())
    out = []
    for word in words:
        if word in _STOP or word in out:
            continue
        out.append(word)
        if len(out) == 5:
            break
    return out


def _hits(text: str, terms: List[str]) -> bool:
    if not terms:
        return False
    low = (text or "").lower()
    return any(term in low for term in terms)


async def depth_for_show(db_pool, query: str) -> str:
    """Global crystals, approved teaching, lived-wisdom themes. Empty if nothing fits."""
    terms = _terms(query)
    if db_pool is None or not terms:
        return ""
    crystals: List[str] = []
    teaching: List[str] = []
    lived: List[str] = []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT crystal_text
                FROM nate_intelligence_crystals
                WHERE user_id IS NULL
                  AND scope = 'global'
                  AND superseded_by IS NULL
                  AND domain = ANY($1::text[])
                  AND confidence >= 0.55
                ORDER BY confidence DESC
                LIMIT 40
                """,
                ["clinical", "coaching", "research", "culture", "general"],
            )
            for row in rows:
                text = guard_onair(row["crystal_text"] or "")
                if text and _hits(text, terms):
                    crystals.append(text[:280])
                if len(crystals) == 2:
                    break
            guides = await conn.fetch(
                """
                SELECT principal_response
                FROM principal_review_library
                WHERE status IN ('approved', 'promoted')
                ORDER BY updated_at DESC
                LIMIT 30
                """
            )
            for row in guides:
                text = guard_onair(row["principal_response"] or "")
                if text and _hits(text, terms):
                    teaching.append(text[:280])
                if len(teaching) == 1:
                    break
            sessions = await conn.fetch(
                """
                SELECT payload
                FROM classroom_session_analyses
                ORDER BY analyzed_at DESC
                LIMIT 12
                """
            )
    except Exception as exc:
        logger.warning("studio public depth skipped: %s", exc)
        sessions = []
    for row in sessions:
        payload = row["payload"] if row else None
        if isinstance(payload, str):
            try:
                import json
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            continue
        bits = []
        for key in ("strengths", "growth_areas"):
            val = payload.get(key) or []
            if isinstance(val, list):
                bits.extend(str(item) for item in val[:2])
            elif isinstance(val, str):
                bits.append(val)
        text = guard_onair(". ".join(bits))
        if text and _hits(text, terms):
            lived.append(text[:220])
        if len(lived) == 1:
            break
    lines = []
    if crystals:
        lines.append("Field notes: " + " ".join(crystals))
    if teaching:
        lines.append("Teaching: " + " ".join(teaching))
    if lived:
        lines.append("From the work, unnamed: " + " ".join(lived))
    if not lines:
        return ""
    return (
        "PUBLIC DEPTH. Use this as understanding. Speak in plain words around their question. "
        "Never name a person. Say a gentleman, a woman, or a couple. "
        "Never mention a child or an age. Do not recite these notes.\n"
        + "\n".join(lines)
    )
