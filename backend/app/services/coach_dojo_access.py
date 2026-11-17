"""Paid DOJO map. Empty when the profile has neither a map nor selected_dojos."""

import json
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


def _as_dict(profile: Any) -> Dict[str, Any]:
    if isinstance(profile, dict):
        return profile
    if isinstance(profile, str) and profile:
        try:
            parsed = json.loads(profile)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def active_dojo_keys(profile: Any, blocked: Optional[Iterable[str]] = None) -> List[str]:
    """DOJOs the coach may use. Does not invent therapist. Does not mutate the profile."""
    data = _as_dict(profile)
    blocked_set = {str(item) for item in (blocked or []) if item}
    subs = data.get("dojo_subscriptions")
    keys: List[str] = []
    if isinstance(subs, dict) and subs:
        today = date.today()
        for key, sub in subs.items():
            name = str(key)
            if isinstance(sub, dict):
                status = str(sub.get("status") or "expired")
                if status == "active":
                    keys.append(name)
                elif status == "cancelled":
                    access_end = sub.get("access_end_date")
                    if not access_end:
                        keys.append(name)
                        continue
                    try:
                        end = datetime.strptime(str(access_end), "%Y-%m-%d").date()
                    except (TypeError, ValueError):
                        continue
                    if today <= end:
                        keys.append(name)
            elif sub is True:
                keys.append(name)
    else:
        selected = data.get("selected_dojos") or []
        if isinstance(selected, list):
            keys = [str(item) for item in selected if item]
    return [key for key in keys if key not in blocked_set]


def gate_mentor_start(profile: Any, requested: Any, blocked: Optional[Iterable[str]] = None):
    """Paid keys the coach asked for. An empty result is an error, not a therapist fallback."""
    paid = set(active_dojo_keys(profile, blocked))
    asked = [str(item) for item in (requested or []) if item]
    allowed = [key for key in asked if key in paid]
    if not allowed:
        return [], "DOJO_NOT_SUBSCRIBED"
    return allowed, ""


def patch_future_sessions(
    sessions: List[Dict[str, Any]],
    old_ids: Iterable[str],
    new_id: str,
    *,
    now: Optional[datetime] = None,
    restore_from: Optional[str] = None,
    hold_tag: Optional[str] = None,
) -> bool:
    """Move future unstarted sessions. A session that already started stays."""
    old = {str(item) for item in old_ids if item}
    if not new_id or not isinstance(sessions, list):
        return False
    moment = now or datetime.now(timezone.utc)
    changed = False
    for session in sessions:
        if not isinstance(session, dict):
            continue
        if session.get("actual_start"):
            continue
        status = str(session.get("status") or "").lower()
        if status in ("active", "in_progress", "completed", "cancelled", "canceled"):
            continue
        start = session.get("scheduled_start")
        if not start:
            continue
        try:
            when = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when <= moment:
            continue
        coach_id = str(session.get("coach_id") or "")
        if restore_from:
            if coach_id not in old:
                continue
            if str(session.get("hold_from") or "") != restore_from:
                continue
            session["coach_id"] = new_id
            session.pop("hold_from", None)
            changed = True
            continue
        if coach_id not in old:
            continue
        session["hold_from"] = hold_tag or coach_id
        session["coach_id"] = new_id
        session["zoom_link"] = ""
        session["zoom_meeting_id"] = ""
        session["zoom_host_url"] = ""
        changed = True
    return changed
