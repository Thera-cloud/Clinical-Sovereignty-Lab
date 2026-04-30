"""
LITTLE NATE — Coach Hierarchy & Coaching Mesh REST API

10 hierarchy endpoints (invite, accept, list, revoke, log/get/export hours, attest,
coaching metrics, platform wisdom) + 6 mesh endpoints (create, list, detail, scores,
generate quiz, methods) + 2 Coach Nate progress endpoints (own, assistant).
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import json
import logging

from app.auth import get_current_user_id

logger = logging.getLogger("nate.coach_hierarchy_api")

router = APIRouter(
    prefix="/api/coach",
    tags=["coach-hierarchy"],
    dependencies=[Depends(get_current_user_id)],
)


# ── Pydantic Models ──

class InviteRequest(BaseModel):
    assistant_username: str


class AcceptRequest(BaseModel):
    master_coach_id: str


class RevokeRequest(BaseModel):
    assistant_id: str


class LogHoursRequest(BaseModel):
    assistant_id: str
    activity_type: str = "individual_supervision"
    dojo_type: Optional[str] = None
    duration_minutes: float
    session_date: Optional[str] = None
    notes: Optional[str] = None


class AttestRequest(BaseModel):
    hours_id: int


class MeshCreateRequest(BaseModel):
    title: str
    session_type: str
    dojo_context: Optional[str] = None
    topic_tags: Optional[List[str]] = None
    nate_participation: bool = True


class GenerateQuizRequest(BaseModel):
    topic: str
    dojo_type: Optional[str] = None
    count: int = 5


# ── Helpers ──

def _get_db(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database not available")
    return pool


def _get_mesh_engine(request: Request):
    engine = getattr(request.app.state, "coaching_mesh_engine", None)
    if not engine:
        raise HTTPException(503, "Coaching mesh engine not available")
    return engine


async def _resolve_hw_id(request: Request, user_id: str) -> str:
    """Resolve a username to hardware_id via the users table."""
    pool = _get_db(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT hardware_id FROM users WHERE username = $1", user_id
        )
    return row["hardware_id"] if row else user_id


def _caller_role(request: Request) -> str:
    return str(getattr(request.state, "user_role", None) or "")


async def _require_path_is_self_or_admin(request: Request, path_coach_hw_id: str) -> None:
    """IDOR guard: path coach/hardware id must match authenticated caller, unless admin."""
    user_id = request.state.user_id if hasattr(request.state, "user_id") else "unknown"
    caller_hw = await _resolve_hw_id(request, user_id)
    if str(path_coach_hw_id) != str(caller_hw) and _caller_role(request) != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Cannot view another coach's hierarchy",
        )


async def _require_master_or_self_for_assistant(
    request: Request, pool, assistant_hw_id: str
) -> None:
    """Authorization: caller is the assistant themself, their supervising master (active hierarchy), or admin."""
    if _caller_role(request) == "ADMIN":
        return
    user_id = request.state.user_id if hasattr(request.state, "user_id") else "unknown"
    caller_hw = await _resolve_hw_id(request, user_id)
    if str(assistant_hw_id) == str(caller_hw):
        return
    async with pool.acquire() as conn:
        ok = await conn.fetchval(
            """SELECT 1 FROM coach_hierarchy
               WHERE master_coach_id = $1 AND assistant_id = $2
                 AND status IN ('active', 'accepted')
               LIMIT 1""",
            caller_hw,
            assistant_hw_id,
        )
    if not ok:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to view this assistant's data",
        )


async def _require_mesh_session_access(request: Request, pool, session_id: str) -> None:
    """IDOR guard: mesh session detail/scores require master, participant, or admin."""
    async with pool.acquire() as conn:
        session = await conn.fetchrow(
            "SELECT master_coach_id FROM coaching_mesh_sessions WHERE session_id = $1",
            session_id,
        )
        if not session:
            raise HTTPException(404, "Session not found")
        if _caller_role(request) == "ADMIN":
            return
        user_id = request.state.user_id if hasattr(request.state, "user_id") else "unknown"
        caller_hw = await _resolve_hw_id(request, user_id)
        if str(session["master_coach_id"]) == str(caller_hw):
            return
        ok = await conn.fetchval(
            """SELECT 1 FROM coaching_mesh_participants
               WHERE session_id = $1 AND user_id = $2
               LIMIT 1""",
            session_id,
            caller_hw,
        )
    if not ok:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to view this mesh session",
        )


# ══════════════════════════════════════════════════════════════════════════════
# PART A: Coach Hierarchy Endpoints (10)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/hierarchy/invite")
async def invite_assistant(body: InviteRequest, request: Request):
    """Master coach invites an assistant coach."""
    pool = _get_db(request)
    user_id = request.state.user_id if hasattr(request.state, "user_id") else "unknown"
    master_hw = await _resolve_hw_id(request, user_id)

    async with pool.acquire() as conn:
        assistant = await conn.fetchrow(
            "SELECT hardware_id, username FROM users WHERE username = $1 AND role = 'COACH'",
            body.assistant_username,
        )
        if not assistant:
            raise HTTPException(404, "Coach not found")

        await conn.execute(
            """INSERT INTO coach_hierarchy (master_coach_id, assistant_id, status)
               VALUES ($1, $2, 'pending')
               ON CONFLICT (master_coach_id, assistant_id)
               DO UPDATE SET status = 'pending', invited_at = NOW(), revoked_at = NULL""",
            master_hw, assistant["hardware_id"],
        )
    return {"status": "invited", "assistant": body.assistant_username}


@router.post("/hierarchy/accept")
async def accept_invitation(body: AcceptRequest, request: Request):
    """Assistant accepts a master coach invitation."""
    pool = _get_db(request)
    user_id = request.state.user_id if hasattr(request.state, "user_id") else "unknown"
    assistant_hw = await _resolve_hw_id(request, user_id)

    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE coach_hierarchy
               SET status = 'active', accepted_at = NOW()
               WHERE master_coach_id = $1 AND assistant_id = $2 AND status = 'pending'""",
            body.master_coach_id, assistant_hw,
        )
    if result == "UPDATE 0":
        raise HTTPException(404, "No pending invitation found")
    return {"status": "accepted", "master_coach_id": body.master_coach_id}


@router.get("/hierarchy/assistants/{coach_id}")
async def list_assistants(coach_id: str, request: Request):
    """List assistants for a master coach."""
    pool = _get_db(request)
    await _require_path_is_self_or_admin(request, coach_id)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ch.assistant_id, ch.status, ch.invited_at, ch.accepted_at,
                      u.username, u.profile_data->>'name' as display_name
               FROM coach_hierarchy ch
               LEFT JOIN users u ON u.hardware_id = ch.assistant_id
               WHERE ch.master_coach_id = $1 AND ch.status IN ('pending', 'active', 'accepted')
               ORDER BY ch.invited_at DESC""",
            coach_id,
        )
    return [
        {
            "assistant_id": r["assistant_id"],
            "username": r["username"],
            "display_name": r["display_name"] or r["username"],
            "status": r["status"],
            "invited_at": r["invited_at"].isoformat() if r["invited_at"] else None,
            "accepted_at": r["accepted_at"].isoformat() if r["accepted_at"] else None,
        }
        for r in rows
    ]


@router.post("/hierarchy/revoke")
async def revoke_assistant(body: RevokeRequest, request: Request):
    """Master revokes an assistant relationship."""
    pool = _get_db(request)
    user_id = request.state.user_id if hasattr(request.state, "user_id") else "unknown"
    master_hw = await _resolve_hw_id(request, user_id)

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE coach_hierarchy
               SET status = 'revoked', revoked_at = NOW()
               WHERE master_coach_id = $1 AND assistant_id = $2""",
            master_hw, body.assistant_id,
        )
    return {"status": "revoked", "assistant_id": body.assistant_id}


@router.post("/hierarchy/hours/log")
async def log_hours(body: LogHoursRequest, request: Request):
    """Master logs supervised hours for an assistant."""
    pool = _get_db(request)
    user_id = request.state.user_id if hasattr(request.state, "user_id") else "unknown"
    master_hw = await _resolve_hw_id(request, user_id)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO supervised_hours
               (assistant_id, master_coach_id, activity_type, dojo_type,
                duration_minutes, session_date, notes)
               VALUES ($1, $2, $3, $4, $5, COALESCE($6::date, CURRENT_DATE), $7)
               RETURNING id""",
            body.assistant_id, master_hw, body.activity_type, body.dojo_type,
            body.duration_minutes, body.session_date, body.notes,
        )
    return {"hours_id": row["id"], "status": "logged"}


@router.get("/hierarchy/hours/{assistant_id}")
async def get_hours(assistant_id: str, request: Request):
    """Get supervised hours for an assistant."""
    pool = _get_db(request)
    await _require_master_or_self_for_assistant(request, pool, assistant_id)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, master_coach_id, activity_type, dojo_type,
                      duration_minutes, session_date, notes,
                      attestation_status, attested_at, mesh_session_id, created_at
               FROM supervised_hours
               WHERE assistant_id = $1
               ORDER BY session_date DESC""",
            assistant_id,
        )
    return [
        {
            "id": r["id"],
            "master_coach_id": r["master_coach_id"],
            "activity_type": r["activity_type"],
            "dojo_type": r["dojo_type"],
            "duration_minutes": r["duration_minutes"],
            "session_date": r["session_date"].isoformat() if r["session_date"] else None,
            "notes": r["notes"],
            "attestation_status": r["attestation_status"],
            "attested_at": r["attested_at"].isoformat() if r["attested_at"] else None,
            "mesh_session_id": r["mesh_session_id"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.get("/hierarchy/hours/export/{assistant_id}")
async def export_hours(assistant_id: str, request: Request):
    """Export supervised hours summary for an assistant."""
    pool = _get_db(request)
    await _require_master_or_self_for_assistant(request, pool, assistant_id)
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COALESCE(SUM(duration_minutes), 0) FROM supervised_hours WHERE assistant_id = $1",
            assistant_id,
        )
        attested = await conn.fetchval(
            """SELECT COALESCE(SUM(duration_minutes), 0) FROM supervised_hours
               WHERE assistant_id = $1 AND attestation_status = 'attested'""",
            assistant_id,
        )
        by_type = await conn.fetch(
            """SELECT activity_type, COUNT(*) as sessions, SUM(duration_minutes) as total_minutes
               FROM supervised_hours WHERE assistant_id = $1
               GROUP BY activity_type ORDER BY total_minutes DESC""",
            assistant_id,
        )
    return {
        "assistant_id": assistant_id,
        "total_minutes": float(total),
        "total_hours": round(float(total) / 60, 1),
        "attested_minutes": float(attested),
        "attested_hours": round(float(attested) / 60, 1),
        "by_type": [
            {"activity_type": r["activity_type"], "sessions": r["sessions"],
             "total_minutes": float(r["total_minutes"])}
            for r in by_type
        ],
    }


@router.post("/hierarchy/hours/attest")
async def attest_hours(body: AttestRequest, request: Request):
    """Master attests supervised hours."""
    pool = _get_db(request)
    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE supervised_hours
               SET attestation_status = 'attested', attested_at = NOW()
               WHERE id = $1 AND attestation_status = 'pending'""",
            body.hours_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(404, "Hours record not found or already attested")
    return {"hours_id": body.hours_id, "status": "attested"}


@router.get("/hierarchy/metrics")
async def coaching_metrics(request: Request):
    """Admin-level coaching hierarchy metrics."""
    pool = _get_db(request)
    async with pool.acquire() as conn:
        total_relationships = await conn.fetchval(
            "SELECT COUNT(*) FROM coach_hierarchy WHERE status = 'active'"
        )
        total_hours = await conn.fetchval(
            "SELECT COALESCE(SUM(duration_minutes), 0) FROM supervised_hours"
        )
        total_mesh_sessions = await conn.fetchval(
            "SELECT COUNT(*) FROM coaching_mesh_sessions"
        )
        active_mesh = await conn.fetchval(
            "SELECT COUNT(*) FROM coaching_mesh_sessions WHERE ended_at IS NULL"
        )
    return {
        "active_relationships": total_relationships,
        "total_supervised_hours": round(float(total_hours) / 60, 1),
        "total_mesh_sessions": total_mesh_sessions,
        "active_mesh_sessions": active_mesh,
    }


@router.get("/hierarchy/wisdom")
async def platform_wisdom(request: Request):
    """Aggregate coaching wisdom from mesh sessions and hierarchy."""
    pool = _get_db(request)
    async with pool.acquire() as conn:
        by_dojo = await conn.fetch(
            """SELECT dojo_context, COUNT(*) as sessions,
                      AVG(participant_count) as avg_participants
               FROM coaching_mesh_sessions
               WHERE dojo_context IS NOT NULL
               GROUP BY dojo_context ORDER BY sessions DESC"""
        )
        top_methods = await conn.fetch(
            """SELECT session_type, COUNT(*) as uses
               FROM coaching_mesh_sessions
               WHERE session_type IS NOT NULL
               GROUP BY session_type ORDER BY uses DESC LIMIT 10"""
        )
    return {
        "by_dojo": [
            {"dojo": r["dojo_context"], "sessions": r["sessions"],
             "avg_participants": round(float(r["avg_participants"]), 1)}
            for r in by_dojo
        ],
        "top_methods": [
            {"method": r["session_type"], "uses": r["uses"]}
            for r in top_methods
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# PART A-extra: Assistant Metrics Overview (master coach dashboard)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/hierarchy/assistant-metrics")
async def get_assistant_metrics(request: Request, days: int = 30):
    """Aggregated metrics for all assistants under the calling master coach."""
    pool = _get_db(request)
    user_id = request.state.user_id if hasattr(request.state, "user_id") else "unknown"
    master_hw = await _resolve_hw_id(request, user_id)

    async with pool.acquire() as conn:
        assistants = await conn.fetch(
            """SELECT ch.assistant_id, u.username,
                      u.profile_data->>'name' as display_name,
                      ch.status, ch.accepted_at
               FROM coach_hierarchy ch
               LEFT JOIN users u ON u.hardware_id = ch.assistant_id
               WHERE ch.master_coach_id = $1 AND ch.status IN ('pending', 'active', 'accepted')
               ORDER BY ch.accepted_at DESC NULLS LAST""",
            master_hw,
        )

        results = []
        for a in assistants:
            a_hw = a["assistant_id"]
            a_username = a["username"] or ""

            client_count = await conn.fetchval(
                """SELECT COUNT(*) FROM users
                   WHERE role = 'CLIENT'
                     AND (profile_data->>'coach_id' = $1
                          OR profile_data->>'assigned_coach_id' = $1
                          OR profile_data->>'assigned_coach' = $2)""",
                a_hw, a_username,
            ) or 0

            a_uuid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1", a_hw
            )

            session_stats = {"total": 0, "completed": 0, "avg_coherence": 0.0}
            if a_uuid:
                stats_row = await conn.fetchrow(
                    """SELECT COUNT(*) as total,
                              COUNT(*) FILTER (WHERE status = 'completed') as completed,
                              COALESCE(AVG(COALESCE((session_data->>'avg_c_emo')::float, 0))
                                       FILTER (WHERE status = 'completed'), 0) as avg_c
                       FROM coaching_sessions
                       WHERE coach_id = $1
                         AND created_at > NOW() - ($2 || ' days')::interval""",
                    a_uuid, str(days),
                )
                if stats_row:
                    session_stats = {
                        "total": stats_row["total"] or 0,
                        "completed": stats_row["completed"] or 0,
                        "avg_coherence": round(float(stats_row["avg_c"] or 0), 3),
                    }

            hours_row = await conn.fetchrow(
                """SELECT COALESCE(SUM(duration_minutes), 0) as total_mins,
                          COUNT(*) FILTER (WHERE attestation_status = 'attested') as attested
                   FROM supervised_hours
                   WHERE assistant_id = $1 AND master_coach_id = $2""",
                a_hw, master_hw,
            )

            results.append({
                "assistant_id": a_hw,
                "username": a_username,
                "display_name": a["display_name"] or a_username,
                "status": a["status"],
                "accepted_at": a["accepted_at"].isoformat() if a["accepted_at"] else None,
                "client_count": client_count,
                "sessions": session_stats,
                "supervised_hours": round(float((hours_row["total_mins"] or 0)) / 60.0, 1) if hours_row else 0,
                "attested_sessions": hours_row["attested"] if hours_row else 0,
            })

    return {"assistants": results, "total": len(results)}


@router.get("/hierarchy/assistant-clients/{coach_username}")
async def get_assistant_clients(coach_username: str, request: Request):
    """List all clients assigned to an assistant (master coach view)."""
    pool = _get_db(request)

    async with pool.acquire() as conn:
        a_row = await conn.fetchrow(
            """SELECT hardware_id FROM users
               WHERE username = $1 AND role = 'COACH' AND deleted_at IS NULL""",
            coach_username,
        )
        if not a_row:
            raise HTTPException(404, "Assistant coach not found")
        a_hw = a_row["hardware_id"]

    await _require_master_or_self_for_assistant(request, pool, a_hw)

    async with pool.acquire() as conn:
        clients = await conn.fetch(
            """SELECT username, hardware_id,
                      profile_data->>'name' as name,
                      profile_data->>'tier' as tier,
                      profile_data->>'coherence_risk' as risk,
                      profile_data->>'last_session_date' as last_session
               FROM users
               WHERE role = 'CLIENT'
                 AND (profile_data->>'coach_id' = $1
                      OR profile_data->>'assigned_coach_id' = $1
                      OR profile_data->>'assigned_coach' = $2)
               ORDER BY profile_data->>'name'""",
            a_hw, coach_username,
        )

    return {
        "clients": [
            {
                "username": c["username"],
                "hardware_id": c["hardware_id"],
                "name": c["name"] or c["username"],
                "tier": c["tier"] or "STANDARD",
                "risk": c["risk"] or "normal",
                "last_session": c["last_session"],
            }
            for c in clients
        ],
        "total": len(clients),
    }


# ══════════════════════════════════════════════════════════════════════════════
# PART A-extra-2: Assistant Session Outcomes (Gap 7a)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/hierarchy/assistant-sessions/{coach_username}")
async def get_assistant_sessions(
    coach_username: str,
    request: Request,
    days: int = 30,
):
    """Master coach views coaching session outcomes for an assistant's clients."""
    pool = _get_db(request)

    async with pool.acquire() as conn:
        assistant_row = await conn.fetchrow(
            """SELECT id, hardware_id FROM users
               WHERE username = $1 AND deleted_at IS NULL""",
            coach_username,
        )
        if not assistant_row:
            raise HTTPException(404, "Coach not found")
        assistant_hw = assistant_row["hardware_id"]
        assistant_uuid = assistant_row["id"]

    await _require_master_or_self_for_assistant(request, pool, assistant_hw)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT cs.session_id, cs.client_id::text, cs.client_name, cs.status,
                      cs.scheduled_at, cs.actual_start, cs.actual_end,
                      cs.duration_minutes, cs.nate_summary, cs.coach_notes,
                      cs.mood_at_start, cs.mood_at_end,
                      COALESCE((cs.session_data->>'avg_c_emo')::float, 0) as avg_c_emo,
                      COALESCE((cs.session_data->>'observations_count')::int, 0) as observations_count
               FROM coaching_sessions cs
               WHERE cs.coach_id = $1
                 AND cs.created_at > NOW() - ($2 || ' days')::interval
               ORDER BY cs.scheduled_at DESC NULLS LAST
               LIMIT 100""",
            assistant_uuid, str(days),
        )

    sessions = []
    for r in rows:
        sessions.append({
            "session_id": r["session_id"],
            "client_id": r["client_id"],
            "client_name": r["client_name"] or r["client_id"],
            "status": r["status"],
            "scheduled_start": r["scheduled_at"].isoformat() if r["scheduled_at"] else None,
            "actual_start": r["actual_start"].isoformat() if r["actual_start"] else None,
            "actual_end": r["actual_end"].isoformat() if r["actual_end"] else None,
            "duration_minutes": r["duration_minutes"],
            "nate_summary": r["nate_summary"] or "",
            "coach_notes": (r["coach_notes"] or "")[:500],
            "mood_at_start": r["mood_at_start"] or "",
            "mood_at_end": r["mood_at_end"] or "",
            "avg_c_emo": round(r["avg_c_emo"], 3),
            "observations_count": r["observations_count"],
        })

    completed = [s for s in sessions if s["status"] == "completed"]
    avg_coherence = (
        sum(s["avg_c_emo"] for s in completed) / len(completed)
        if completed else 0
    )
    summarized = sum(1 for s in completed if s["nate_summary"])

    return {
        "assistant_username": coach_username,
        "days": days,
        "total_sessions": len(sessions),
        "completed_sessions": len(completed),
        "avg_coherence": round(avg_coherence, 3),
        "sessions_with_summary": summarized,
        "sessions": sessions,
    }


# ══════════════════════════════════════════════════════════════════════════════
# PART B: Coaching Mesh Endpoints (6)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/mesh/create")
async def create_mesh_session(body: MeshCreateRequest, request: Request):
    """Create a new BLE coaching mesh session."""
    engine = _get_mesh_engine(request)
    user_id = request.state.user_id if hasattr(request.state, "user_id") else "unknown"
    master_hw = await _resolve_hw_id(request, user_id)

    result = await engine.create_session(
        master_id=master_hw,
        title=body.title,
        session_type=body.session_type,
        dojo_context=body.dojo_context,
        topic_tags=body.topic_tags,
        nate_participation=body.nate_participation,
    )
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/mesh/sessions/{coach_id}")
async def list_mesh_sessions(coach_id: str, request: Request, limit: int = 20):
    """List mesh sessions for a coach (as master or participant)."""
    _get_db(request)
    await _require_path_is_self_or_admin(request, coach_id)
    engine = _get_mesh_engine(request)
    return await engine.get_sessions_for_coach(coach_id, limit=limit)


@router.get("/mesh/session/{session_id}")
async def get_mesh_session_detail(session_id: str, request: Request):
    """Get session detail with participants and transcript."""
    pool = _get_db(request)
    await _require_mesh_session_access(request, pool, session_id)
    engine = _get_mesh_engine(request)
    participants = await engine.get_session_participants(session_id)
    transcript = await engine.get_session_transcript(session_id)
    async with pool.acquire() as conn:
        session = await conn.fetchrow(
            """SELECT session_id, master_coach_id, session_type, title,
                      topic_tags, dojo_context, started_at, ended_at,
                      participant_count, nate_participation
               FROM coaching_mesh_sessions WHERE session_id = $1""",
            session_id,
        )
    if not session:
        raise HTTPException(404, "Session not found")
    return {
        "session": {
            "session_id": session["session_id"],
            "master_coach_id": session["master_coach_id"],
            "session_type": session["session_type"],
            "title": session["title"],
            "dojo_context": session["dojo_context"],
            "started_at": session["started_at"].isoformat() if session["started_at"] else None,
            "ended_at": session["ended_at"].isoformat() if session["ended_at"] else None,
            "participant_count": session["participant_count"],
        },
        "participants": participants,
        "transcript": transcript,
    }


@router.get("/mesh/session/{session_id}/scores")
async def get_mesh_scores(session_id: str, request: Request):
    """Get per-participant scores for a mesh session."""
    pool = _get_db(request)
    await _require_mesh_session_access(request, pool, session_id)
    engine = _get_mesh_engine(request)
    return await engine.get_session_scores(session_id)


@router.post("/mesh/generate-quiz")
async def generate_quiz(body: GenerateQuizRequest, request: Request):
    """AI-generate quiz questions for a topic/DOJO."""
    engine = _get_mesh_engine(request)
    questions = await engine.generate_quiz_from_topic(
        topic=body.topic, dojo_type=body.dojo_type, count=body.count,
    )
    return {"questions": questions, "count": len(questions)}


@router.get("/mesh/methods/{dojo_type}")
async def get_training_methods(dojo_type: str, request: Request):
    """Get DOJO-specific training methods (or all if dojo_type is 'all')."""
    engine = _get_mesh_engine(request)
    if dojo_type == "all":
        return engine.get_methods()
    return engine.get_methods(dojo_type)


# ══════════════════════════════════════════════════════════════════════════════
# PART C: Coach Nate Progress Endpoints (2)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/nate-progress")
async def get_my_nate_progress(request: Request):
    """Coach's own cumulative progress across all 6 Coach Nate skill areas."""
    pool = _get_db(request)
    user_id = request.state.user_id if hasattr(request.state, "user_id") else "unknown"

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT skill_area, session_count, average_score, best_score,
                      total_score, dimension_averages, last_session_at
               FROM coach_nate_progress
               WHERE coach_username = $1
               ORDER BY skill_area""",
            user_id,
        )

    all_skills = [
        "rapport_building", "focused_listening", "intuition_development",
        "effective_questions", "constructive_feedback", "coaching_path",
    ]
    progress = {}
    for skill in all_skills:
        progress[skill] = {
            "session_count": 0, "average_score": 0, "best_score": 0,
            "total_score": 0, "dimension_averages": {}, "last_session_at": None,
        }
    for r in rows:
        dims = r["dimension_averages"] or {}
        if isinstance(dims, str):
            try:
                dims = json.loads(dims)
            except Exception:
                dims = {}
        progress[r["skill_area"]] = {
            "session_count": r["session_count"],
            "average_score": float(r["average_score"]) if r["average_score"] else 0,
            "best_score": float(r["best_score"]) if r["best_score"] else 0,
            "total_score": float(r["total_score"]) if r["total_score"] else 0,
            "dimension_averages": dims,
            "last_session_at": r["last_session_at"].isoformat() if r["last_session_at"] else None,
        }

    averages = [v["average_score"] for v in progress.values() if v["session_count"] > 0]
    overall = sum(averages) / len(averages) if averages else 0

    return {
        "coach_username": user_id,
        "skills": progress,
        "overall_readiness": round(overall, 2),
        "skills_practiced": len(averages),
        "total_skills": len(all_skills),
    }


@router.get("/nate-progress/{coach_username}")
async def get_assistant_nate_progress(coach_username: str, request: Request):
    """Master coach views an assistant's Coach Nate progress (requires hierarchy)."""
    pool = _get_db(request)

    async with pool.acquire() as conn:
        assistant_hw = await conn.fetchval(
            """SELECT hardware_id FROM users
               WHERE username = $1 AND deleted_at IS NULL""",
            coach_username,
        )
        if not assistant_hw:
            raise HTTPException(404, "Coach not found")

    await _require_master_or_self_for_assistant(request, pool, assistant_hw)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT skill_area, session_count, average_score, best_score,
                      total_score, dimension_averages, last_session_at
               FROM coach_nate_progress
               WHERE coach_username = $1
               ORDER BY skill_area""",
            coach_username,
        )

    all_skills = [
        "rapport_building", "focused_listening", "intuition_development",
        "effective_questions", "constructive_feedback", "coaching_path",
    ]
    progress = {}
    for skill in all_skills:
        progress[skill] = {
            "session_count": 0, "average_score": 0, "best_score": 0,
            "total_score": 0, "dimension_averages": {}, "last_session_at": None,
        }
    for r in rows:
        dims = r["dimension_averages"] or {}
        if isinstance(dims, str):
            try:
                dims = json.loads(dims)
            except Exception:
                dims = {}
        progress[r["skill_area"]] = {
            "session_count": r["session_count"],
            "average_score": float(r["average_score"]) if r["average_score"] else 0,
            "best_score": float(r["best_score"]) if r["best_score"] else 0,
            "total_score": float(r["total_score"]) if r["total_score"] else 0,
            "dimension_averages": dims,
            "last_session_at": r["last_session_at"].isoformat() if r["last_session_at"] else None,
        }

    averages = [v["average_score"] for v in progress.values() if v["session_count"] > 0]
    overall = sum(averages) / len(averages) if averages else 0

    return {
        "coach_username": coach_username,
        "skills": progress,
        "overall_readiness": round(overall, 2),
        "skills_practiced": len(averages),
        "total_skills": len(all_skills),
    }
