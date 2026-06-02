"""Chat scheduling assistant for Little Nate.

Intercepts client chat turns that express scheduling intent ("book with my
coach", "what times are open") and returns machine-readable slots computed from
the single source of truth (coach_slot_engine.compute_available_slots). The LLM
never invents times; it only narrates the system-provided slot list.

handle_turn() returns: {handled, response, payload}
  - handled=False  -> not a scheduling turn; caller should fall through to the LLM.
  - handled=True   -> caller emits `response` as nate_response and, if present,
                      `payload` as a structured frame (type=scheduling_slots).

This module is import-safe (no bridge import at module load) and never raises to
the caller — failures degrade to handled=False so chat continues normally.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Callable, Optional

try:
    from app.services.coach_slot_engine import compute_available_slots, DEFAULT_TZ
except Exception:  # pragma: no cover - defensive
    compute_available_slots = None  # type: ignore
    DEFAULT_TZ = "America/New_York"

# Scheduling intent: needs a scheduling verb/noun AND a coach/session referent,
# OR an explicit availability question. Kept tight to avoid hijacking therapy talk.
_BOOK_VERBS = re.compile(
    r"\b(book|schedule|set\s*up|reserve|make|arrange)\b", re.IGNORECASE
)
_SESSION_NOUNS = re.compile(
    r"\b(session|appointment|appt|meeting|call|time)\b", re.IGNORECASE
)
_COACH_REF = re.compile(r"\b(coach|my\s+coach)\b", re.IGNORECASE)
_AVAIL_Q = re.compile(
    r"\b(what|which|when)\b.{0,40}\b(times?|slots?|avail\w*|open|free)\b"
    r"|\b(avail\w*|open\s+slots?|free\s+times?)\b",
    re.IGNORECASE,
)
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def detect_intent(text: str) -> Optional[str]:
    """Return 'schedule' if the message expresses scheduling intent, else None."""
    if not text:
        return None
    t = text.strip()
    if len(t) > 400:  # long disclosures are therapy, not scheduling
        return None
    has_book = bool(_BOOK_VERBS.search(t) and (_SESSION_NOUNS.search(t) or _COACH_REF.search(t)))
    has_avail = bool(_AVAIL_Q.search(t) and (_COACH_REF.search(t) or _SESSION_NOUNS.search(t)))
    if has_book or has_avail:
        return "schedule"
    return None


def resolve_coach(profile: dict) -> str:
    """Coach hardware id: profile coach_id then assigned_coach_id."""
    if not profile:
        return ""
    return (
        (profile.get("coach_id") or "")
        or (profile.get("assigned_coach_id") or "")
    ).strip()


def _coach_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(DEFAULT_TZ)
    except Exception:
        return None


def parse_target_date(text: str) -> Optional[str]:
    """Extract an ISO date (coach-local) from natural language. None if absent."""
    if not text:
        return None
    t = text.lower()
    tz = _coach_tz()
    today = _dt.datetime.now(tz).date() if tz else _dt.date.today()

    # Explicit ISO date.
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", t)
    if m:
        return m.group(1)

    if re.search(r"\btoday\b", t):
        return today.isoformat()
    if re.search(r"\btomorrow\b", t):
        return (today + _dt.timedelta(days=1)).isoformat()

    # "next <weekday>" / "<weekday>" -> next occurrence (today counts if named).
    for name, idx in _WEEKDAYS.items():
        if re.search(r"\b" + name + r"\b", t):
            delta = (idx - today.weekday()) % 7
            if delta == 0 and "next" in t:
                delta = 7
            return (today + _dt.timedelta(days=delta)).isoformat()

    return None


def _fmt_slot_label(iso_start: str) -> str:
    try:
        dt = _dt.datetime.fromisoformat(iso_start)
        return dt.strftime("%-I:%M %p")
    except Exception:
        return iso_start


def _coach_name(profile: dict, registry_loader: Optional[Callable[[], dict]], coach_hw_id: str) -> str:
    if registry_loader is None:
        return "your coach"
    try:
        reg = registry_loader() or {}
        for _k, _v in reg.items():
            p = (_v or {}).get("profile", {})
            if p.get("hardware_id") == coach_hw_id and p.get("role") == "COACH":
                return p.get("name") or p.get("username") or "your coach"
    except Exception:
        pass
    return "your coach"


async def handle_turn(
    profile: dict,
    text: str,
    db_pool: Any,
    registry_loader: Optional[Callable[[], dict]] = None,
) -> dict:
    """Process a client chat turn for scheduling. See module docstring for contract."""
    miss = {"handled": False, "response": "", "payload": None}
    try:
        if detect_intent(text) != "schedule":
            return miss
        if compute_available_slots is None or not db_pool:
            return miss

        coach_hw_id = resolve_coach(profile)
        if not coach_hw_id:
            return {
                "handled": True,
                "response": (
                    "I'd love to help you set up a session, but I don't see a coach "
                    "assigned to your account yet. Reach out to support and we'll get "
                    "you matched."
                ),
                "payload": None,
            }

        coach_name = _coach_name(profile, registry_loader, coach_hw_id)
        target_date = parse_target_date(text)
        if not target_date:
            return {
                "handled": True,
                "response": (
                    f"Happy to help you schedule with {coach_name}. Which day works "
                    "for you — today, tomorrow, or a specific weekday?"
                ),
                "payload": None,
            }

        engine = await compute_available_slots(
            db_pool, coach_hw_id, target_date, registry_loader=registry_loader
        )
        if engine.get("error") == "coach_not_found":
            return {
                "handled": True,
                "response": "I couldn't find your coach's calendar right now. Please try again shortly.",
                "payload": None,
            }
        if engine.get("error"):
            return miss

        slots = engine.get("available_slots") or []
        try:
            pretty_date = _dt.date.fromisoformat(target_date).strftime("%A, %b %-d")
        except Exception:
            pretty_date = target_date

        if not slots:
            return {
                "handled": True,
                "response": (
                    f"{coach_name} doesn't have any open times on {pretty_date}. "
                    "Want me to check another day?"
                ),
                "payload": {
                    "type": "scheduling_slots",
                    "surface": "chat",
                    "coach_id": coach_hw_id,
                    "coach_name": coach_name,
                    "date": target_date,
                    "slots": [],
                },
            }

        labels = ", ".join(_fmt_slot_label(s["start"]) for s in slots[:6])
        more = "" if len(slots) <= 6 else f" (and {len(slots) - 6} more)"
        response = (
            f"Here are {coach_name}'s open times on {pretty_date}: {labels}{more}. "
            "Tap a time to request it — I'll send the request to your coach for approval."
        )
        return {
            "handled": True,
            "response": response,
            "payload": {
                "type": "scheduling_slots",
                "surface": "chat",
                "coach_id": coach_hw_id,
                "coach_name": coach_name,
                "date": target_date,
                "slots": slots,
            },
        }
    except Exception:
        return miss
