"""Coach Schedule reschedule — past slots stay locked for reflection + billing."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

RESCHEDULE_ELIGIBLE = frozenset({"scheduled", "active"})
PAST_LOCKED_STATUSES = frozenset({
    "scheduled", "active", "pending_approval", "completed", "no_show",
    "rescheduled", "cancelled", "cancelled_by_google",
})
REMINDER_TYPES = (
    "reminder_24h",
    "reminder_72h",
    "reminder_48h",
    "48h_reminder",
)


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return as_utc(value)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return as_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except Exception:
        return None


def is_past_locked(scheduled_start: Any, now: Optional[datetime] = None) -> bool:
    """True once the appointment instant has passed — calendar day leftovers stay locked."""
    start = parse_iso_dt(scheduled_start)
    if start is None:
        return False
    now_utc = as_utc(now) or datetime.now(timezone.utc)
    return start <= now_utc


def duration_minutes(session: Dict[str, Any], default: int = 50) -> int:
    try:
        raw = int(session.get("duration_minutes") or 0)
    except (TypeError, ValueError):
        raw = 0
    if raw >= 5:
        return raw
    start = parse_iso_dt(session.get("scheduled_start"))
    end = parse_iso_dt(session.get("scheduled_end"))
    if start and end and end > start:
        return max(5, int((end - start).total_seconds() / 60))
    return default


def mark_old_rescheduled(
    old: Dict[str, Any],
    *,
    new_session_id: str,
    actor: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    stamp = (as_utc(now) or datetime.now(timezone.utc)).isoformat()
    sd = old.get("session_data")
    if not isinstance(sd, dict):
        sd = {}
    else:
        sd = dict(sd)
    sd.update({
        "rescheduled_to": new_session_id,
        "rescheduled_at": stamp,
        "rescheduled_by": actor,
        "original_scheduled_start": str(old.get("scheduled_start") or ""),
        "original_scheduled_end": str(old.get("scheduled_end") or ""),
    })
    old["status"] = "rescheduled"
    old["session_data"] = sd
    old["rescheduled_to"] = new_session_id
    old["rescheduled_at"] = stamp
    old["zoom_meeting_id"] = ""
    old["zoom_link"] = ""
    old["zoom_host_url"] = ""
    old["zoom_meeting_deleted_at"] = stamp
    return old


def build_new_session(
    old: Dict[str, Any],
    *,
    new_session_id: str,
    scheduled_start: str,
    scheduled_end: str,
    actor: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    stamp = (as_utc(now) or datetime.now(timezone.utc)).isoformat()
    return {
        "session_id": new_session_id,
        "client_id": old.get("client_id") or "",
        "coach_id": old.get("coach_id") or "",
        "family_id": old.get("family_id") or "",
        "client_name": old.get("client_name") or "",
        "session_type": old.get("session_type") or "COACH",
        "status": "scheduled",
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "actual_start": None,
        "actual_end": None,
        "duration_minutes": 0,
        "zoom_link": "",
        "zoom_meeting_id": "",
        "zoom_host_url": "",
        "notes": old.get("notes") or "",
        "coach_notes": old.get("coach_notes") or "",
        "price_cents": old.get("price_cents") or 0,
        "payment_status": old.get("payment_status") or "pending",
        "created_at": stamp,
        "rescheduled_from": old.get("session_id") or "",
        "session_data": {
            "rescheduled_from": old.get("session_id") or "",
            "rescheduled_at": stamp,
            "rescheduled_by": actor,
        },
    }


def reschedule_guard(
    session: Dict[str, Any],
    new_start: datetime,
    now: Optional[datetime] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Return (error_code, message) or (None, None) if allowed."""
    now_utc = as_utc(now) or datetime.now(timezone.utc)
    status = str(session.get("status") or "").lower()
    if status not in RESCHEDULE_ELIGIBLE:
        return "not_reschedulable", "Only scheduled live sessions can be rescheduled."
    if is_past_locked(session.get("scheduled_start"), now_utc):
        return "past_locked", "Past sessions stay on the calendar for records and billing."
    if new_start <= now_utc:
        return "new_in_past", "The new time must be in the future."
    old_start = parse_iso_dt(session.get("scheduled_start"))
    if old_start and abs((new_start - old_start).total_seconds()) < 60:
        return "same_slot", "Pick a different date or time."
    return None, None


async def void_session_reminders(db_pool, session_uuid) -> int:
    """Drop unsent/sent reminder claims so the old slot cannot re-fire."""
    if not db_pool or not session_uuid:
        return 0
    try:
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM session_notifications
                WHERE session_id = $1
                  AND notification_type = ANY($2::text[])
                """,
                session_uuid,
                list(REMINDER_TYPES),
            )
        parts = str(result or "").split()
        return int(parts[-1]) if parts and parts[-1].isdigit() else 0
    except Exception:
        return 0


async def log_reschedule(
    db_pool,
    *,
    old_session_id: str,
    new_session_id: str,
    coach_id: str,
    client_id: str,
    old_start: Optional[datetime],
    new_start: Optional[datetime],
    actor: str,
) -> None:
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO session_reschedule_log
                    (old_session_id, new_session_id, coach_id, client_id,
                     old_start, new_start, rescheduled_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                old_session_id,
                new_session_id,
                coach_id or "",
                client_id or "",
                old_start,
                new_start,
                actor or "",
            )
    except Exception:
        return
