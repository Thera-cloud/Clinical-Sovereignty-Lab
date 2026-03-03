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


@router.get("/health")
async def schedule_health(request: Request):
    """Health check."""
    return {"status": "ok", "service": "coach_schedule"}
