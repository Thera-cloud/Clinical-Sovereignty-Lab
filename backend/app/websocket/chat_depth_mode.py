"""
Chat depth mode — Faster vs Extra turn budgets.

Faster: skip heavy pre-inference paths; still inject a compact richness directive.
Extra: full context + full six-quotient depth directive.
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
    # QUANTUM-CRYSTAL-ARCH: hybrid Faster keeps 6 crystals (was 4) for richness
    return 6 if is_faster(mode) else 8


def pg_history_limit(mode: str) -> int:
    return 8 if is_faster(mode) else 15


def allow_enrichment(mode: str) -> bool:
    return not is_faster(mode)


def allow_plan_heavy(mode: str) -> bool:
    """Clinical technique directory / web-enrich inside plan_ctx."""
    return not is_faster(mode)


def allow_plan_context(mode: str) -> bool:
    """QUANTUM-CRYSTAL-ARCH: Faster skips all plan_ctx (active + cycle + sandbox)."""
    return not is_faster(mode)


def crystal_recall_timeout_s(mode: str) -> float | None:
    """
    Wall-clock cap for crystal recall on Faster. Extra = uncapped (None).
    Override via BRIDGE_FASTER_CRYSTAL_TIMEOUT_S (seconds).
    """
    if not is_faster(mode):
        return None
    import os

    raw = (os.getenv("BRIDGE_FASTER_CRYSTAL_TIMEOUT_S") or "2.5").strip()
    try:
        val = float(raw)
    except ValueError:
        val = 2.5
    return max(0.5, val) if val > 0 else None


def relational_timeout_s(mode: str) -> float | None:
    """Cap relational/story gather on Faster; Extra uncapped."""
    if not is_faster(mode):
        return None
    import os

    raw = (os.getenv("BRIDGE_FASTER_RELATIONAL_TIMEOUT_S") or "1.2").strip()
    try:
        val = float(raw)
    except ValueError:
        val = 1.2
    return max(0.3, val) if val > 0 else None


def stream_before_therapeutic_audit(mode: str) -> bool:
    """
    When True, stream tokens to client before post-flight TMC audit.
    Env ENABLE_STREAM_BEFORE_THERAPEUTIC_AUDIT:
      faster (default) | true | always | false
    """
    import os

    raw = (os.getenv("ENABLE_STREAM_BEFORE_THERAPEUTIC_AUDIT") or "faster").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on", "always"):
        return True
    # default / "faster": only Faster depth streams before audit
    return is_faster(mode)


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


def build_faster_richness_directive(user_text: str) -> str:
    """
    Compact richness for Faster — same clinical voice as Extra, less prompt bulk.
    Heuristic only (no LLM / DB).
    """
    active = _soft_quotient_tags(user_text or "")
    if not active:
        active = ["EQ", "SQ", "AQ"]
    focus = ", ".join(active)
    return (
        "[CHAT DEPTH: FASTER — RICH CLINICAL VOICE]\n"
        f"Client cues most active: {focus}.\n"
        "Stay clinically rich despite a light context path:\n"
        "- Name the pattern (IQ) without diagnosing; track affect/body (EQ).\n"
        "- Notice relational armor / parallel process (SQ); honor faith/metaphor (CQ) if present.\n"
        "- Hold moral tension (MQ) and crisis/helplessness (AQ) — no premature coping lists.\n"
        "One coherent voice, warm and specific — deepen; do not lecture quotient names."
    )


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


def build_depth_richness_directive(mode: str, user_text: str) -> str:
    """Pick Faster compact or Extra full richness block."""
    if is_faster(mode):
        return build_faster_richness_directive(user_text)
    return build_extra_quotient_directive(user_text)


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
