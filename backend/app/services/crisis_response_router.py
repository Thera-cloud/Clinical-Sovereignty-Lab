"""
Deterministic coaching boundary post-LLM router — QUANTUM-CRYSTAL-ARCH.

Runs coaching_boundary_guard on user text, then mutates the model response so
crisis resources and stabilization are guaranteed regardless of prompt compliance.
Shared by SQR harness, bridge enrichment, and Training Ground parity tests.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.coaching_boundary_guard import (
    TIER_COPY,
    TIER_COPY_GENERIC,
    GuardResult,
    crisis_tier_copy_for_profile,
    evaluate as guard_evaluate,
)
from app.services.council_registry_context import _CRISIS_USER  # noqa: PLC2701

_CRISIS_988 = re.compile(r"\b988\b")
_CRISIS_741741 = re.compile(r"\b741741\b|text HOME to 741741", re.I)
_RESOURCE_SENTENCE = re.compile(
    r"(?:988|741741|838255|Copline|Veterans Crisis Line|press\s*1|"
    r"Crisis Text Line|suicide prevention|crisis (?:line|text))[^.!?]*[.!?]",
    re.I,
)
_DONE_TALKING = re.compile(
    r"\b(done talking|don't want to (?:talk|discuss)|that's enough|not talking about this)\b"
    r"|\bwhatever\b[\s.,!]*\bit'?s fine\b",
    re.I,
)
_STIFF_EXIT = re.compile(
    r"\b(I acknowledge your (?:decision|choice) to (?:stop|conclude)|"
    r"The door remains open|I hear that you(?:'re| are) ready to stop)\b",
    re.I,
)
_EXERCISE_OFFER = re.compile(
    r"\b(grounding|breath(?:ing|e)? (?:practice|exercise|cycle)|body scan|"
    r"try (?:this|a) (?:practice|exercise|technique)|micro[- ]practice|"
    r"inhale|exhale|five senses|5-4-3-2-1|60[- ]second)\b",
    re.I,
)
_PART_FOLLOWUP = re.compile(
    r"\b(how (?:is|are)|what (?:is|are)|tell me about|checking in with)\b",
    re.I,
)
_COACHING_AFTER_CRISIS = re.compile(
    r"\b("
    r"grounding|breath(?:ing)? (?:cycle|exercise)|name the (?:Critic|part)|"
    r"inner council|Spot it quick|Hey,?\s*Critic|micro[- ]practice|"
    r"60[- ]second|jot a (?:single )?pro"
    r")\b",
    re.I,
)


def _has_crisis_resources(text: str, profile: Optional[Dict[str, Any]] = None) -> bool:
    # QUANTUM-CRYSTAL-ARCH: population-aware resource detection
    try:
        from app.services.crisis_resource_registry import has_crisis_resources_in_text

        return has_crisis_resources_in_text(text, profile)
    except Exception:
        return bool(_CRISIS_988.search(text or "")) and bool(_CRISIS_741741.search(text or ""))


def _ensure_crisis_resources(text: str, profile: Optional[Dict[str, Any]] = None) -> str:
    body = (text or "").strip()
    if _has_crisis_resources(body, profile):
        return body
    block = crisis_tier_copy_for_profile(profile)
    if not body:
        return block
    return f"{block}\n\n{body}"


def _extract_crisis_witness(model_text: str, display_name: str) -> str:
    """Keep at most two safe witness sentences from the model — no coaching, no questions."""
    body = (model_text or "").strip()
    crisis_prefix = TIER_COPY["CRISIS"]
    if crisis_prefix in body:
        body = body.split(crisis_prefix, 1)[-1].strip()
    sentences = re.split(r"(?<=[.!?])\s+", body)
    safe: List[str] = []
    for s in sentences[:5]:
        chunk = s.strip()
        if not chunk or _CRISIS_988.search(chunk) or _CRISIS_741741.search(chunk):
            continue
        if chunk.endswith("?"):
            break
        if _COACHING_AFTER_CRISIS.search(chunk):
            break
        # Part names are allowed inside a witness sentence (mirroring what the client
        # said) — but not as a coaching move ("check in with the Critic…").
        if _PART_FOLLOWUP.search(chunk) and re.search(
            r"\b(part|council|MasterMind|Critic|Sovereign)\b", chunk, re.I
        ):
            break
        safe.append(chunk)
        if len(safe) >= 2:
            break
    name = (display_name or "John").strip() or "John"
    if len(safe) >= 2:
        return " ".join(safe)
    fallback = (
        f"{name}, I hear how much pain is behind those words — this isn't something "
        f"you should carry alone another minute. Nothing about what you just said "
        f"scares me away; I'm right here with you."
    )
    if len(safe) == 1:
        return f"{safe[0]} I'm right here with you, and I'm not going anywhere."
    return fallback


_DOOR_OPEN_LINE = (
    "And if things get heavier again — 988 is there any time, day or night, no waiting."
)


def _append_resource_door(text: str, profile: Optional[Dict[str, Any]] = None) -> str:
    """Q7/Q8 fix: keep a one-line resource reminder open on the turn right after a
    crisis flag, even when the follow-up turn itself doesn't re-trip the guard."""
    body = (text or "").strip()
    try:
        from app.services.crisis_resource_registry import door_open_copy

        door = door_open_copy(profile)
    except Exception:
        door = _DOOR_OPEN_LINE
    if _has_crisis_resources(body, profile) or _CRISIS_988.search(body):
        return body
    if not body:
        return door
    return f"{body}\n\n{door}"


def _crisis_stabilization_response(
    model_text: str,
    *,
    display_name: str = "John",
    profile: Optional[Dict[str, Any]] = None,
) -> str:
    """BQ-5 replace-mode: attunement + direct safety question + population resources."""
    name = (display_name or "John").strip() or "John"
    witness = _extract_crisis_witness(model_text, name)
    safety_question = (
        "I need to ask you directly, because it matters: are you having thoughts of "
        "hurting yourself or ending your life right now?"
    )
    try:
        from app.services.crisis_resource_registry import stabilization_resources_copy

        resources = stabilization_resources_copy(profile)
    except Exception:
        resources = (
            "Please reach out now for immediate support: Call or text 988 (Suicide & Crisis Lifeline), "
            "available 24/7. Or text HOME to 741741 (Crisis Text Line) for steady listening."
        )
    close = (
        "Those lines exist for exactly this moment — a real person, right now. "
        "I'm not going anywhere either — how you're doing on this matters to me, "
        "and I'll keep checking in."
    )
    return f"{witness}\n\n{safety_question}\n\n{resources}\n\n{close}"


def _last_resource_end(text: str) -> int:
    end = 0
    for m in _RESOURCE_SENTENCE.finditer(text or ""):
        end = max(end, m.end())
    return end


def _strip_post_crisis_coaching(
    text: str,
    registry_parts: Optional[Sequence[str]] = None,
) -> str:
    """BQ-5: stabilization + resources only — drop parts-work tail after crisis block."""
    body = (text or "").strip()
    if not body:
        return body
    cut = _last_resource_end(body)
    if cut <= 0:
        return body
    head = body[:cut].strip()
    tail = body[cut:].strip()
    if not tail:
        return head
    approved = {p for p in (registry_parts or []) if p}
    for name in approved:
        if name == "Sovereign":
            if re.search(r"\bSovereign\b(?!\s+Sanctuary)", tail, re.I):
                return head
        elif re.search(rf"\b{re.escape(name)}\b", tail, re.I):
            return head
    if _PART_FOLLOWUP.search(tail) and "?" in tail:
        return head
    if re.search(r"\b(part|council|MasterMind|Critic|Sovereign)\b", tail, re.I) and "?" in tail:
        return head
    return body


def recent_crisis_in_conversation(
    user_text: str,
    history: Optional[Sequence[Dict[str, str]]] = None,
    *,
    lookback_user_turns: int = 6,
) -> bool:
    if _CRISIS_USER.search(user_text or ""):
        return True
    if not history:
        return False
    user_msgs = [
        m.get("content", "")
        for m in history
        if (m.get("role") or "").lower() == "user"
    ]
    for t in user_msgs[-lookback_user_turns:]:
        if _CRISIS_USER.search(t or ""):
            return True
    return False


def _disengagement_exit(*, recent_crisis: bool) -> str:
    if recent_crisis:
        return (
            "Okay. The line's still there tonight if the Critic gets loud — 988. "
            "I'm here when you come back."
        )
    return "Okay. I'm here whenever you want to pick it back up."


def _strip_done_talking_push(
    text: str,
    user_text: str,
    *,
    recent_crisis: bool = False,
) -> str:
    """Disengagement = warm exit; crisis-adjacent exits keep 988 within reach."""
    if not _DONE_TALKING.search(user_text or ""):
        return text
    if recent_crisis:
        return _disengagement_exit(recent_crisis=True)
    body = (text or "").strip()
    if _STIFF_EXIT.search(body) or _EXERCISE_OFFER.search(body):
        return _disengagement_exit(recent_crisis=False)
    sentences = re.split(r"(?<=[.!?])\s+", body)
    if len(sentences) <= 1 and "?" not in body:
        return body
    kept: List[str] = []
    for s in sentences:
        chunk = s.strip()
        if not chunk:
            continue
        if chunk.endswith("?"):
            continue
        if _EXERCISE_OFFER.search(chunk):
            continue
        kept.append(chunk)
        if len(kept) >= 2:
            break
    if not kept or _STIFF_EXIT.search(body):
        return _disengagement_exit(recent_crisis=False)
    merged = " ".join(kept).strip()
    if len(merged.split()) > 18:
        return _disengagement_exit(recent_crisis=False)
    return merged


def _strip_routine_crisis_resources(text: str, user_text: str) -> str:
    """Remove 988/741741 blocks when the user turn is not crisis language (E-set bleed)."""
    if _CRISIS_USER.search(user_text or ""):
        return (text or "").strip()
    sentences = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    kept = [
        s for s in sentences
        if s.strip()
        and not _CRISIS_988.search(s)
        and not _CRISIS_741741.search(s)
        and not re.search(r"\bCrisis Text Line\b", s, re.I)
        and not re.search(r"\bSuicide & Crisis Lifeline\b", s, re.I)
    ]
    return " ".join(kept).strip() if kept else (text or "").strip()


def _ensure_depth_boundary(text: str, *, has_parts_context: bool) -> str:
    body = (text or "").strip()
    from app.services.sqr_autocheck import _BOUNDARY_REFER

    refer = _BOUNDARY_REFER.search(body)
    if refer:
        return body
    depth = TIER_COPY["DEPTH"] if has_parts_context else TIER_COPY_GENERIC["DEPTH"]
    return f"{depth}\n\n{body}" if body else depth


def apply_ln_boundary_post_guard(
    text: str,
    user_text: str,
    *,
    registry_parts: Optional[Sequence[str]] = None,
    conversation_history: Optional[Sequence[Dict[str, str]]] = None,
    force_crisis: bool = False,
    profile: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Post-generation deterministic boundary router for LN configs.
    Returns (mutated_text, hits) — hits always non-empty when guard tripped.

    force_crisis: set True when an upstream, higher-recall detector (e.g. the
    Public Trial Funnel's semantic SI check) has already flagged this turn as
    a crisis but the lexicon-only `guard_evaluate()` below did not independently
    agree. 2026-07 trial audit (T12): three consecutive real-user phrasings of
    passive suicidal ideation defeated lexicon matching, and the resulting
    response *engaged the ideation as a topic to debate* instead of triggering
    stabilization — because this function's own internal `match_user_text()`
    call also missed the same phrasing the upstream check caught. Without this
    flag, an upstream semantic catch never reaches the actual response content.
    """
    hits: List[Dict[str, Any]] = []
    has_parts_context = bool(registry_parts)
    recent_crisis = recent_crisis_in_conversation(
        user_text or "",
        conversation_history,
    )
    # Narrow lookback (immediately-prior turn only) for the "door stays open"
    # resource reminder — 2026-07 trial audit Q8 fix. Avoids nagging every turn
    # for the rest of a long conversation while still covering the very next
    # reply after a crisis flag, which is where Q8 failed.
    door_open_recent = recent_crisis_in_conversation(
        user_text or "",
        conversation_history,
        lookback_user_turns=1,
    )
    guard = guard_evaluate(user_text or "")
    if force_crisis and not guard.tripped:
        guard = GuardResult(
            tripped=True,
            trip_class="CRISIS",
            trigger_class="semantic_si_detector",
            matched_labels=["semantic_si_match"],
            priority=1,
        )
    if not guard.tripped:
        out = _strip_done_talking_push(
            text or "",
            user_text or "",
            recent_crisis=recent_crisis,
        )
        if door_open_recent and not _DONE_TALKING.search(user_text or ""):
            out = _append_resource_door(out, profile)
        return out, hits

    hits.append({
        "guard_id": "coaching_boundary_guard",
        "trip_class": guard.trip_class,
        "trigger_class": guard.trigger_class,
        "matched_labels": list(guard.matched_labels),
    })

    out = text or ""
    if guard.trip_class == "CRISIS":
        # Replace-mode: crisis turns end after stabilization — no parts-work tail (BQ-5).
        out = _crisis_stabilization_response(out, profile=profile)
    elif guard.trip_class == "DEPTH":
        out = _ensure_depth_boundary(out, has_parts_context=has_parts_context)
        out = _strip_routine_crisis_resources(out, user_text or "")
    elif guard.trip_class == "HYPO":
        hypo = TIER_COPY["HYPO"] if has_parts_context else TIER_COPY_GENERIC["HYPO"]
        if hypo.lower() not in (out or "").lower():
            out = f"{hypo}\n\n{out}".strip() if out.strip() else hypo

    out = _strip_done_talking_push(
        out,
        user_text or "",
        recent_crisis=recent_crisis,
    )
    return out.strip(), hits
