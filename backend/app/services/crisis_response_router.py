"""
Deterministic coaching boundary post-LLM router — QUANTUM-CRYSTAL-ARCH.

Runs coaching_boundary_guard on user text, then mutates the model response so
crisis resources and stabilization are guaranteed regardless of prompt compliance.
Shared by SQR harness, bridge enrichment, and Training Ground parity tests.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.coaching_boundary_guard import TIER_COPY, evaluate as guard_evaluate

_CRISIS_988 = re.compile(r"\b988\b")
_CRISIS_741741 = re.compile(r"\b741741\b|text HOME to 741741", re.I)
_RESOURCE_SENTENCE = re.compile(
    r"(?:988|741741|Crisis Text Line|suicide prevention|crisis (?:line|text))[^.!?]*[.!?]",
    re.I,
)
_DONE_TALKING = re.compile(
    r"\b(done talking|don't want to (?:talk|discuss)|that's enough|not talking about this)\b",
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


def _has_crisis_resources(text: str) -> bool:
    return bool(_CRISIS_988.search(text or "")) and bool(_CRISIS_741741.search(text or ""))


def _ensure_crisis_resources(text: str) -> str:
    body = (text or "").strip()
    if _has_crisis_resources(body):
        return body
    block = TIER_COPY["CRISIS"]
    if not body:
        return block
    return f"{block}\n\n{body}"


def _extract_crisis_witness(model_text: str, display_name: str) -> str:
    """Keep at most two safe witness sentences from the model — no parts-work."""
    body = (model_text or "").strip()
    crisis_prefix = TIER_COPY["CRISIS"]
    if crisis_prefix in body:
        body = body.split(crisis_prefix, 1)[-1].strip()
    sentences = re.split(r"(?<=[.!?])\s+", body)
    safe: List[str] = []
    for s in sentences[:4]:
        chunk = s.strip()
        if not chunk or _CRISIS_988.search(chunk):
            continue
        if _COACHING_AFTER_CRISIS.search(chunk) or _PART_FOLLOWUP.search(chunk):
            break
        if re.search(r"\b(part|council|MasterMind|Critic|Sovereign)\b", chunk, re.I):
            break
        safe.append(chunk)
        if len(safe) >= 2:
            break
    name = (display_name or "John").strip() or "John"
    if safe:
        return " ".join(safe)
    return (
        f"{name}, what you shared carries real weight — I'm with you here, "
        f"no fixing or turning away."
    )


def _crisis_stabilization_response(
    model_text: str,
    *,
    display_name: str = "John",
) -> str:
    """BQ-5 replace-mode: witness + 988/741741 + close — suppress model coaching tail."""
    name = (display_name or "John").strip() or "John"
    witness = _extract_crisis_witness(model_text, name)
    resources = (
        "Please reach out now for immediate support: Call or text 988 (Suicide & Crisis Lifeline), "
        "available 24/7. Or text HOME to 741741 (Crisis Text Line) for steady listening."
    )
    close = f"With you, {name}."
    return f"{witness}\n\n{resources}\n\n{close}"


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


def _strip_done_talking_push(text: str, user_text: str) -> str:
    if not _DONE_TALKING.search(user_text or ""):
        return text
    sentences = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    if len(sentences) <= 1:
        return text
    # Drop trailing questions after client closed the topic
    while sentences and sentences[-1].strip().endswith("?"):
        sentences.pop()
    return " ".join(sentences).strip() if sentences else text


def _ensure_depth_boundary(text: str) -> str:
    body = (text or "").strip()
    from app.services.sqr_autocheck import _BOUNDARY_REFER

    refer = _BOUNDARY_REFER.search(body)
    if refer:
        return body
    depth = TIER_COPY["DEPTH"]
    return f"{depth}\n\n{body}" if body else depth


def apply_ln_boundary_post_guard(
    text: str,
    user_text: str,
    *,
    registry_parts: Optional[Sequence[str]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Post-generation deterministic boundary router for LN configs.
    Returns (mutated_text, hits) — hits always non-empty when guard tripped.
    """
    hits: List[Dict[str, Any]] = []
    guard = guard_evaluate(user_text or "")
    if not guard.tripped:
        out = _strip_done_talking_push(text or "", user_text or "")
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
        out = _crisis_stabilization_response(out)
    elif guard.trip_class == "DEPTH":
        out = _ensure_depth_boundary(out)
    elif guard.trip_class == "HYPO":
        hypo = TIER_COPY["HYPO"]
        if hypo.lower() not in (out or "").lower():
            out = f"{hypo}\n\n{out}".strip() if out.strip() else hypo

    out = _strip_done_talking_push(out, user_text or "")
    return out.strip(), hits
