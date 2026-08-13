"""Shared coach availability slot computation.

Single source of truth for "what 1-hour slots are open for this coach on this
date". Used by:
  - bridge_server.py  -> client_get_coach_availability handler
  - routers/sessions.py -> GET /api/sessions/available-slots/{coach_id}
  - services/client_scheduling_assistant.py -> chat scheduling path

Extracted from the inline generator in the bridge availability handler so the
calendar, REST, and chat surfaces can never drift. The booked-mask query casts
coach_id to text on both sides so it matches whether coaching_sessions.coach_id
is stored as UUID or as the hardware-id string (the prior inline query passed
the hardware string only, which silently returned 0 rows when the column was a
UUID -> over-showing already-booked slots).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Optional

_DAY_INT_TO_NAME = {
    0: "monday", 1: "tuesday", 2: "wednesday", 3: "thursday",
    4: "friday", 5: "saturday", 6: "sunday",
}

DEFAULT_TZ = "America/New_York"


async def compute_available_slots(
    db_pool: Any,
    coach_hw_id: str,
    date_str: str,
    *,
    registry_loader: Optional[Callable[[], dict]] = None,
    timezone_name: str = DEFAULT_TZ,
) -> dict:
    """Compute open 1-hour slots for a coach on a given ISO date.

    Args:
        db_pool: asyncpg pool.
        coach_hw_id: coach hardware_id (registry key).
        date_str: ISO date (YYYY-MM-DD) in coach-local time.
        registry_loader: optional callable returning the user registry dict,
            used to resolve the coach username for Google external-busy masking.
            If None, Google busy windows are skipped (DB booked slots still apply).
        timezone_name: coach-local timezone name.

    Returns:
        {
          "available_slots": [{"start": iso, "end": iso}, ...],
          "booked_slots":    [{"start": iso, "end": iso, "source"?: str}, ...],
          "availability":    {"slots": [...], "timezone": tz},
          "coach_uuid":      uuid | None,
          "error":           None | "coach_not_found" | "no_db" | "bad_date",
        }
    """
    result: dict = {
        "available_slots": [],
        "booked_slots": [],
        "availability": {"slots": [], "timezone": timezone_name},
        "coach_uuid": None,
        "error": None,
    }

    if not db_pool:
        result["error"] = "no_db"
        return result

    coach_hw_id = (coach_hw_id or "").strip()
    date_str = (date_str or "").strip()

    async with db_pool.acquire() as conn:
        coach_uuid = await conn.fetchval(
            "SELECT id FROM users WHERE hardware_id = $1", coach_hw_id
        )
        if not coach_uuid:
            result["error"] = "coach_not_found"
            return result
        result["coach_uuid"] = str(coach_uuid)

        slot_rows = await conn.fetch(
            "SELECT day_of_week, start_time, end_time FROM coach_availability "
            "WHERE coach_id = $1 AND specific_date IS NULL "
            "AND (is_blocked IS NULL OR is_blocked = false) "
            "ORDER BY day_of_week, start_time",
            coach_uuid,
        )
        avail_slots = [
            {
                "day": r["day_of_week"],
                "day_name": _DAY_INT_TO_NAME.get(r["day_of_week"], ""),
                "start": str(r["start_time"]),
                "end": str(r["end_time"]),
            }
            for r in slot_rows
        ]
        result["availability"] = {"slots": avail_slots, "timezone": timezone_name}

        if not date_str:
            return result

        try:
            tz = _dt.datetime.now().astimezone().tzinfo
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(timezone_name)
            except Exception:
                pass
        except Exception:
            tz = None

        try:
            target_dt = _dt.datetime.fromisoformat(date_str)
            if tz is not None:
                target_dt = target_dt.replace(tzinfo=tz)
            day_name = target_dt.strftime("%A").lower()
        except Exception:
            result["error"] = "bad_date"
            return result

        target_date_obj = target_dt.date()

        is_blocked_date = await conn.fetchval(
            "SELECT 1 FROM coach_availability "
            "WHERE coach_id = $1 AND specific_date = $2 AND is_blocked = true LIMIT 1",
            coach_uuid, target_date_obj,
        )
        day_slots = [] if is_blocked_date else [
            s for s in avail_slots if s.get("day_name", "") == day_name
        ]

        booked_slots: list = []
        # TYPE-SAFE booked mask: cast both sides to text so a UUID column matches
        # the hardware-id string OR the resolved UUID string.
        booked = await conn.fetch(
            "SELECT scheduled_at, ended_at FROM coaching_sessions "
            "WHERE coach_id::text IN ($1, $2) "
            "AND status IN ('scheduled','active','pending_approval','SCHEDULED','ACTIVE','PENDING_APPROVAL') "
            "AND scheduled_at::date = $3",
            coach_hw_id, str(coach_uuid), target_date_obj,
        )
        for br in booked:
            bs = br["scheduled_at"]
            be = br["ended_at"] or (bs + _dt.timedelta(hours=1)) if bs else None
            if bs:
                booked_slots.append({
                    "start": bs.isoformat(),
                    "end": be.isoformat() if be else "",
                })

        # B1: Google free/busy into LN booking. Resolve username from PG so
        # REST, chat, and negotiation all mask google_external_busy without
        # depending on the JSON registry. registry_loader is fallback only.
        coach_username = None
        try:
            coach_username = await conn.fetchval(
                "SELECT username FROM users WHERE hardware_id = $1 LIMIT 1",
                coach_hw_id,
            )
        except Exception:
            coach_username = None
        if not coach_username and registry_loader is not None:
            try:
                registry = registry_loader()
                for _k, _v in (registry or {}).items():
                    p = (_v or {}).get("profile", {})
                    if p.get("hardware_id") == coach_hw_id and p.get("role") == "COACH":
                        coach_username = p.get("username") or _k
                        break
            except Exception:
                coach_username = None
        if coach_username:
            try:
                day_start = target_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = day_start + _dt.timedelta(days=1)
                ext = await conn.fetch(
                    "SELECT start_at, end_at FROM google_external_busy "
                    "WHERE user_id = $1 AND start_at < $3 AND end_at > $2",
                    coach_username, day_start, day_end,
                )
                for xr in ext:
                    xs, xe = xr["start_at"], xr["end_at"]
                    if xs and xe:
                        booked_slots.append({
                            "start": xs.isoformat(),
                            "end": xe.isoformat(),
                            "source": "google",
                        })
            except Exception:
                pass

        now = _dt.datetime.now(tz) if tz is not None else _dt.datetime.now()
        for slot in day_slots:
            st_str = slot.get("start", "09:00:00")
            en_str = slot.get("end", "17:00:00")
            # Respect minute precision: round start UP, end DOWN to whole hours.
            try:
                st_t = _dt.time.fromisoformat(st_str)
                en_t = _dt.time.fromisoformat(en_str)
                start_h = st_t.hour + (1 if st_t.minute > 0 else 0)
                end_h = en_t.hour
            except Exception:
                start_h = int(st_str.split(":")[0])
                end_h = int(en_str.split(":")[0])
            for hour in range(start_h, end_h):
                slot_start = target_dt.replace(hour=hour, minute=0, second=0, microsecond=0)
                slot_end = slot_start + _dt.timedelta(hours=1)
                is_free = True
                for b in booked_slots:
                    try:
                        b_s = _dt.datetime.fromisoformat(b["start"])
                        b_e = _dt.datetime.fromisoformat(b["end"])
                        if slot_start < b_e and slot_end > b_s:
                            is_free = False
                            break
                    except Exception:
                        pass
                if is_free and slot_start > now:
                    result["available_slots"].append({
                        "start": slot_start.isoformat(),
                        "end": slot_end.isoformat(),
                    })

        result["booked_slots"] = booked_slots

    return result
