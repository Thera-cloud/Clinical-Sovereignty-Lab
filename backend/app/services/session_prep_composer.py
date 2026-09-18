"""Client-specific View Brief session-prep talking points.

Growth keeps the phase framework. Memory keeps crystals. Prep is the
coach's next-hour direction from what Little Nate already heard.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

_GENERIC_CRYSTAL = re.compile(
    r"here(?:'s| is) the (?:synthesized |crystallized )?insight"
    r"|insight crystal"
    r"|after analyzing the provided knowledge"
    r"|crystallized insight for the",
    re.I,
)
_FRAMEWORK_LINE = re.compile(
    r"^(register:|eft:|watch for:|time focus|companion into the wound)",
    re.I,
)
_WS = re.compile(r"\s+")


def _plain(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, dict):
        for key in (
            "text", "summary", "content_summary", "user", "user_text",
            "topic_summary", "note", "harvest",
        ):
            val = raw.get(key)
            if val:
                return _plain(val)
        return ""
    return _WS.sub(" ", str(raw)).strip()


def _clip(text: str, n: int = 100) -> str:
    t = _plain(text)
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0].rstrip(".,;:")
    return (cut or t[:n]) + "…"


def _is_generic_crystal(text: str) -> bool:
    t = _plain(text)
    if len(t) < 24:
        return True
    return bool(_GENERIC_CRYSTAL.search(t))


def _last_user_lines(turns: Iterable[Any], n: int = 3, min_len: int = 18) -> List[str]:
    out: List[str] = []
    for raw in reversed(list(turns or [])):
        if not isinstance(raw, dict):
            continue
        user = _plain(raw.get("user") or raw.get("user_text") or raw.get("preview"))
        if len(user) < min_len or user.startswith("{") or user.startswith("["):
            continue
        out.append(user)
        if len(out) >= n:
            break
    out.reverse()
    return out


def _risk(metrics: Any) -> str:
    if not isinstance(metrics, dict):
        return ""
    return str(
        metrics.get("risk_level")
        or (metrics.get("nevedal_state") or {}).get("risk_level")
        or ""
    ).upper()


def _mood_trend(metrics: Any) -> str:
    if not isinstance(metrics, dict):
        return ""
    return str(
        metrics.get("mood_trend")
        or metrics.get("moodTrend")
        or ""
    ).lower()


def _reconsolidation(metrics: Any) -> float:
    if not isinstance(metrics, dict):
        return 0.0
    pmb = metrics.get("pmb")
    if not isinstance(pmb, dict):
        return 0.0
    try:
        return float(pmb.get("reconsolidation_readiness") or 0)
    except (TypeError, ValueError):
        return 0.0


def compose_session_prep_points(
    brief: Optional[Dict[str, Any]],
    thrive: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Directional prep lines. Never the Growth EFT/register slogans."""
    brief = brief or {}
    thrive = thrive or {}
    points: List[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        line = _plain(raw)
        if not line or _FRAMEWORK_LINE.search(line):
            return
        key = line.lower()[:90]
        if key in seen:
            return
        seen.add(key)
        points.append(line)

    last_lines = _last_user_lines(brief.get("recent_conversations") or [])
    if last_lines:
        add(
            f"Open on what they last brought: “{_clip(last_lines[-1], 88)}” "
            "— stay there; don't start a new map."
        )
        if len(last_lines) > 1:
            add(
                f"Second thread still live: “{_clip(last_lines[-2], 80)}”. "
                "Name it only if the first one lands."
            )

    focus = _plain(brief.get("session_focus"))
    if focus:
        add(f"They already named this hour: {_clip(focus, 100)}.")

    summaries = brief.get("prior_session_summaries") or []
    if summaries:
        leftover = _plain(summaries[0])
        if leftover:
            add(
                f"Last session leftover: {_clip(leftover, 100)}. "
                "Ask what landed, not what you taught."
            )

    for crystal in brief.get("crystal_memory") or []:
        text = _plain(crystal)
        if _is_generic_crystal(text):
            continue
        domain = ""
        if isinstance(crystal, dict):
            domain = _plain(crystal.get("domain"))
        tag = f" ({domain})" if domain and domain not in ("general", "clinical") else ""
        add(
            f"LN already holds this{tag}: {_clip(text, 92)}. "
            "Use it as the through-line; Memory has the rest."
        )
        break

    breakthroughs = brief.get("recent_breakthroughs") or []
    if breakthroughs:
        last_br = breakthroughs[-1]
        br_text = _plain(last_br)
        if br_text and not _is_generic_crystal(br_text):
            add(f"Build on what they already realized: “{_clip(br_text, 80)}”.")

    for goal in (thrive.get("goals_active") or [])[:1]:
        if not isinstance(goal, dict):
            continue
        gtext = _plain(goal.get("text"))
        if not gtext:
            continue
        pct = goal.get("progress_pct")
        pct_s = f" ({int(pct)}%)" if isinstance(pct, (int, float)) else ""
        add(
            f"Growth already has a goal{pct_s}: “{_clip(gtext, 72)}”. "
            "Check it. Don't invent a new one."
        )

    harvests = thrive.get("recent_harvest") or []
    if harvests:
        h0 = harvests[0]
        htext = _plain(h0.get("harvest") if isinstance(h0, dict) else h0)
        key = _plain(h0.get("practice_key") if isinstance(h0, dict) else "")
        if htext:
            label = key.replace("_", " ") if key else "a practice"
            add(
                f"They already practiced {label}: {_clip(htext, 80)}. "
                "Ask what shifted."
            )

    metrics = brief.get("metrics") if isinstance(brief.get("metrics"), dict) else {}
    risk = _risk(metrics)
    if risk in ("HIGH", "CRITICAL", "CRISIS"):
        add("Safety first this hour — last-session carryover before any growth talk.")
    if _mood_trend(metrics) in ("declining", "down", "worsening"):
        add("Mood is sliding — name that before technique.")
    if _reconsolidation(metrics) >= 0.6:
        add(
            "Reconsolidation window is open — stay in the charge they named, "
            "don't soothe it away."
        )

    homework = brief.get("pending_homework") or []
    if homework:
        hw = homework[0]
        add(f"Homework still open: {_clip(hw, 80)}. Close or drop it on purpose.")

    if not points:
        turns = brief.get("recent_conversations") or []
        intake = brief.get("intake_summary") if isinstance(brief.get("intake_summary"), dict) else {}
        has_intake = bool(intake.get("has_any_answers")) or int(
            intake.get("section_1_completion_pct") or 0
        ) > 0
        if not turns:
            add(
                "LN has no personal thread yet. Open with why they booked, "
                "then one feeling, then stop talking."
            )
        if not has_intake:
            add("Intake is still blank — one question about what they need from this hour.")
        if not points:
            add("Follow their first sentence. Framework stays on Growth, not in your opening.")

    return points[:6]
