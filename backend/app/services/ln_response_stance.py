"""Little Nate assertive-stance addon.

Purpose:
    Curb the over-reflection / constant mirror-question pattern clients report
    ("LN keeps handing everything back to me instead of engaging"). The addon
    is a *system prompt fragment* injected additively into LN's system prompt,
    behind the ``ENABLE_LN_ASSERTIVE_STANCE`` flag (default: on).

Design:
    - We do NOT edit LN's core personality prompt in bridge_server.py. This
      module returns a string that the bridge appends after the existing
      COACHING WORKBOOK TOOLS block.
    - The addon consumes the workbook intent classifier's recommendation and
      turns it into a concrete instruction ("offer this tool now" vs "hold").
    - It also enforces a hard "one reflection question per turn" ceiling and
      names the classical replacements (direct observation, one concrete
      option, silence).
"""

from __future__ import annotations

import os
from typing import Optional

try:
    from app.services.workbook_intent_classifier import (
        IntentResult,
        suggested_offer_line,
    )
except Exception:  # pragma: no cover - defensive import
    IntentResult = None  # type: ignore[assignment]

    def suggested_offer_line(_res) -> str:  # type: ignore[return-value]
        return ""


STANCE_FLAG_ENV = "ENABLE_LN_ASSERTIVE_STANCE"


def is_enabled() -> bool:
    val = (os.getenv(STANCE_FLAG_ENV) or "true").strip().lower()
    return val in ("1", "true", "yes", "on")


BASE_STANCE = (
    "ASSERTIVE COACHING STANCE (this block overrides any tendency to mirror everything back): "
    "1) MAX ONE reflection question per turn. If you already reflected once, do NOT add "
    "'what's coming up for you?', 'how does that land?', 'tell me more about that', or any "
    "variant. Instead: name what you actually observe, or offer a concrete next move. "
    "2) DIRECT NAMING beats open questions. If you see a pattern, say the pattern. "
    "'You are describing the third night this week you couldn't sleep before a Sunday call "
    "with your mother' beats 'what do you notice about your sleep?'. "
    "3) OFFER something when it fits. Coaching = you have tools; use them. When the workbook "
    "intent classifier below flags a method with action=offer, name the tool by file and "
    "invite consent in the SAME turn. Do not spend another turn 'sitting with' the feeling "
    "before offering. "
    "4) SILENCE is a valid move. If the moment is heavy, one sentence of witnessing + a "
    "period is better than a question. Do not fill space to prove you are present. "
    "5) NEVER force a body-check, breathwork, or grounding as your default fallback. Only "
    "offer somatic tools when the client's message actually points at the body."
)


def _fmt_intent(intent: Optional[object]) -> str:
    if intent is None:
        return "COACHING INTENT: none — no workbook match; coach directly without a named tool."
    try:
        method = getattr(intent, "method", "none")
        action = getattr(intent, "action", "observe")
        conf = float(getattr(intent, "confidence", 0.0) or 0.0)
        wb = getattr(intent, "workbook_file", None)
        rationale = getattr(intent, "rationale", "") or ""
    except Exception:
        return "COACHING INTENT: parse-error — coach directly without a named tool."

    if action == "offer":
        line = suggested_offer_line(intent) if IntentResult is not None else ""
        wb_part = f" (source: {wb})" if wb else ""
        return (
            "COACHING INTENT: method=" + method + f" confidence={conf:.2f} action=OFFER{wb_part}. "
            "Rationale: " + rationale + ". "
            "IN THIS TURN: after your one direct observation, offer this tool with consent. "
            "Suggested line (adapt in your own voice, do not read verbatim): " + (line or "")
        )
    if action == "defer":
        return (
            "COACHING INTENT: method=" + method + f" confidence={conf:.2f} action=DEFER. "
            "A prior skill plan is active — do NOT introduce a new method this turn. "
            "Continue the current plan or check progress."
        )
    return (
        "COACHING INTENT: method=" + method + f" confidence={conf:.2f} action=OBSERVE. "
        "Rationale: " + rationale + ". "
        "IN THIS TURN: do not offer a workbook. Name what you see, ask AT MOST one question."
    )


def stance_block(intent: Optional[object] = None) -> str:
    """Return the assertive-stance system-prompt fragment.

    ``intent`` should be a ``IntentResult`` from
    ``workbook_intent_classifier.classify(...)`` or ``None``.
    """

    if not is_enabled():
        return ""
    return BASE_STANCE + "\n\n" + _fmt_intent(intent)


__all__ = ["stance_block", "is_enabled", "BASE_STANCE", "STANCE_FLAG_ENV"]
