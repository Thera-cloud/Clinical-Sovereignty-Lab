"""
Coach Directory API — public-facing coach listing for client discovery.

Returns only public profile fields. No email, no client lists, no financials.
"""

import logging
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from app.services.api_server import get_current_user

logger = logging.getLogger("nate.coach_directory_api")

router = APIRouter(
    prefix="/api/coach/directory",
    tags=["coach-directory"],
)


@router.get("/health")
async def directory_health():
    """Health check."""
    return {"status": "ok", "service": "coach_directory"}


@router.get("")
async def list_coaches(request: Request, user: Dict = Depends(get_current_user)):
    """List coaches accepting new clients."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """SELECT coach_user_id, username, display_name, photo_url, bio,
                      specialty_tags, years_experience, session_duration_minutes
               FROM coach_profiles
               WHERE accepting_new_clients = true
               ORDER BY display_name"""
        )

    coaches = []
    for r in rows:
        tags = r["specialty_tags"]
        if isinstance(tags, str):
            import json
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        coaches.append({
            "coach_user_id": r["coach_user_id"],
            "username": r["username"],
            "display_name": r["display_name"],
            "photo_url": r["photo_url"],
            "bio": r["bio"],
            "specialty_tags": tags or [],
            "years_experience": r["years_experience"] or 0,
            "session_duration_minutes": r["session_duration_minutes"] or 60,
        })

    return {"coaches": coaches, "count": len(coaches)}


@router.get("/{coach_user_id}")
async def get_coach_profile(
    coach_user_id: str, request: Request, user: Dict = Depends(get_current_user)
):
    """Get a single coach's public profile."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT coach_user_id, username, display_name, photo_url, bio,
                      specialty_tags, years_experience, session_duration_minutes,
                      accepting_new_clients, max_caseload, current_caseload
               FROM coach_profiles
               WHERE coach_user_id = $1""",
            coach_user_id,
        )

    if not row:
        raise HTTPException(404, "Coach not found")

    tags = row["specialty_tags"]
    if isinstance(tags, str):
        import json
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []

    return {
        "coach_user_id": row["coach_user_id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "photo_url": row["photo_url"],
        "bio": row["bio"],
        "specialty_tags": tags or [],
        "years_experience": row["years_experience"] or 0,
        "session_duration_minutes": row["session_duration_minutes"] or 60,
        "accepting_new_clients": row["accepting_new_clients"],
        "spots_available": max(0, (row["max_caseload"] or 20) - (row["current_caseload"] or 0)),
    }
