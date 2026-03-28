"""
Coach Schedule API — Availability management and calendar sync

Phase 8: Pre-set availability, payment status indicators, calendar view.
"""

import json
import logging
from datetime import datetime, timezone, timedelta, time, date
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.services.api_server import get_current_user, require_coach

logger = logging.getLogger("nate.schedule_api")

router = APIRouter(
    prefix="/api/coach/schedule",
    tags=["coach-schedule"],
    dependencies=[Depends(require_coach)],
)

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class SetAvailabilityRequest(BaseModel):
    day_of_week: int  # 0=Monday, 6=Sunday
    start_time: str   # HH:MM format
    end_time: str     # HH:MM format
    recurring: bool = True
    specific_date: Optional[str] = None  # YYYY-MM-DD for one-off blocks


class CalendarSyncRequest(BaseModel):
    email: str
    provider: str = "google"  # google or outlook


@router.get("/availability")
async def get_availability(request: Request, user: Dict = Depends(require_coach)):
    """Get coach's availability slots."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", user.get("username", ""))

    async with db.acquire() as conn:
        user_uuid = await conn.fetchval(
            "SELECT id FROM users WHERE hardware_id = $1 LIMIT 1", hw_id,
        )
        if not user_uuid:
            return {"slots": [], "count": 0}

        rows = await conn.fetch(
            """SELECT id, day_of_week, start_time, end_time, is_available, specific_date, calendar_sync_email
               FROM coach_availability WHERE coach_id = $1
               ORDER BY day_of_week, start_time""",
            user_uuid,
        )

    slots = []
    for r in rows:
        slots.append({
            "id": str(r["id"]),
            "day_of_week": r["day_of_week"],
            "day_name": DAY_NAMES[r["day_of_week"]] if 0 <= r["day_of_week"] <= 6 else "Unknown",
            "start_time": str(r["start_time"]),
            "end_time": str(r["end_time"]),
            "is_available": r["is_available"],
            "specific_date": r["specific_date"].isoformat() if r["specific_date"] else None,
        })

    return {"slots": slots, "count": len(slots)}


@router.post("/availability")
async def set_availability(req: SetAvailabilityRequest, request: Request, user: Dict = Depends(require_coach)):
    """Add an availability slot."""
    if req.day_of_week < 0 or req.day_of_week > 6:
        raise HTTPException(400, "day_of_week must be 0-6 (Monday-Sunday)")

    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", user.get("username", ""))

    try:
        start = time.fromisoformat(req.start_time)
        end = time.fromisoformat(req.end_time)
    except ValueError:
        raise HTTPException(400, "Invalid time format. Use HH:MM")

    if start >= end:
        raise HTTPException(400, "Start time must be before end time")

    specific_date = None
    if req.specific_date:
        try:
            specific_date = date.fromisoformat(req.specific_date)
        except ValueError:
            raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")

    async with db.acquire() as conn:
        user_uuid = await conn.fetchval(
            "SELECT id FROM users WHERE hardware_id = $1 LIMIT 1", hw_id,
        )
        if not user_uuid:
            raise HTTPException(404, "Coach not found")

        row = await conn.fetchrow(
            """INSERT INTO coach_availability (coach_id, day_of_week, start_time, end_time, is_available, specific_date)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            user_uuid, req.day_of_week, start, end, req.recurring, specific_date,
        )

    return {"id": str(row["id"]), "status": "created"}


@router.delete("/availability/{slot_id}")
async def delete_availability(slot_id: str, request: Request, user: Dict = Depends(require_coach)):
    """Remove an availability slot."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", user.get("username", ""))

    async with db.acquire() as conn:
        user_uuid = await conn.fetchval(
            "SELECT id FROM users WHERE hardware_id = $1 LIMIT 1", hw_id,
        )
        if not user_uuid:
            raise HTTPException(404, "Coach not found")

        result = await conn.execute(
            "DELETE FROM coach_availability WHERE id = $1::uuid AND coach_id = $2",
            slot_id, user_uuid,
        )

    if "DELETE 0" in result:
        raise HTTPException(404, "Slot not found")
    return {"status": "deleted"}


@router.get("/calendar")
async def get_calendar(
    days: int = 30, request: Request = None, user: Dict = Depends(require_coach)
):
    """Get calendar view with sessions and payment status indicators."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", user.get("username", ""))
    now = datetime.now(timezone.utc)
    end_date = now + timedelta(days=days)

    async with db.acquire() as conn:
        sessions = await conn.fetch(
            """SELECT s.id, s.scheduled_at, s.started_at, s.ended_at,
                      s.session_type, s.status,
                      u.username as client_username,
                      u.profile_data->>'name' as client_name
               FROM sessions s
               JOIN users u ON u.id = s.user_id
               WHERE s.scheduled_at BETWEEN $1 AND $2
               AND u.profile_data->>'coach_id' = $3
               ORDER BY s.scheduled_at ASC""",
            now, end_date, hw_id,
        )

        user_uuid = await conn.fetchval(
            "SELECT id FROM users WHERE hardware_id = $1 LIMIT 1", hw_id,
        )
        availability = []
        if user_uuid:
            availability = await conn.fetch(
                "SELECT * FROM coach_availability WHERE coach_id = $1",
                user_uuid,
            )

    calendar_events = []
    for s in sessions:
        calendar_events.append({
            "id": str(s["id"]),
            "type": "session",
            "start": s["scheduled_at"].isoformat() if s["scheduled_at"] else None,
            "end": s["ended_at"].isoformat() if s["ended_at"] else None,
            "client_username": s["client_username"],
            "client_name": s["client_name"],
            "session_type": s["session_type"],
            "status": s["status"] or "SCHEDULED",
        })

    return {
        "events": calendar_events,
        "availability": [
            {
                "day_of_week": a["day_of_week"],
                "start_time": str(a["start_time"]),
                "end_time": str(a["end_time"]),
                "is_available": a["is_available"],
            }
            for a in availability
        ],
    }


@router.post("/calendar-sync")
async def setup_calendar_sync(req: CalendarSyncRequest, request: Request, user: Dict = Depends(require_coach)):
    """Set up calendar sync with Google Calendar or Outlook."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", user.get("username", ""))

    async with db.acquire() as conn:
        user_uuid = await conn.fetchval(
            "SELECT id FROM users WHERE hardware_id = $1 LIMIT 1", hw_id,
        )
        if user_uuid:
            await conn.execute(
                """UPDATE coach_availability SET calendar_sync_email = $1
                   WHERE coach_id = $2""",
                req.email, user_uuid,
            )

    return {
        "status": "configured",
        "email": req.email,
        "provider": req.provider,
        "message": f"Calendar sync configured with {req.email}. Events will sync on next session creation.",
    }


@router.get("/availability/{coach_id}")
async def get_coach_availability_by_id(
    coach_id: str, request: Request, user: Dict = Depends(require_coach)
):
    """Get a specific coach's availability (used by clients/assistants). If coach_id is an assistant with no slots, returns master's availability from coach_hierarchy."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    async with db.acquire() as conn:
        coach_uuid = await conn.fetchval(
            "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1", coach_id,
        )
        if not coach_uuid:
            return {"slots": [], "count": 0}

        rows = await conn.fetch(
            """SELECT id, day_of_week, start_time, end_time, is_available, specific_date, recurring
               FROM coach_availability WHERE coach_id = $1 AND is_available = TRUE
               ORDER BY day_of_week, start_time""",
            coach_uuid,
        )

        # If no slots and coach_id is an assistant, resolve master and return master's slots
        if not rows:
            coach_hw_id = await conn.fetchval(
                "SELECT hardware_id FROM users WHERE id = $1 LIMIT 1", coach_uuid,
            )
            if coach_hw_id:
                master_row = await conn.fetchrow(
                    """SELECT u.id as master_uuid FROM coach_hierarchy ch
                       JOIN users u ON u.hardware_id = ch.master_coach_id
                       WHERE ch.assistant_id = $1 AND ch.status = 'active' LIMIT 1""",
                    coach_hw_id,
                )
                if master_row:
                    rows = await conn.fetch(
                        """SELECT id, day_of_week, start_time, end_time, is_available, specific_date, recurring
                           FROM coach_availability WHERE coach_id = $1 AND is_available = TRUE
                           ORDER BY day_of_week, start_time""",
                        master_row["master_uuid"],
                    )

    slots = []
    for r in rows:
        slots.append({
            "id": str(r["id"]),
            "day_of_week": r["day_of_week"],
            "day_name": DAY_NAMES[r["day_of_week"]] if 0 <= r["day_of_week"] <= 6 else "Unknown",
            "start_time": str(r["start_time"]),
            "end_time": str(r["end_time"]),
            "is_available": r["is_available"],
            "recurring": r["recurring"] if r["recurring"] is not None else True,
            "specific_date": r["specific_date"].isoformat() if r["specific_date"] else None,
        })

    return {"slots": slots, "count": len(slots)}


@router.get("/master-availability")
async def get_master_availability(
    request: Request, user: Dict = Depends(require_coach)
):
    """Assistant coach views master coach's available slots."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", user.get("username", ""))

    async with db.acquire() as conn:
        master_row = await conn.fetchrow(
            """SELECT ch.master_coach_id, u.username as master_username,
                      u.hardware_id as master_hw_id,
                      u.profile_data->>'name' as master_name,
                      u.id as master_uuid
               FROM coach_hierarchy ch
               JOIN users u ON u.hardware_id = ch.master_coach_id
               WHERE ch.assistant_id = $1 AND ch.status = 'active'
               LIMIT 1""",
            hw_id,
        )
        if not master_row:
            return {"master": None, "slots": [], "message": "No active master coach relationship found"}

        rows = await conn.fetch(
            """SELECT id, day_of_week, start_time, end_time, specific_date, recurring
               FROM coach_availability WHERE coach_id = $1 AND is_available = TRUE
               ORDER BY day_of_week, start_time""",
            master_row["master_uuid"],
        )

    slots = []
    for r in rows:
        slots.append({
            "id": str(r["id"]),
            "day_of_week": r["day_of_week"],
            "day_name": DAY_NAMES[r["day_of_week"]] if 0 <= r["day_of_week"] <= 6 else "Unknown",
            "start_time": str(r["start_time"]),
            "end_time": str(r["end_time"]),
            "recurring": r["recurring"] if r["recurring"] is not None else True,
            "specific_date": r["specific_date"].isoformat() if r["specific_date"] else None,
        })

    return {
        "master": {
            "username": master_row["master_username"],
            "hardware_id": master_row["master_hw_id"],
            "name": master_row["master_name"],
        },
        "slots": slots,
    }


class BookMasterRequest(BaseModel):
    scheduled_start: str
    scheduled_end: str
    notes: str = ""


@router.post("/book-master")
async def book_master_session(
    req: BookMasterRequest, request: Request, user: Dict = Depends(require_coach)
):
    """Assistant coach books a session with their master coach."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    username = user.get("username", "")
    hw_id = user.get("hardware_id", user.get("username", ""))

    try:
        sched_start = datetime.fromisoformat(req.scheduled_start)
        sched_end = datetime.fromisoformat(req.scheduled_end)
    except ValueError:
        raise HTTPException(400, "Invalid datetime format. Use ISO-8601")

    if sched_end <= sched_start:
        raise HTTPException(400, "End time must be after start time")

    async with db.acquire() as conn:
        master_row = await conn.fetchrow(
            """SELECT u.username as master_username
               FROM coach_hierarchy ch
               JOIN users u ON u.hardware_id = ch.master_coach_id
               WHERE ch.assistant_id = $1 AND ch.status = 'active' LIMIT 1""",
            hw_id,
        )
        if not master_row:
            raise HTTPException(403, "No active master coach relationship")

        row = await conn.fetchrow(
            """INSERT INTO coach_consultations
                   (assistant_username, master_username, scheduled_start, scheduled_end, is_free, notes)
               VALUES ($1, $2, $3, $4, FALSE, $5)
               ON CONFLICT (assistant_username, master_username, scheduled_start) DO NOTHING
               RETURNING id""",
            username, master_row["master_username"], sched_start, sched_end, req.notes,
        )

    if not row:
        raise HTTPException(409, "A consultation is already booked at this time")

    return {"id": str(row["id"]), "status": "booked", "master": master_row["master_username"]}


@router.post("/free-consultation")
async def request_free_consultation(
    req: BookMasterRequest, request: Request, user: Dict = Depends(require_coach)
):
    """Assistant coach requests a free daily consultation with master coach (1 per day)."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    username = user.get("username", "")
    hw_id = user.get("hardware_id", user.get("username", ""))

    try:
        sched_start = datetime.fromisoformat(req.scheduled_start)
        sched_end = datetime.fromisoformat(req.scheduled_end)
    except ValueError:
        raise HTTPException(400, "Invalid datetime format. Use ISO-8601")

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    async with db.acquire() as conn:
        master_row = await conn.fetchrow(
            """SELECT u.username as master_username
               FROM coach_hierarchy ch
               JOIN users u ON u.hardware_id = ch.master_coach_id
               WHERE ch.assistant_id = $1 AND ch.status = 'active' LIMIT 1""",
            hw_id,
        )
        if not master_row:
            raise HTTPException(403, "No active master coach relationship")

        existing = await conn.fetchval(
            """SELECT COUNT(*) FROM coach_consultations
               WHERE assistant_username = $1 AND master_username = $2
                 AND is_free = TRUE
                 AND scheduled_start >= $3 AND scheduled_start < $4
                 AND status != 'cancelled'""",
            username, master_row["master_username"], today_start, today_end,
        )
        if existing and existing > 0:
            raise HTTPException(429, "Free consultation already used today. Limit: 1 per day.")

        row = await conn.fetchrow(
            """INSERT INTO coach_consultations
                   (assistant_username, master_username, scheduled_start, scheduled_end, is_free, notes)
               VALUES ($1, $2, $3, $4, TRUE, $5)
               ON CONFLICT (assistant_username, master_username, scheduled_start) DO NOTHING
               RETURNING id""",
            username, master_row["master_username"], sched_start, sched_end, req.notes,
        )

    if not row:
        raise HTTPException(409, "A consultation is already booked at this time")

    return {"id": str(row["id"]), "status": "booked_free", "master": master_row["master_username"]}


@router.get("/consultations")
async def get_consultations(
    request: Request, user: Dict = Depends(require_coach)
):
    """Get upcoming consultations for the current coach (as assistant or master)."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    username = user.get("username", "")
    now = datetime.now(timezone.utc)

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, assistant_username, master_username, scheduled_start, scheduled_end,
                      status, is_free, notes, created_at
               FROM coach_consultations
               WHERE (assistant_username = $1 OR master_username = $1)
                 AND scheduled_start >= $2
                 AND status != 'cancelled'
               ORDER BY scheduled_start ASC
               LIMIT 50""",
            username, now,
        )

    return {
        "consultations": [
            {
                "id": str(r["id"]),
                "assistant": r["assistant_username"],
                "master": r["master_username"],
                "start": r["scheduled_start"].isoformat(),
                "end": r["scheduled_end"].isoformat(),
                "status": r["status"],
                "is_free": r["is_free"],
                "notes": r["notes"] or "",
                "role": "assistant" if r["assistant_username"] == username else "master",
            }
            for r in rows
        ],
    }


@router.get("/health")
async def schedule_health(request: Request):
    """Health check."""
    return {"status": "ok", "service": "coach_schedule"}
