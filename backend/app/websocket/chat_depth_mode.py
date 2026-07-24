"""
Chat depth mode — Faster vs Extra turn budgets.

Faster: skip heavy pre-inference paths so first token arrives sooner.
Extra: full context + six-quotient depth directive.
"""
from __future__ import annotations

from typing import List, Optional

# QUANTUM-CRYSTAL-ARCH

DEPTH_FASTER = "faster"
DEPTH_EXTRA = "extra"


def normalize_depth_mode(raw: Optional[str]) -> str:
    v = (raw or DEPTH_EXTRA).strip().lower()
    if v in ("fast", "faster", "quick", "light"):
        return DEPTH_FASTER
    if v in ("extra", "deep", "full", "rich"):
        return DEPTH_EXTRA
    return DEPTH_EXTRA


def is_faster(mode: str) -> bool:
    return normalize_depth_mode(mode) == DEPTH_FASTER


def crystal_max_results(mode: str) -> int:
    return 4 if is_faster(mode) else 8


def pg_history_limit(mode: str) -> int:
    return 8 if is_faster(mode) else 15


def allow_enrichment(mode: str) -> bool:
    return not is_faster(mode)


def allow_plan_heavy(mode: str) -> bool:
    """Clinical technique directory / web-enrich inside plan_ctx."""
    return not is_faster(mode)


def allow_fsf(mode: str) -> bool:
    return not is_faster(mode)


def allow_newsletter_library(mode: str) -> bool:
    return not is_faster(mode)


def allow_deep_memory_search(mode: str) -> bool:
    """Deep memory search is Extra-only (biggest sequential cost)."""
    return not is_faster(mode)


def allow_web_search_auto(mode: str) -> bool:
    """Faster: only explicit search phrases (handled by caller); skip soft triggers."""
    return not is_faster(mode)


def build_extra_quotient_directive(user_text: str) -> str:
    """
    Extra-mode prompt block: pull more of the six quotient levels into the turn.
    Heuristic only — no LLM / DB / heavy imports (keeps Faster path lean).
    """
    active = _soft_quotient_tags(user_text or "")
    if not active:
        active = ["EQ", "SQ", "AQ"]

    focus = ", ".join(active)
    return (
        "[CHAT DEPTH: EXTRA — SIX QUOTIENT DEPTH]\n"
        f"Client cues most active: {focus}.\n"
        "Respond with clinical depth across the six quotients where relevant:\n"
        "- IQ: name the pattern/system without over-diagnosing\n"
        "- EQ: track affect + body if present; hold paradox\n"
        "- MQ: moral injury / right-wrong tension without prescribing\n"
        "- SQ: notice control/parallel process; do not accommodate armor\n"
        "- CQ: honor metaphor, culture, faith, generational frame if present\n"
        "- AQ: stay with crisis/helplessness; no premature coping lists\n"
        "Prioritize SQ/CQ/AQ when those cues are present (known weaker bands).\n"
        "Keep one coherent voice — deepen, do not lecture all six by name."
    )


def _soft_quotient_tags(text: str) -> List[str]:
    t = (text or "").lower()
    tags: List[str] = []
    if any(w in t for w in ("feel", "sad", "anxious", "angry", "scared", "hurt")):
        tags.append("EQ")
    if any(w in t for w in ("son", "daughter", "family", "partner", "wife", "husband", "friend")):
        tags.append("SQ")
    if any(w in t for w in ("god", "church", "faith", "denominat", "pray", "spirit")):
        tags.append("CQ")
    if any(w in t for w in ("true", "right", "wrong", "should", "guilt", "moral")):
        tags.append("MQ")
    if any(w in t for w in ("pattern", "always", "cycle", "why do i")):
        tags.append("IQ")
    if any(w in t for w in ("hopeless", "can't", "give up", "crisis", "suicid")):
        tags.append("AQ")
    return tags
