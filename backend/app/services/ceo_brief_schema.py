"""Shared CEO Dual-COO decision brief helpers (no Redis / dual_coo imports).

# QUANTUM-CRYSTAL-ARCH — Dual-COO CEO decision briefs
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Union


def _as_lines(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        out: List[str] = []
        for item in value:
            s = str(item or "").strip()
            if s:
                out.append(s)
        return out
    s = str(value).strip()
    return [s] if s else []


def normalize_decision_fields(
    *,
    what_it_should_do: Any = None,
    what_it_should_not_be: Any = None,
    bottom_line: Any = None,
) -> Dict[str, Any]:
    do_lines = _as_lines(what_it_should_do)
    not_lines = _as_lines(what_it_should_not_be)
    bl = str(bottom_line or "").strip()
    return {
        "what_it_should_do": do_lines,
        "what_it_should_not_be": not_lines,
        "bottom_line": bl,
    }


def default_decision_fields(risk: str = "YELLOW") -> Dict[str, Any]:
    risk_u = (risk or "YELLOW").upper()
    return normalize_decision_fields(
        what_it_should_do=[
            "Record your CEO decision on this Dual-COO escalation.",
            "On APPROVE, apply any linked payload actions (when present).",
        ],
        what_it_should_not_be=[
            "Not an automatic production deploy by itself.",
            "Not a clinical Tier-2/3 claim unless the payload explicitly says so.",
        ],
        bottom_line=(
            "RED — decide promptly (ACK / APPROVE / REJECT / HOLD)."
            if risk_u == "RED"
            else "YELLOW — morning-batch review; ACK or APPROVE when ready."
        ),
    )


def merge_decision_into_payload(
    payload: Optional[Dict[str, Any]],
    decision: Dict[str, Any],
) -> Dict[str, Any]:
    """Copy decision fields onto payload for Redis / dashboard / email."""
    out = dict(payload or {})
    out["what_it_should_do"] = list(decision.get("what_it_should_do") or [])
    out["what_it_should_not_be"] = list(decision.get("what_it_should_not_be") or [])
    out["bottom_line"] = str(decision.get("bottom_line") or "")
    return out


def payload_has_decision_brief(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    bl = str(payload.get("bottom_line") or "").strip()
    do = payload.get("what_it_should_do")
    notb = payload.get("what_it_should_not_be")
    return bool(bl and (do or notb))


def format_bullets(lines: Sequence[str], *, max_items: int = 8) -> str:
    items = [str(x).strip() for x in lines if str(x).strip()][:max_items]
    if not items:
        return "(none)"
    return "\n".join(f"  - {s}" for s in items)


def format_decision_summary_block(
    *,
    objective: str,
    what_it_should_do: Union[str, Sequence[str]],
    what_it_should_not_be: Union[str, Sequence[str]],
    bottom_line: str,
    steps: Sequence[str],
    risk: str,
) -> str:
    step_lines = "\n".join(f"  {i}. {s}" for i, s in enumerate(list(steps)[:6], 1))
    return (
        f"=== WHAT HAPPENED ({risk}) ===\n{str(objective or '').strip()}\n\n"
        f"=== WHAT IT SHOULD DO ===\n{format_bullets(_as_lines(what_it_should_do))}\n\n"
        f"=== WHAT IT SHOULD NOT BE ===\n{format_bullets(_as_lines(what_it_should_not_be))}\n\n"
        f"=== BOTTOM LINE ===\n{str(bottom_line or '').strip()}\n\n"
        f"=== WHAT I NEED FROM YOU ===\n{step_lines}\n"
    )


def attach_ceo_brief_to_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Mutate item.payload with decision brief fields (sync; safe for enqueue_ceo)."""
    from app.services.ceo_inbox_notify import build_ceo_review_brief

    brief = build_ceo_review_brief(item)
    decision = normalize_decision_fields(
        what_it_should_do=brief.get("what_it_should_do"),
        what_it_should_not_be=brief.get("what_it_should_not_be"),
        bottom_line=brief.get("bottom_line"),
    )
    payload = merge_decision_into_payload(
        item.get("payload") if isinstance(item.get("payload"), dict) else {},
        decision,
    )
    # Keep ask helpers for dashboard fallbacks
    if brief.get("objective") and not payload.get("ceo_summary"):
        payload["ceo_summary"] = brief["objective"]
    if brief.get("action_steps") and not payload.get("action_steps"):
        payload["action_steps"] = list(brief["action_steps"])[:8]
    item["payload"] = payload
    item["brief"] = {
        "objective": brief.get("objective"),
        "what_it_should_do": decision["what_it_should_do"],
        "what_it_should_not_be": decision["what_it_should_not_be"],
        "bottom_line": decision["bottom_line"],
        "action_steps": brief.get("action_steps"),
        "summary_block": brief.get("summary_block"),
    }
    return item
