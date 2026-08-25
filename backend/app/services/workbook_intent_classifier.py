"""Coaching workbook intent classifier.

Deterministic (no LLM): scores a client's utterance against known workbook
methods and returns a single recommendation LN/AlphaLN/Queens can use to
decide whether to *offer* a workbook exercise (with consent) or *observe*.

Contract:
    classify(user_text: str, recent_texts: list[str] | None = None,
             skill_plan_locked: bool = False) -> IntentResult

Result fields:
    method: canonical method key (gestalt, ifs, eft, polyvagal,
            memory_reconsolidation, nicc, boundary_stabilization,
            behavioral_activation, none)
    workbook_file: best-guess catalog filename or None
    confidence: 0.0..1.0
    action: 'offer' | 'observe' | 'defer'
    rationale: short human string (why this method + why this action)
    signals: dict of matched keyword counts per method (for tests/debug)

Design goals (per coaching-not-therapy rule):
    - never crystallize into permanent memory here
    - never call the LLM
    - never rewrite the client's frame — only *recommend*
    - respect skill-plan locks (defer if a prior plan is active)
    - dampen when the client is frame-controlling (LN's Priority Override 1)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence


METHOD_LEXICON: Dict[str, List[str]] = {
    "gestalt": [
        "empty chair", "unfinished business", "unfinished with",
        "if they were sitting", "say it to them", "dialogue with",
        "polarity", "two parts of me", "top dog", "underdog",
        "here and now", "aware of", "awareness", "figure and ground",
    ],
    "ifs": [
        "a part of me", "parts of me", "part of me feels",
        "one part wants", "another part", "protector", "manager",
        "exile", "firefighter", "self-led", "self led",
        "inner child", "younger part", "wounded part",
    ],
    "eft": [
        "we keep fighting", "same fight", "cycle with my",
        "we pursue", "she withdraws", "he withdraws", "i pursue",
        "attachment", "reach for you", "reach for him", "reach for her",
        "raw spot", "primary emotion", "underneath the anger",
    ],
    "polyvagal": [
        "shut down", "shutting down", "frozen", "can't breathe",
        "racing heart", "panic", "dysregulated", "regulate",
        "ventral", "dorsal", "sympathetic", "nervous system",
        "grounding", "orient", "safe cue",
    ],
    "memory_reconsolidation": [
        "always been this way", "core belief", "core wound",
        "the same feeling from when i was", "reminds me of when i was",
        "childhood", "little me", "when i was a kid", "growing up",
        "juxtaposition", "mismatch experience",
    ],
    "nicc": [
        "clinical protocol", "structured session", "case conceptualization",
        "treatment plan", "goals for therapy", "session agenda",
    ],
    "boundary_stabilization": [
        "boundary", "boundaries", "keeps overstepping", "won't stop",
        "keeps pushing", "how do i say no", "can't say no",
        "guilty for saying", "people please",
    ],
    "behavioral_activation": [
        "can't get out of bed", "no motivation", "haven't done",
        "avoiding", "procrastinating", "isolating", "haven't left",
        "small step", "one thing today",
    ],
}

FILENAME_HINT: Dict[str, List[str]] = {
    "gestalt": ["gestalt"],
    "ifs": ["ifs", "internal family"],
    "eft": ["eft", "emotionally focused", "eft-sm", "eft_sm"],
    "polyvagal": ["polyvagal", "vagal", "porges"],
    "memory_reconsolidation": ["reconsolid", "coherence therapy", "ecker"],
    "nicc": ["nicc", "clinical protocol"],
    "boundary_stabilization": ["boundar"],
    "behavioral_activation": ["behavioral activation", "activation"],
}

FRAME_CONTROL_MARKERS = (
    "i need you to", "don't ask me", "just give me", "stop asking",
    "not helpful", "actionable", "practical",
    "i need strategies not therapy", "don't want to talk about feelings",
)


@dataclass
class IntentResult:
    method: str = "none"
    workbook_file: Optional[str] = None
    confidence: float = 0.0
    action: str = "observe"  # 'offer' | 'observe' | 'defer'
    rationale: str = ""
    signals: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "workbook_file": self.workbook_file,
            "confidence": round(self.confidence, 3),
            "action": self.action,
            "rationale": self.rationale,
            "signals": dict(self.signals),
        }


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[’'`]", "'", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _score(text: str) -> Dict[str, int]:
    n = _normalize(text)
    out: Dict[str, int] = {}
    for method, phrases in METHOD_LEXICON.items():
        count = 0
        for p in phrases:
            if p in n:
                count += 1
        if count:
            out[method] = count
    return out


def _pick_workbook(method: str, catalog: Sequence[str]) -> Optional[str]:
    if not catalog:
        return None
    hints = FILENAME_HINT.get(method, [])
    if not hints:
        return None
    lowered = [(c, c.lower()) for c in catalog]
    for hint in hints:
        for original, low in lowered:
            if hint in low:
                return original
    return None


def _has_frame_control(text: str) -> bool:
    n = _normalize(text)
    return any(m in n for m in FRAME_CONTROL_MARKERS)


def _asked_for_a_tool(text: str) -> bool:
    n = _normalize(text)
    return any(
        p in n
        for p in (
            "what can i do", "what should i do", "give me an exercise",
            "give me a tool", "any exercises", "any workbook",
            "walk me through", "teach me", "how do i work on",
        )
    )


def classify(
    user_text: str,
    recent_texts: Optional[List[str]] = None,
    skill_plan_locked: bool = False,
    catalog: Optional[Sequence[str]] = None,
) -> IntentResult:
    """Return a coaching intent recommendation for LN.

    - If ``skill_plan_locked`` is True, the classifier will *defer* even when
      a match exists (LN is already coaching an active skill plan; don't
      pile on a second exercise).
    - If the user is frame-controlling (Override 1 territory), we downgrade
      to 'observe' — LN needs to name the dynamic before offering a tool.
    """

    text = user_text or ""
    if not text.strip():
        return IntentResult(rationale="empty input")

    signals = _score(text)
    if recent_texts:
        for t in recent_texts[-4:]:
            for m, c in _score(t or "").items():
                signals[m] = signals.get(m, 0) + c

    if not signals:
        return IntentResult(rationale="no method markers matched", signals={})

    method, count = max(signals.items(), key=lambda kv: kv[1])
    # confidence: saturates at 3 lexical hits, mild bonus if user asked for a tool
    conf = min(1.0, 0.35 + 0.20 * (count - 1))
    if _asked_for_a_tool(text):
        conf = min(1.0, conf + 0.20)

    workbook = _pick_workbook(method, catalog or [])

    if skill_plan_locked:
        return IntentResult(
            method=method,
            workbook_file=workbook,
            confidence=conf,
            action="defer",
            rationale="skill_plan_locked — hold this method in reserve; do not offer now",
            signals=signals,
        )

    if _has_frame_control(text):
        return IntentResult(
            method=method,
            workbook_file=workbook,
            confidence=conf,
            action="observe",
            rationale="frame_control_detected — mirror the dynamic first (Override 1) before offering tools",
            signals=signals,
        )

    # 'offer' gate: need either explicit tool request or >=2 strong signals
    if _asked_for_a_tool(text) or count >= 2 or conf >= 0.55:
        return IntentResult(
            method=method,
            workbook_file=workbook,
            confidence=conf,
            action="offer",
            rationale=(
                f"{count} {method} markers matched"
                + (f" and matching workbook '{workbook}'" if workbook else "")
                + "; offer as optional tool with consent"
            ),
            signals=signals,
        )

    return IntentResult(
        method=method,
        workbook_file=workbook,
        confidence=conf,
        action="observe",
        rationale=f"weak {method} signal ({count} hit) — hold and confirm before offering",
        signals=signals,
    )


def suggested_offer_line(res: IntentResult) -> str:
    """Concrete, assertive one-liner LN can lean on when action == 'offer'."""
    if res.action != "offer":
        return ""
    method_lines = {
        "gestalt": "There's a Gestalt exercise called empty-chair that fits what you're describing. Want to try it?",
        "ifs": "This sounds like a parts conversation. I can walk you through an IFS parts map if you want.",
        "eft": "You've named the cycle — pursue and withdraw. There's an EFT step that untangles it. Want the walk-through?",
        "polyvagal": "Your body is telling us something. There's a short Polyvagal reset we can do right now if you want.",
        "memory_reconsolidation": "This has the shape of an old belief loading a current moment. There's a Memory Reconsolidation step that targets that. Want to try it?",
        "nicc": "We can run this through a structured NICC checklist so nothing gets skipped. Want to?",
        "boundary_stabilization": "There's a Boundary Stabilization exercise that gives you the exact language. Want it?",
        "behavioral_activation": "One small activation step today would probably shift more than talking about it. Want me to name one?",
    }
    base = method_lines.get(res.method, "There's a workbook that fits what you're describing. Want to walk through it?")
    if res.workbook_file:
        base = base.rstrip("?") + f" (Source: {res.workbook_file})?"
    return base


__all__ = ["IntentResult", "classify", "suggested_offer_line", "METHOD_LEXICON"]
