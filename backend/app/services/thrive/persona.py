"""Per-phase system-prompt addendum for Little Nate — QUANTUM-CRYSTAL-ARCH.

Injected once per CLIENT turn behind ENABLE_GROWTH_PHASE. Kept short: the
base persona already carries LN's unconditional warmth; this only changes
*which mind leads* and what LN must not do in this phase.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.thrive.growth_phase import (
    CONSOLIDATE,
    GENERATIVE,
    PROCESS,
    STABILIZE,
    SUB_CRISIS_HOLD,
    SUB_WORKING_THROUGH,
    THRIVE,
    effective_phase,
    framework_for,
)
from app.services.thrive.practice_catalog import FOCUS_AREAS, PRACTICES

_MAX_CHARS = 1600


def _clip(text: str, n: int = _MAX_CHARS) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _focus_lines(focus_state: Optional[Dict[str, Any]]) -> List[str]:
    """focus_state: {'areas': [{'key','cadence','last_completed_at','streak'}], 'goals': [{'title','target_date','status'}], 'strengths': [..]}"""
    lines: List[str] = []
    if not focus_state:
        return lines
    areas = focus_state.get("areas") or []
    if areas:
        parts = []
        for a in areas[:4]:
            fa = FOCUS_AREAS.get(a.get("key", ""))
            if not fa:
                continue
            pr = PRACTICES.get(fa.anchor_practice)
            streak = a.get("streak")
            due = " (due)" if a.get("due") else ""
            parts.append(f"{fa.label} via {pr.label if pr else fa.anchor_practice}{due}" + (f", streak {streak}" if streak else ""))
        if parts:
            lines.append("Active focus areas: " + "; ".join(parts) + ".")
    goals = [g for g in (focus_state.get("goals") or []) if g.get("status") in (None, "active")]
    if goals:
        g = goals[0]
        tgt = f" by {g['target_date']}" if g.get("target_date") else ""
        lines.append(f"Live goal: {g.get('title')}{tgt}.")
    strengths = focus_state.get("strengths") or []
    if strengths:
        lines.append("Known signature strengths: " + ", ".join(str(s).replace("_", " ") for s in strengths[:5]) + ".")
    # phase-aware growth memory — what this person has built, harvested, completed
    memory = [m for m in (focus_state.get("thrive_memory") or []) if isinstance(m, str) and m.strip()]
    if memory:
        lines.append("Growth memory (recalled — reference naturally, never recite):")
        lines.extend(f"  • {m.strip()[:220]}" for m in memory[:4])
    # LN-led strengths interview when no signature yet (in-house, free, no survey)
    if not focus_state.get("has_signature"):
        try:
            from app.services.thrive.strengths_interview import interview_lines
            lines.extend(interview_lines(focus_state.get("strengths_answers") or {}, bool(strengths)))
        except Exception:  # module optional at import time
            pass
    return lines


def build_phase_addendum(
    phase: Optional[str],
    sub_state: Optional[str] = None,
    focus_state: Optional[Dict[str, Any]] = None,
    *,
    display_name: Optional[str] = None,
) -> str:
    """Return the addendum text for this turn ('' when nothing to add)."""
    eff = effective_phase(phase, sub_state)
    fw = framework_for(eff)
    name = display_name or "the client"
    lines: List[str] = [f"[GROWTH PHASE: {fw.label.upper()}]"]

    if sub_state == SUB_CRISIS_HOLD:
        lines.append(
            "Safety signal is active. Lead with stabilization and presence; no goal talk, no reframes toward the future until the client is steady."
        )
    elif sub_state == SUB_WORKING_THROUGH:
        lines.append(
            f"{name} asked to work something through. Shift fully into the trauma-informed mind for this arc — past→present, feelings first, EFT/EFIT steps, reconsolidation pacing. "
            "Do not rush back to goals. When the arc closes on its own (relief, meaning, a new response), gently re-open the forward direction."
        )
    elif eff == STABILIZE:
        lines.append("Regulation before exploration. Short turns, body-anchored, one thing at a time. Offer the secure base; do not open wounds.")
    elif eff == PROCESS:
        lines.append(
            f"Trauma-informed processing mind leads. Frameworks: {fw.eft}; NICC {fw.nicc}; EMDR {fw.emdr}. "
            "Track the negative cycle, access primary emotion, hold reconsolidation windows with care."
        )
    elif eff == CONSOLIDATE:
        lines.append(
            f"Integration mind leads. {fw.eft}; NICC {fw.nicc}; EMDR {fw.emdr}. "
            "Mirror what is different now, name the growth in the client's own words, and invite where the new response gets practiced first. "
            "Wound language from the client is retrospective here — meet it as evidence of healing, never as a request to reprocess."
        )
    elif eff in (THRIVE, GENERATIVE):
        lines.append(
            "POSITIVE-PSYCHOLOGY COACHING MIND LEADS. Time focus is present→future. "
            "Core questions: what do you want to build now; which goal is live; what can you complete today; what went well and what did you do to make it happen; which strength did you use. "
            "Voice: Post-Traumatic Growth (five domains), strengths-based (VIA), PERMA, broaden-and-build, mindful self-compassion, appreciative inquiry, antifragile framing (a wobble is data, not relapse; subtract what fragilizes; small bets, capped downside). "
            "Use the past strictly to identify survival skills and strengths, then return to the present 'new normal' and future goals. "
            "DO NOT steer back into childhood wounds, parts/exile work, or feelings excavation unless the client explicitly asks. "
            "Celebration and retrospective wound language ('I healed from…', 'I forgave…') are wins — respond as a champion, not a clinician. "
            "Keep your unconditional warmth; change the register from witness to collaborator."
        )
        if eff == GENERATIVE:
            lines.append("Generative edge: mentoring, giving back, legacy and shared meaning. Ask who benefits from what the client has learned.")
        lines.extend(_focus_lines(focus_state))
        lines.append(
            "Weave one practice into the conversation naturally when it fits (Three Good Things, Best Possible Self, Strength Date, Self-Compassion Break, goal ladder, antifragile review). Never assign homework lists."
        )

    return _clip("\n".join(lines))


def coach_register_note(phase: Optional[str], sub_state: Optional[str] = None) -> str:
    """One-liner for coach surfaces (briefing header, live-session guidance)."""
    eff = effective_phase(phase, sub_state)
    fw = framework_for(eff)
    if sub_state == SUB_WORKING_THROUGH:
        return f"Client is working something through (bounded return to {fw.label}). Lead with EFT/EFIT steps; hold goals for later."
    if sub_state == SUB_CRISIS_HOLD:
        return "Crisis hold active — stabilization only."
    return f"Phase {fw.label}: coach focus → {fw.coach_focus}. Register: {fw.ln_register}."
