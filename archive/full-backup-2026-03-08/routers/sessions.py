"""
Scheduling & Session Management API Routes
Handles appointment booking, calendar management, and session tracking
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, UploadFile, File, Form

from app.services.api_server import get_current_user as _require_auth
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta, timezone
import os
import json
import secrets
import asyncio
import logging
from pathlib import Path
import httpx

from app.config import settings
from app.auth import get_current_user_id
from app.services.zoom_client import ZoomClient
from app.services.blob_storage import upload_bytes

_logger = logging.getLogger("sessions")

# Import classroom analyzer for automatic analysis after archive
try:
    from app.services.classroom_analyzer import (
        ClassroomAnalyzer,
        VTTParser,
        build_analysis_prompt,
        ANALYSIS_SYSTEM_PROMPT,
    )
    CLASSROOM_AVAILABLE = True
except ImportError:
    CLASSROOM_AVAILABLE = False
    ClassroomAnalyzer = None

router = APIRouter(prefix="/api/sessions", tags=["sessions"], dependencies=[Depends(_require_auth)])

from app.config import settings as _settings
DATA_DIR = Path(_settings.DATA_DIR)
WORKBOOKS_DIR = Path(_settings.WORKBOOKS_DIR)

from app.services.pg_data_helpers import (
    load_sessions_pg, upsert_session_pg, delete_session_pg,
    load_registry_pg, find_user_pg, upsert_classroom_analysis_pg,
    get_master_for_assistant_pg,
)

# Initialize classroom analyzer for auto-analysis
_classroom_analyzer = None
if CLASSROOM_AVAILABLE:
    try:
        _classroom_analyzer = ClassroomAnalyzer(DATA_DIR, WORKBOOKS_DIR)
        print("[Sessions] Classroom analyzer initialized for auto-analysis")
    except Exception as e:
        print(f"[Sessions] Could not initialize classroom analyzer: {e}")


async def auto_analyze_transcript(
    session_id: str,
    transcript_content: str,
    session_data: dict
):
    """
    Automatically analyze a transcript after archiving.
    Runs as a background task so archive completes quickly.
    """
    if not _classroom_analyzer:
        print(f"[AutoAnalysis] Skipping - classroom analyzer not available")
        return
    
    try:
        print(f"[AutoAnalysis] Starting automatic analysis for session {session_id}")
        
        # Extract session info
        client_id = session_data.get("client_id", "")
        client_name = session_data.get("client_name", session_data.get("client", ""))
        coach_id = session_data.get("coach_id", "")
        family_id = session_data.get("family_id", "")
        
        coach_name = "Coach"
        try:
            registry_path = DATA_DIR / "registry.json"
            if registry_path.exists():
                with open(registry_path, 'r') as f:
                    registry = json.load(f)
                for _, v in registry.items():
                    p = v.get("profile", {})
                    if p.get("hardware_id") == coach_id:
                        coach_name = p.get("name", "Coach")
                        break
                if not family_id and client_id:
                    for _, v in registry.items():
                        p = v.get("profile", {})
                        if p.get("hardware_id") == client_id:
                            family_id = p.get("family_id", "")
                            if not client_name:
                                client_name = p.get("name", "")
                            break
        except Exception as e:
            _logger.warning("AutoAnalysis: Registry lookup error: %s", e)
        
        # Run metrics analysis (synchronous part)
        analysis = _classroom_analyzer.analyze_transcript(
            session_id=session_id,
            coach_id=coach_id,
            client_id=client_id,
            coach_name=coach_name,
            vtt_content=transcript_content,
            focus_area="general therapeutic skills",
            due_date=None,
            family_id=family_id,
            client_name=client_name
        )
        
        print(f"[AutoAnalysis] Metrics extracted for {session_id}: {analysis.get('metrics', {}).get('total_duration_minutes', 0):.1f} min")
        
        # Mark as ready for AI analysis
        sessions = load_json(DATA_DIR / "sessions.json", [])
        for s in sessions:
            if s.get("session_id") == session_id:
                s["classroom_auto_analyzed_at"] = str(datetime.now())
                s["classroom_analysis_available"] = True
                break
        save_json(DATA_DIR / "sessions.json", sessions)
        
        # Queue AI analysis as background task
        # This will run asynchronously and notify coach when complete
        _classroom_analyzer.queue_ai_analysis(
            session_id=session_id,
            coach_id=coach_id,
            coach_name=coach_name,
            vtt_content=transcript_content,
            focus_area="general therapeutic skills"
        )
        
        print(f"[AutoAnalysis] Metrics complete, AI analysis queued for session {session_id}")
        
    except Exception as e:
        print(f"[AutoAnalysis] Error analyzing session {session_id}: {e}")
        import traceback
        traceback.print_exc()


# Models
class ScheduleSessionRequest(BaseModel):
    client_id: str
    coach_id: str
    family_id: Optional[str] = ""
    client_name: Optional[str] = ""
    scheduled_start: str  # ISO format
    scheduled_end: str
    session_type: str = "COACH"  # COACH, FAMILY, GROUP, MASTER_CONSULTATION
    notes: Optional[str] = ""
    zoom_link: Optional[str] = ""
    disable_recording: Optional[bool] = False
    free_consultation: Optional[bool] = False

class UpdateSessionRequest(BaseModel):
    session_id: str
    status: Optional[str] = None
    coach_notes: Optional[str] = None
    topics_covered: Optional[List[str]] = None
    homework_assigned: Optional[List[str]] = None

class CoachAvailabilityRequest(BaseModel):
    coach_id: str
    slots: List[dict]  # [{"day": "monday", "start": "09:00", "end": "17:00"}]
    timezone: str = "America/New_York"

# Helpers
def _get_fernet():
    """Get Fernet cipher for encrypting session files at rest."""
    try:
        from app.field_encryption import _get_fernet as _gf
        return _gf()
    except Exception:
        return None

def load_json(filepath: Path, default=None):
    if default is None: default = {}
    if not filepath.exists(): return default
    try:
        raw = filepath.read_bytes()
        fernet = _get_fernet()
        if fernet and raw and not raw.startswith(b'[') and not raw.startswith(b'{'):
            try:
                decrypted = fernet.decrypt(raw)
                return json.loads(decrypted)
            except Exception:
                pass
        return json.loads(raw)
    except Exception as e:
        _logger.warning("load_json: failed to read %s: %s", filepath, e)
        return default

def save_json(filepath: Path, data):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, default=str).encode('utf-8')
    # Encrypt session files at rest if encryption key is available
    fernet = _get_fernet()
    if fernet and 'sessions' in str(filepath) and 'classroom_sessions' not in str(filepath):
        payload = fernet.encrypt(payload)
    with open(filepath, 'wb') as f:
        f.write(payload)
    # Restrict file permissions (owner read/write only)
    try:
        filepath.chmod(0o600)
    except Exception:
        pass

def generate_session_id():
    return f"SES_{datetime.now().strftime('%Y%m%d')}_{secrets.token_hex(6).upper()}"


def _get_db(request: Request):
    return getattr(request.app.state, "db_pool", None)


async def _load_sessions_pf(request: Request) -> list:
    """PG-first session loader. Falls back to JSON only if PG fails."""
    db = _get_db(request)
    if db:
        try:
            pg_sessions = await load_sessions_pg(db)
            if pg_sessions is not None:
                return pg_sessions
        except Exception as e:
            _logger.warning("_load_sessions_pf: PG read failed, falling back to JSON: %s", e)
    return load_json(DATA_DIR / "sessions.json", [])


async def _save_session_dual(request: Request, session: dict, all_sessions: list = None):
    """Dual-write: upsert to PG + save full list to JSON backup."""
    db = _get_db(request)
    if db:
        try:
            await upsert_session_pg(db, session)
        except Exception as e:
            _logger.warning("_save_session_dual: PG upsert failed: %s", e)
    if all_sessions is not None:
        save_json(DATA_DIR / "sessions.json", all_sessions)

# Zoom meeting map (meeting_id -> internal session metadata)
ZOOM_MEETING_MAP_FILE = DATA_DIR / "zoom_meeting_map.json"

def _parse_iso_dt(s: str) -> Optional[datetime]:
    ss = (s or "").strip()
    if not ss:
        return None
    try:
        dtv = datetime.fromisoformat(ss.replace("Z", "+00:00"))
        if dtv.tzinfo is None:
            # Treat naive times as UTC for consistent comparisons/storage.
            return dtv.replace(tzinfo=timezone.utc)
        return dtv
    except Exception:
        return None

def _iso_to_zoom_start(iso_str: str) -> str:
    """
    Zoom accepts ISO strings. If naive, we treat as UTC and add 'Z' for stability.
    """
    s = (iso_str or "").strip()
    if not s:
        return ""
    try:
        dtv = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dtv.tzinfo is None:
            return dtv.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        return dtv.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        # fallback: return as-is
        return s

def _update_zoom_meeting_map(
    meeting_id: str,
    *,
    schedule_session_id: str,
    client_id: str,
    family_id: str,
    topic: str,
) -> None:
    """
    Best-effort: persist mapping so webhooks attach to the right internal folder.
    """
    mid = (meeting_id or "").strip()
    if not mid:
        return
    mm = load_json(ZOOM_MEETING_MAP_FILE, {}) or {}
    if not isinstance(mm, dict):
        mm = {}
    mm[mid] = {
        "updated_at": datetime.utcnow().isoformat(),
        "schedule_session_id": schedule_session_id or "",
        "client_id": client_id or "",
        "family_id": family_id or "",
        "topic": topic or "",
    }
    save_json(ZOOM_MEETING_MAP_FILE, mm)

def _make_zoom_client() -> ZoomClient:
    return ZoomClient(
        account_id=settings.ZOOM_ACCOUNT_ID,
        client_id=settings.ZOOM_CLIENT_ID,
        client_secret=settings.ZOOM_CLIENT_SECRET,
        host_user=settings.ZOOM_HOST_USER,
        default_timezone=settings.ZOOM_DEFAULT_TIMEZONE,
        default_waiting_room=settings.ZOOM_DEFAULT_WAITING_ROOM,
        default_join_before_host=settings.ZOOM_DEFAULT_JOIN_BEFORE_HOST,
        default_auto_recording=settings.ZOOM_DEFAULT_AUTO_RECORDING,
    )

# Endpoints

@router.post("/schedule")
async def schedule_session(req: ScheduleSessionRequest, request: Request):
    """Schedule a new session"""
    sessions = await _load_sessions_pf(request)
    
    # Check for conflicts — skip sessions whose scheduled_end is in the past
    # (stale "scheduled" sessions that were never started/completed/cancelled)
    now = datetime.now(timezone.utc)
    for s in sessions:
        if s.get("coach_id") == req.coach_id and s.get("status") in ["scheduled", "active"]:
            existing_start = _parse_iso_dt(s.get("scheduled_start", ""))
            existing_end = _parse_iso_dt(s.get("scheduled_end", ""))
            new_start = _parse_iso_dt(req.scheduled_start)
            new_end = _parse_iso_dt(req.scheduled_end)
            if not (existing_start and existing_end and new_start and new_end):
                continue
            if existing_end < now and s.get("status") == "scheduled":
                continue
            if (new_start < existing_end and new_end > existing_start):
                conflict_client = s.get("client_name") or s.get("client_id", "unknown")
                conflict_start = existing_start.strftime("%m/%d %I:%M %p") if existing_start else "?"
                conflict_end = existing_end.strftime("%I:%M %p") if existing_end else "?"
                raise HTTPException(
                    409,
                    f"Time slot conflict: overlaps with {conflict_client} session ({conflict_start} - {conflict_end} UTC)"
                )
    
    session_id = generate_session_id()

    _is_consultation = req.session_type == "MASTER_CONSULTATION" or req.free_consultation

    # Enforce 1 free consultation per day per assistant coach
    if req.free_consultation:
        pool = getattr(request.app.state, "db_pool", None)
        if pool:
            try:
                today_count = await pool.fetchval(
                    """SELECT COUNT(*) FROM coaching_sessions
                       WHERE coach_id = $1 AND session_type = 'MASTER_CONSULTATION'
                         AND (payment_status = 'waived' OR (session_data->>'payment_status') = 'waived')
                         AND scheduled_start::date = CURRENT_DATE
                         AND status NOT IN ('cancelled', 'declined')""",
                    req.coach_id,
                )
                if today_count and today_count >= 1:
                    raise HTTPException(400, "Free consultation already used today")
            except HTTPException:
                raise
            except Exception as e:
                _logger.warning("Free consultation limit check failed: %s", e)

    # Look up coach fee from profile_data for billing
    coach_fee_cents = 0
    if not _is_consultation:
        try:
            pool = getattr(request.app.state, "db_pool", None)
            if pool:
                coach_row = await pool.fetchrow(
                    "SELECT profile_data->>'coaching_fee' as fee FROM users WHERE hardware_id = $1 AND role = 'COACH'",
                    req.coach_id,
                )
                if coach_row and coach_row["fee"]:
                    coach_fee_cents = int(float(coach_row["fee"]) * 100)
        except Exception as e:
            _logger.warning("schedule_session: could not look up coach fee for %s: %s", req.coach_id, e)

    _effective_type = "MASTER_CONSULTATION" if req.free_consultation else req.session_type
    _effective_duration = 15 if req.free_consultation else 0

    session = {
        "session_id": session_id,
        "client_id": req.client_id,
        "coach_id": req.coach_id,
        "family_id": req.family_id or "",
        "client_name": req.client_name or "",
        "session_type": _effective_type,
        "status": "scheduled",
        "scheduled_start": req.scheduled_start,
        "scheduled_end": req.scheduled_end,
        "actual_start": None,
        "actual_end": None,
        "duration_minutes": _effective_duration,
        "zoom_link": req.zoom_link,
        "zoom_meeting_id": "",
        "notes": req.notes,
        "coach_notes": "",
        "topics_covered": [],
        "homework_assigned": [],
        "mood_at_start": "",
        "mood_at_end": "",
        "nate_summary": "",
        "recording_url": "",
        "created_at": str(datetime.now()),
        "price_cents": 0 if _is_consultation else coach_fee_cents,
        "payment_status": "waived" if _is_consultation else "pending",
        "free_consultation": req.free_consultation or False,
    }

    # Optional: auto-create Zoom meeting if enabled and no link provided.
    zoom_error = None
    try:
        if settings.ENABLE_ZOOM and not (req.zoom_link or "").strip():
            print(f">>> [ZOOM] Auto-create enabled for session {session_id} (coach_id={req.coach_id}, client_id={req.client_id})")
            # Compute duration from scheduled_start/end if possible
            dur_min = 50
            try:
                st = _parse_iso_dt(req.scheduled_start)
                en = _parse_iso_dt(req.scheduled_end)
                if st and en and en > st:
                    dur_min = max(5, int((en - st).total_seconds() / 60))
            except Exception:
                dur_min = 50

            start_iso = _iso_to_zoom_start(req.scheduled_start)
            if not start_iso:
                start_iso = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

            topic = f"Coaching Session {session_id}"
            if req.session_type:
                topic = f"{req.session_type} — {topic}"

            client = _make_zoom_client()

            # Build Zoom meeting settings - override recording if coach opts out
            zoom_settings = {}
            if req.disable_recording:
                zoom_settings["auto_recording"] = "none"
                session["recording_disabled"] = True
                print(f">>> [ZOOM] Recording disabled by coach for session {session_id}")

            zoom_resp = await client.create_meeting(
                topic=topic,
                start_time_iso=start_iso,
                duration_minutes=int(dur_min or 50),
                agenda=req.notes or "",
                settings=zoom_settings if zoom_settings else None,
            )
            mid = str(zoom_resp.get("id") or "")
            join_url = str(zoom_resp.get("join_url") or "")
            start_url = str(zoom_resp.get("start_url") or "")  # Host URL for coaches
            if join_url:
                session["zoom_link"] = join_url
            if start_url:
                session["zoom_host_url"] = start_url  # Coach launches directly into Zoom as host
            if mid:
                session["zoom_meeting_id"] = mid
                # We don't always know family_id in this API; allow client apps to pass via notes
                _update_zoom_meeting_map(
                    mid,
                    schedule_session_id=session_id,
                    client_id=req.client_id,
                    family_id=req.family_id or "",
                    topic=topic,
                )
            print(f">>> [ZOOM] Created meeting for session {session_id} (meeting_id={mid}, has_join_url={bool(join_url)})")
    except Exception as e:
        zoom_error = str(e)
        print(f">>> [ZOOM] Auto-create failed for session {session_id}: {zoom_error}")
    
    sessions.append(session)
    await _save_session_dual(request, session, sessions)
    
    resp = {"session": session}
    if zoom_error:
        resp["zoom_error"] = zoom_error
    return resp

@router.get("/client/{client_id}")
async def get_client_sessions(request: Request, client_id: str, current_user: str = Depends(get_current_user_id), status: str = None, limit: int = 20):
    """Get sessions for a client. Requires authentication; user must be the client, their coach, or admin."""
    sessions = await _load_sessions_pf(request)
    client_sessions = [s for s in sessions if s.get("client_id") == client_id]
    user_role = getattr(request.state, "user_role", "")
    if current_user != client_id and user_role != "ADMIN":
        is_assigned_coach = any(s.get("coach_id") == current_user for s in client_sessions)
        if not is_assigned_coach:
            raise HTTPException(403, "Access denied: you are not this client or their assigned coach")
    
    if status:
        client_sessions = [s for s in client_sessions if s.get("status") == status]
    
    client_sessions.sort(key=lambda x: x.get("scheduled_start", ""), reverse=True)
    return {"sessions": client_sessions[:limit]}

@router.get("/coach/{coach_id}")
async def get_coach_sessions(request: Request, coach_id: str, current_user: str = Depends(get_current_user_id), status: str = None, limit: int = 50):
    """Get sessions for a coach. Requires authentication; user must be the coach or admin."""
    user_role = getattr(request.state, "user_role", "")
    if current_user != coach_id and user_role != "ADMIN":
        raise HTTPException(403, "Access denied: you can only view your own sessions")
    sessions = await _load_sessions_pf(request)
    coach_sessions = [s for s in sessions if s.get("coach_id") == coach_id]
    
    if status:
        coach_sessions = [s for s in coach_sessions if s.get("status") == status]
    
    coach_sessions.sort(key=lambda x: x.get("scheduled_start", ""), reverse=True)
    return {"sessions": coach_sessions[:limit]}

@router.get("/upcoming/{user_id}")
async def get_upcoming_sessions(request: Request, user_id: str, current_user: str = Depends(get_current_user_id), days: int = 7):
    """Get upcoming sessions for a user (as client or coach). Requires authentication."""
    user_role = getattr(request.state, "user_role", "")
    if current_user != user_id and user_role != "ADMIN":
        raise HTTPException(403, "Access denied: you can only view your own upcoming sessions")
    sessions = await _load_sessions_pf(request)
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days)
    
    upcoming = []
    for s in sessions:
        if s.get("client_id") == user_id or s.get("coach_id") == user_id:
            if s.get("status") == "scheduled":
                try:
                    start = _parse_iso_dt(s.get("scheduled_start", ""))
                    if not start:
                        continue
                    if now <= start <= cutoff:
                        upcoming.append(s)
                except:
                    pass
    
    upcoming.sort(key=lambda x: x.get("scheduled_start", ""))
    return {"sessions": upcoming}


@router.post("/expire-stale")
async def expire_stale_sessions(request: Request):
    """Auto-expire scheduled sessions whose scheduled_end is in the past."""
    db = _get_db(request)
    expired_count = 0
    if db:
        try:
            async with db.acquire() as conn:
                result = await conn.execute(
                    """UPDATE coaching_sessions
                       SET status = 'no_show', updated_at = NOW()
                       WHERE status = 'scheduled'
                         AND scheduled_end < NOW() - INTERVAL '30 minutes'""",
                )
                expired_count = int(result.split()[-1]) if result else 0
        except Exception as e:
            _logger.warning("expire_stale_sessions: %s", e)
    return {"expired": expired_count}


@router.get("/{session_id}")
async def get_session(request: Request, session_id: str, current_user: str = Depends(get_current_user_id)):
    """Get session details. Requires authentication; user must be the client or coach for this session."""
    sessions = await _load_sessions_pf(request)
    for s in sessions:
        if s.get("session_id") == session_id:
            if current_user not in (s.get("client_id"), s.get("coach_id")):
                raise HTTPException(403, "Access denied: you are not a participant in this session")
            return {"session": s}
    raise HTTPException(404, "Session not found")

@router.post("/start/{session_id}")
async def start_session(request: Request, session_id: str, current_user: str = Depends(get_current_user_id)):
    """Mark session as started. Requires authentication; user must be the coach."""
    sessions = await _load_sessions_pf(request)

    for s in sessions:
        if s.get("session_id") == session_id:
            if current_user not in (s.get("client_id"), s.get("coach_id")):
                raise HTTPException(403, "Access denied: you are not a participant in this session")
            s["status"] = "active"
            s["actual_start"] = datetime.now(timezone.utc).isoformat()
            await _save_session_dual(request, s, sessions)
            return {"session": s}

    raise HTTPException(404, "Session not found")

@router.post("/end/{session_id}")
async def end_session(request: Request, session_id: str, current_user: str = Depends(get_current_user_id), mood_at_end: str = "", summary: str = ""):
    """Mark session as ended. Requires authentication; user must be a participant."""
    sessions = await _load_sessions_pf(request)

    for s in sessions:
        if s.get("session_id") == session_id:
            if current_user not in (s.get("client_id"), s.get("coach_id")):
                raise HTTPException(403, "Access denied: you are not a participant in this session")
            now_utc = datetime.now(timezone.utc)
            s["status"] = "completed"
            s["actual_end"] = now_utc.isoformat()
            s["mood_at_end"] = mood_at_end
            s["nate_summary"] = summary

            if s.get("actual_start"):
                try:
                    start = datetime.fromisoformat(s["actual_start"])
                    s["duration_minutes"] = int((now_utc - start).total_seconds() / 60)
                except Exception:
                    pass

            await _save_session_dual(request, s, sessions)
            
            db = _get_db(request)
            if db:
                try:
                    async with db.acquire() as conn:
                        await conn.execute(
                            """UPDATE users SET profile_data = jsonb_set(
                                   COALESCE(profile_data, '{}'::jsonb),
                                   '{total_sessions_count}',
                                   (COALESCE((profile_data->>'total_sessions_count')::int, 0) + 1)::text::jsonb
                               ) WHERE hardware_id = $1""",
                            s.get("client_id", ""),
                        )
                except Exception as e:
                    _logger.warning("end_session: PG session count update failed: %s", e)
            else:
                registry = load_json(DATA_DIR / "user_registry.json")
                for k, v in registry.items():
                    if v.get("profile", {}).get("hardware_id") == s.get("client_id"):
                        v["profile"]["total_sessions_count"] = v["profile"].get("total_sessions_count", 0) + 1
                        save_json(DATA_DIR / "user_registry.json", registry)
                        break
            
            return {"session": s}
    
    raise HTTPException(404, "Session not found")


@router.post("/{session_id}/zoom/delete")
async def delete_zoom_meeting(session_id: str, request: Request):
    """
    Delete the Zoom meeting associated with a scheduled session.
    This helps avoid wasted Zoom storage and reduces long-term clutter.
    """
    sessions = await _load_sessions_pf(request)
    if not isinstance(sessions, list):
        sessions = []

    for s in sessions:
            meeting_id = (s.get("zoom_meeting_id") or "").strip()
            if not meeting_id:
                return {"ok": True, "message": "No zoom_meeting_id on session", "session": s}

            if not settings.ENABLE_ZOOM:
                raise HTTPException(status_code=400, detail="Zoom disabled (ENABLE_ZOOM=false)")

            client = _make_zoom_client()

            try:
                await client.delete_meeting(meeting_id=meeting_id)
            except httpx.HTTPStatusError as e:
                body = ""
                try:
                    body = (e.response.text or "")[:2000]
                except Exception:
                    body = ""
                raise HTTPException(
                    status_code=502,
                    detail={"error": "zoom_delete_failed", "zoom_status": getattr(e.response, "status_code", None), "zoom_body": body},
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail={"error": "zoom_delete_failed", "message": str(e)})

            s["zoom_meeting_deleted_at"] = str(datetime.now())
            s["zoom_meeting_id"] = ""
            s["zoom_link"] = ""
            await _save_session_dual(request, s, sessions)
            return {"ok": True, "message": "Zoom meeting deleted", "session": s}

    raise HTTPException(404, "Session not found")


@router.get("/{session_id}/zoom/recording_status")
async def get_recording_status(session_id: str, request: Request):
    """
    Check if Zoom recording is ready for archiving.
    
    Returns:
        - available: Whether any recordings exist
        - status: "recording" | "processing" | "completed" | "unavailable"
        - has_transcript: Whether a transcript file is available
        - can_archive: Whether the session can be archived now
        - message: Human-readable status message
        - estimated_wait_minutes: How long to wait if processing
    """
    if not settings.ENABLE_ZOOM:
        raise HTTPException(status_code=400, detail="Zoom disabled (ENABLE_ZOOM=false)")

    sessions = await _load_sessions_pf(request)
    if not isinstance(sessions, list):
        sessions = []

    target = None
    for s in sessions:
        if s.get("session_id") == session_id:
            target = s
            break
    if not target:
        raise HTTPException(404, "Session not found")
    
    meeting_id = (target.get("zoom_meeting_id") or "").strip()
    if not meeting_id:
        return {
            "available": False,
            "status": "unavailable",
            "has_transcript": False,
            "can_archive": False,
            "message": "Session has no Zoom meeting ID",
            "already_archived": bool(target.get("transcript_archived_at")),
        }
    
    # Check if already archived
    if target.get("transcript_archived_at"):
        return {
            "available": True,
            "status": "archived",
            "has_transcript": True,
            "can_archive": False,
            "message": f"Transcript already archived on {target.get('transcript_archived_at')}",
            "already_archived": True,
            "transcript_location": target.get("transcript_location", ""),
        }
    
    client = _make_zoom_client()
    
    try:
        availability = await client.check_recording_availability(meeting_id=meeting_id)
    except Exception as e:
        return {
            "available": False,
            "status": "error",
            "has_transcript": False,
            "can_archive": False,
            "message": f"Error checking Zoom: {str(e)}",
            "already_archived": False,
        }
    
    status = availability.get("status", "unavailable")
    recording_files = availability.get("recording_files", [])
    
    # Check for transcript files
    has_transcript = False
    transcript_status = "unavailable"
    for f in recording_files:
        if not isinstance(f, dict):
            continue
        ftype = (f.get("file_type") or "").upper()
        ext = (f.get("file_extension") or "").upper()
        if ftype in ("TRANSCRIPT", "CC") or ext in ("VTT", "TXT"):
            has_transcript = True
            transcript_status = f.get("status", "completed")
            break
    
    # Determine message and can_archive
    can_archive = False
    estimated_wait = 0
    
    if status == "unavailable":
        message = "No recordings found. Meeting may not have been recorded, or recording not yet available."
    elif status == "recording":
        message = "Meeting is still recording. Please wait for meeting to end."
        estimated_wait = 5
    elif status == "processing":
        message = "Recording is still processing. Zoom typically takes 5-15 minutes after meeting ends."
        estimated_wait = 10
    elif status == "completed":
        if has_transcript:
            if transcript_status == "processing":
                message = "Recording complete but transcript is still processing. Please wait a few more minutes."
                estimated_wait = 5
            else:
                message = "Recording and transcript ready for archiving."
                can_archive = True
        else:
            message = "Recording available but NO TRANSCRIPT found. Ensure 'Audio Transcript' is enabled in your Zoom settings."
            can_archive = False
    else:
        message = f"Unknown status: {status}"
    
    return {
        "available": availability.get("available", False),
        "status": status,
        "has_transcript": has_transcript,
        "transcript_status": transcript_status if has_transcript else "unavailable",
        "can_archive": can_archive,
        "message": message,
        "estimated_wait_minutes": estimated_wait,
        "already_archived": False,
        "days_remaining": availability.get("days_remaining", 30),
        "recording_files_count": len(recording_files),
    }


@router.post("/{session_id}/zoom/archive_transcript")
async def archive_zoom_transcript(
    session_id: str,
    request: Request,
    delete_recordings: bool = True,
    delete_meeting: bool = False,
    background_tasks: BackgroundTasks = None,
):
    """
    Archive transcript artifacts (VTT/CC) to Azure Blob (or local fallback) and optionally delete Zoom recordings.

    Best practice for storage:
    - Keep only transcript + Nate summary.
    - Delete cloud recording media to avoid waste.
    
    IMPORTANT: Check recording_status first to ensure transcript is ready.
    """
    if not settings.ENABLE_ZOOM:
        raise HTTPException(status_code=400, detail="Zoom disabled (ENABLE_ZOOM=false)")

    sessions = await _load_sessions_pf(request)
    if not isinstance(sessions, list):
        sessions = []

    target = None
    for s in sessions:
        if s.get("session_id") == session_id:
            target = s
            break
    if not target:
        raise HTTPException(404, "Session not found")

    meeting_id = (target.get("zoom_meeting_id") or "").strip()
    if not meeting_id:
        raise HTTPException(status_code=400, detail="Session has no zoom_meeting_id")

    client = _make_zoom_client()
    
    # Check recording status FIRST before attempting download
    try:
        availability = await client.check_recording_availability(meeting_id=meeting_id)
        status = availability.get("status", "unavailable")
        
        if status == "unavailable":
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "recording_unavailable",
                    "message": "No recordings found. The meeting may not have been recorded, or the recording has been deleted.",
                    "suggestion": "Ensure 'Cloud Recording' is enabled in Zoom settings before the meeting."
                }
            )
        
        if status == "recording":
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "recording_in_progress",
                    "message": "The meeting is still being recorded. Please wait for the meeting to end.",
                    "status": status
                }
            )
        
        if status == "processing":
            raise HTTPException(
                status_code=202,
                detail={
                    "error": "recording_processing",
                    "message": "Recording is still being processed by Zoom. Please try again in 5-15 minutes.",
                    "status": status,
                    "estimated_wait_minutes": 10
                }
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Archive] Status check failed, proceeding with archive attempt: {e}")
        # Continue to try archive anyway - the status check is advisory

    # Find transcript-like files
    try:
        rec = await client.get_meeting_recordings(meeting_id=meeting_id)
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = (e.response.text or "")[:2000]
        except Exception:
            body = ""
        
        # Parse Zoom error for better messaging
        error_code = None
        try:
            import json as json_lib
            error_data = json_lib.loads(body)
            error_code = error_data.get("code")
        except:
            pass
        
        if error_code == 3301:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "recording_not_found",
                    "message": "Recording does not exist. It may have been deleted or never created.",
                    "zoom_error_code": 3301,
                    "suggestion": "Ensure meetings are set to record to cloud and the recording hasn't been manually deleted."
                }
            )
        
        raise HTTPException(
            status_code=502,
            detail={"error": "zoom_recordings_failed", "zoom_status": getattr(e.response, "status_code", None), "zoom_body": body},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "zoom_recordings_failed", "message": str(e)})

    files = []
    try:
        files = (rec.get("recording_files") or []) if isinstance(rec, dict) else []
    except Exception:
        files = []

    transcript_files = []
    for f in files:
        if not isinstance(f, dict):
            continue
        ftype = (f.get("file_type") or "").upper()
        ext = (f.get("file_extension") or "").upper()
        # Zoom commonly uses "TRANSCRIPT" or "CC" for captions
        if ftype in ("TRANSCRIPT", "CC") or ext in ("VTT", "TXT"):
            transcript_files.append(f)

    if not transcript_files:
        # Check if there are video files but no transcript
        video_files = [f for f in files if (f.get("file_type") or "").upper() in ("MP4", "M4A", "SHARED_SCREEN_WITH_SPEAKER_VIEW")]
        
        if video_files:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "no_transcript_found",
                    "message": "Recording exists but NO AUDIO TRANSCRIPT was generated.",
                    "suggestion": "Enable 'Audio Transcript' in Zoom Settings > Recording > Advanced Cloud Recording Settings. The transcript may still be processing - try again in a few minutes.",
                    "has_video": True,
                    "video_count": len(video_files)
                }
            )
        else:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "no_transcript_found",
                    "message": "No transcript/CC files found for this meeting.",
                    "suggestion": "Ensure the meeting was recorded to cloud with audio transcription enabled.",
                    "has_video": False
                }
            )

    # Pick the newest transcript artifact
    transcript_files.sort(key=lambda x: (x.get("recording_start") or ""), reverse=True)
    chosen = transcript_files[0]
    download_url = (chosen.get("download_url") or "").strip()
    if not download_url:
        raise HTTPException(status_code=404, detail={"error": "missing_download_url", "message": "Transcript file missing download_url."})

    content = await client.download_recording_file(download_url=download_url)
    
    # Decode transcript content
    transcript_text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else str(content)
    ext = ((chosen.get("file_extension") or "vtt").strip().lower() or "vtt")
    
    # ============================================================
    # PHASE 1: Little Nate READS and LEARNS from transcript FIRST
    # (Before archiving to ensure learning happens even if archive fails)
    # ============================================================
    analysis_result = None
    learning_completed = False
    
    if CLASSROOM_AVAILABLE and _classroom_analyzer:
        try:
            print(f"[Archive] Step 1: Little Nate reading transcript for session {session_id}")
            
            # Extract session info for analysis
            client_id = target.get("client_id", "")
            client_name = target.get("client_name", target.get("client", ""))
            coach_id = target.get("coach_id", "")
            family_id = target.get("family_id", "")
            
            coach_name = "Coach"
            db = _get_db(request)
            if db:
                try:
                    cp = await find_user_pg(db, hardware_id=coach_id)
                    if cp:
                        cpd = cp.get("profile_data") or {}
                        if isinstance(cpd, str):
                            cpd = json.loads(cpd) if cpd else {}
                        coach_name = cpd.get("name", "Coach")
                    if not family_id and client_id:
                        clp = await find_user_pg(db, hardware_id=client_id)
                        if clp:
                            cld = clp.get("profile_data") or {}
                            if isinstance(cld, str):
                                cld = json.loads(cld) if cld else {}
                            family_id = cld.get("family_id", "")
                            if not client_name:
                                client_name = cld.get("name", "")
                except Exception as e:
                    _logger.warning("archive_zoom_transcript: PG registry lookup failed: %s", e)
            if coach_name == "Coach":
                try:
                    registry_path = DATA_DIR / "registry.json"
                    if not registry_path.exists():
                        registry_path = DATA_DIR / "user_registry.json"
                    if registry_path.exists():
                        with open(registry_path, 'r') as f:
                            registry = json.load(f)
                        for _, v in registry.items():
                            p = v.get("profile", {})
                            if p.get("hardware_id") == coach_id:
                                coach_name = p.get("name", "Coach")
                                break
                            if not family_id and p.get("hardware_id") == client_id:
                                family_id = p.get("family_id", "")
                                if not client_name:
                                    client_name = p.get("name", "")
                except Exception as e:
                    _logger.warning("archive_zoom_transcript: JSON registry lookup failed: %s", e)
            
            # Run metrics analysis (synchronous)
            analysis_result = _classroom_analyzer.analyze_transcript(
                session_id=session_id,
                coach_id=coach_id,
                client_id=client_id,
                coach_name=coach_name,
                vtt_content=transcript_text,
                focus_area="general therapeutic skills",
                due_date=None,
                family_id=family_id,
                client_name=client_name
            )
            # Persist to PostgreSQL so lived wisdom is not lost (plan: lived_wisdom_persistence_addendum)
            db_pool = _get_db(request)
            if db_pool and analysis_result:
                try:
                    await upsert_classroom_analysis_pg(db_pool, analysis_result)
                except Exception as pg_err:
                    _logger.warning("archive_zoom_transcript: PG classroom analysis persist failed: %s", pg_err)
                # Notify coach (ready for assessment) and master (analysis pending)
                try:
                    ns = getattr(request.app.state, "notification_system", None)
                    if ns:
                        client_name = analysis_result.get("client_name") or "your client"
                        coach_id = analysis_result.get("coach_id") or ""
                        coach_name = coach_name or "assistant coach"
                        async with db_pool.acquire() as conn:
                            r = await conn.fetchrow(
                                "SELECT COALESCE(profile_data->>'email', email, '') as email FROM users WHERE hardware_id = $1",
                                coach_id,
                            )
                            coach_email = (r.get("email") or "").strip() if r else None
                        if coach_email:
                            asyncio.create_task(ns.send_classroom_ready_for_assessment(coach_email, client_name))
                        master_id = await get_master_for_assistant_pg(db_pool, coach_id)
                        if master_id and master_id != coach_id:
                            async with db_pool.acquire() as conn:
                                r = await conn.fetchrow(
                                    "SELECT COALESCE(profile_data->>'email', email, '') as email FROM users WHERE hardware_id = $1",
                                    master_id,
                                )
                                master_email = (r.get("email") or "").strip() if r else None
                            if master_email:
                                asyncio.create_task(ns.send_classroom_analysis_pending(master_email, client_name, coach_name))
                except Exception as notif_err:
                    _logger.warning("archive_zoom_transcript: classroom notification failed: %s", notif_err)
            
            print(f"[Archive] Step 2: Metrics extracted - {analysis_result.get('metrics', {}).get('total_duration_minutes', 0):.1f} min session")
            target["nate_read_transcript_at"] = str(datetime.now())
            target["nate_extracted_metrics"] = True
            
            # Queue AI analysis (will run in background and push to Night School)
            _classroom_analyzer.queue_ai_analysis(
                session_id=session_id,
                coach_id=coach_id,
                coach_name=coach_name,
                vtt_content=transcript_text,
                focus_area="general therapeutic skills"
            )
            
            learning_completed = True
            target["nate_learning_queued_at"] = str(datetime.now())
            print(f"[Archive] Step 3: AI analysis queued for Night School learning")
            
        except Exception as e:
            print(f"[Archive] Warning - Learning failed but continuing with archive: {e}")
            import traceback
            traceback.print_exc()
            target["nate_learning_error"] = str(e)
    else:
        print(f"[Archive] Classroom analyzer not available - skipping learning phase")
    
    # ============================================================
    # PHASE 2: Archive transcript to Azure Blob Storage
    # (After learning so transcript is preserved even if we learned)
    # ============================================================
    rel_path = f"sessions/{session_id}/{meeting_id}/transcript.{ext}"
    storage_kind, location = upload_bytes(rel_path=rel_path, content=content, content_type="text/vtt" if ext == "vtt" else "text/plain")

    target["transcript_archived_at"] = str(datetime.now())
    target["transcript_storage"] = storage_kind
    target["transcript_location"] = location
    target["transcript_file_type"] = (chosen.get("file_type") or "")
    target["transcript_file_extension"] = ext
    target["classroom_analysis_available"] = learning_completed

    # Do not keep recording_url by default (storage minimization)
    target["recording_url"] = ""
    
    print(f"[Archive] Step 4: Transcript archived to {storage_kind}: {location}")

    # ============================================================
    # PHASE 3: Clean up Zoom recordings (optional)
    # ============================================================
    recordings_deleted = False
    if delete_recordings:
        try:
            await client.delete_meeting_recordings(meeting_id=meeting_id)
            recordings_deleted = True
            target["zoom_recordings_deleted_at"] = str(datetime.now())
            print(f"[Archive] Step 5: Zoom recordings deleted")
        except Exception as e:
            target["zoom_recordings_delete_error"] = str(e)

    # Optionally delete meeting itself
    meeting_deleted = False
    if delete_meeting:
        try:
            await client.delete_meeting(meeting_id=meeting_id)
            meeting_deleted = True
            target["zoom_meeting_deleted_at"] = str(datetime.now())
            target["zoom_meeting_id"] = ""
            target["zoom_link"] = ""
        except Exception as e:
            target["zoom_meeting_delete_error"] = str(e)

    await _save_session_dual(request, target, sessions)

    return {
        "ok": True,
        "session": target,
        "archived_to": {"storage": storage_kind, "location": location},
        "recordings_deleted": recordings_deleted,
        "meeting_deleted": meeting_deleted,
        "nate_learning_completed": learning_completed,
        "analysis_summary": {
            "duration_minutes": analysis_result.get("metrics", {}).get("total_duration_minutes", 0) if analysis_result else 0,
            "techniques_found": len(analysis_result.get("metrics", {}).get("techniques", {})) if analysis_result else 0,
        } if analysis_result else None,
    }

@router.put("/{session_id}")
async def update_session(session_id: str, req: UpdateSessionRequest, request: Request, current_user: str = Depends(get_current_user_id)):
    """Update session details. Requires authentication; user must be the coach."""
    sessions = await _load_sessions_pf(request)

    for s in sessions:
        if s.get("session_id") == session_id:
            if current_user != s.get("coach_id"):
                raise HTTPException(403, "Access denied: only the assigned coach can update session details")
            if req.status: s["status"] = req.status
            if req.coach_notes: s["coach_notes"] = req.coach_notes
            if req.topics_covered: s["topics_covered"] = req.topics_covered
            if req.homework_assigned: s["homework_assigned"] = req.homework_assigned
            s["updated_at"] = str(datetime.now())
            await _save_session_dual(request, s, sessions)
            return {"session": s}

    raise HTTPException(404, "Session not found")

@router.delete("/{session_id}")
async def cancel_session(session_id: str, request: Request, current_user: str = Depends(get_current_user_id), reason: str = "", hard_delete: bool = False):
    """Cancel or delete a session. Requires authentication; user must be a participant.

    Args:
        session_id: The session ID to cancel/delete
        reason: Optional cancellation reason
        hard_delete: If True, permanently removes the session. If False, just marks as cancelled.
    """
    sessions = await _load_sessions_pf(request)

    for i, s in enumerate(sessions):
        if s.get("session_id") == session_id:
            if current_user not in (s.get("client_id"), s.get("coach_id")):
                raise HTTPException(403, "Access denied: you are not a participant in this session")
            if hard_delete:
                deleted_session = sessions.pop(i)
                db = _get_db(request)
                if db:
                    try:
                        await delete_session_pg(db, session_id)
                    except Exception as e:
                        _logger.warning("cancel_session: PG delete failed: %s", e)
                save_json(DATA_DIR / "sessions.json", sessions)
                return {"message": "Session permanently deleted", "session": deleted_session}
            else:
                s["status"] = "cancelled"
                s["cancellation_reason"] = reason
                s["cancelled_at"] = str(datetime.now())
                await _save_session_dual(request, s, sessions)
                # Notify the coach via WebSocket so their SCHEDULE tab auto-refreshes
                try:
                    bridge = getattr(request.app.state, "bridge_notify", None)
                    if bridge and hasattr(bridge, "notify_user"):
                        coach_hw_id = s.get("coach_id", "")
                        if coach_hw_id:
                            await bridge.notify_user(coach_hw_id, {
                                "type": "session_cancelled_by_client",
                                "session_id": session_id,
                                "client_name": s.get("client_name", ""),
                                "cancelled_at": s["cancelled_at"],
                            })
                except Exception as e:
                    _logger.warning("cancel_session: could not notify coach: %s", e)
                return {"message": "Session cancelled", "session": s}

    raise HTTPException(404, "Session not found")

# Coach Availability — reads from coach_availability PostgreSQL table

DAY_NAMES_LOWER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

@router.post("/availability")
async def set_coach_availability(req: CoachAvailabilityRequest, request: Request):
    """Set coach's availability slots (writes to PostgreSQL)."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    async with db.acquire() as conn:
        coach_uuid = await conn.fetchval(
            "SELECT id FROM users WHERE hardware_id = $1 LIMIT 1", req.coach_id,
        )
        if not coach_uuid:
            raise HTTPException(404, "Coach not found")

        for slot in (req.slots or []):
            day_str = (slot.get("day") or "").strip().lower()
            dow = DAY_NAMES_LOWER.index(day_str) if day_str in DAY_NAMES_LOWER else None
            if dow is None:
                continue
            start_str = slot.get("start", "09:00")
            end_str = slot.get("end", "17:00")
            await conn.execute(
                """INSERT INTO coach_availability (coach_id, day_of_week, start_time, end_time, is_available, recurring)
                   VALUES ($1, $2, $3::time, $4::time, TRUE, TRUE)
                   ON CONFLICT DO NOTHING""",
                coach_uuid, dow, start_str, end_str,
            )

    return {"availability": {"coach_id": req.coach_id, "timezone": req.timezone, "slots": req.slots}}


@router.get("/availability/{coach_id}")
async def get_coach_availability(coach_id: str, request: Request):
    """Get coach's availability from PostgreSQL."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        return {"availability": {"slots": [], "timezone": "America/New_York"}}

    async with db.acquire() as conn:
        coach_uuid = await conn.fetchval(
            "SELECT id FROM users WHERE hardware_id = $1 LIMIT 1", coach_id,
        )
        if not coach_uuid:
            return {"availability": {"slots": [], "timezone": "America/New_York"}}

        rows = await conn.fetch(
            """SELECT day_of_week, start_time, end_time, is_available, specific_date, recurring
               FROM coach_availability WHERE coach_id = $1 AND is_available = TRUE
               ORDER BY day_of_week, start_time""",
            coach_uuid,
        )

    slots = []
    for r in rows:
        dow = r["day_of_week"]
        day_name = DAY_NAMES_LOWER[dow] if 0 <= dow <= 6 else "unknown"
        slots.append({
            "day": day_name,
            "start": str(r["start_time"])[:5],
            "end": str(r["end_time"])[:5],
            "recurring": r["recurring"] if r["recurring"] is not None else True,
            "specific_date": r["specific_date"].isoformat() if r["specific_date"] else None,
        })

    return {"availability": {"slots": slots, "timezone": "America/New_York"}}


@router.get("/available-slots/{coach_id}")
async def get_available_slots(coach_id: str, date: str, request: Request):
    """Get available time slots for a specific date (reads from PostgreSQL).
    Coach availability hours are stored as local time. We convert them to UTC
    using the coach's timezone from profile_data before returning slots."""
    try:
        target_date = _parse_iso_dt(date) or datetime.fromisoformat(date)
    except Exception:
        raise HTTPException(400, "Invalid date format")

    dow = target_date.weekday()  # 0=Monday

    db = getattr(request.app.state, "db_pool", None)
    avail_rows = []
    coach_tz_name = None
    if db:
        try:
            async with db.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, profile_data->>'timezone' as tz FROM users WHERE hardware_id = $1 LIMIT 1", coach_id,
                )
                if row:
                    coach_uuid = row["id"]
                    coach_tz_name = row["tz"]
                    avail_rows = await conn.fetch(
                        """SELECT start_time, end_time, session_duration_minutes
                           FROM coach_availability
                           WHERE coach_id = $1 AND day_of_week = $2
                             AND is_available = TRUE
                             AND (specific_date IS NULL OR specific_date = $3)
                           ORDER BY start_time""",
                        coach_uuid, dow, target_date.date(),
                    )
        except Exception as e:
            _logger.warning("available-slots PG query failed: %s", e)

    # Resolve coach timezone; fall back to UTC if not set
    try:
        from zoneinfo import ZoneInfo
        coach_tz = ZoneInfo(coach_tz_name) if coach_tz_name else timezone.utc
    except Exception:
        coach_tz = timezone.utc

    sessions = await _load_sessions_pf(request)

    booked = []
    for s in sessions:
        if s.get("coach_id") == coach_id and s.get("status") in ["scheduled", "active"]:
            try:
                start = _parse_iso_dt(s.get("scheduled_start", ""))
                if not start:
                    continue
                if start.date() == target_date.date():
                    booked.append({"start": s["scheduled_start"], "end": s["scheduled_end"]})
            except Exception as e:
                _logger.debug("availability: parse session slot failed for %s: %s", s.get("session_id"), e)

    available = []
    for row in avail_rows:
        start_hour = row["start_time"].hour
        end_hour = row["end_time"].hour
        duration = row["session_duration_minutes"] if row["session_duration_minutes"] else 60

        local_date = target_date.date()
        for hour in range(start_hour, end_hour):
            # Build slot in coach's local timezone, then convert to UTC
            naive_local = datetime(local_date.year, local_date.month, local_date.day,
                                   hour, 0, 0)
            local_slot_start = naive_local.replace(tzinfo=coach_tz)
            slot_start_utc = local_slot_start.astimezone(timezone.utc)
            slot_end_utc = slot_start_utc + timedelta(minutes=duration)

            is_free = True
            for b in booked:
                b_start = _parse_iso_dt(b.get("start", ""))
                b_end = _parse_iso_dt(b.get("end", ""))
                if not (b_start and b_end):
                    continue
                if slot_start_utc < b_end and slot_end_utc > b_start:
                    is_free = False
                    break

            if is_free and slot_start_utc > datetime.now(timezone.utc):
                available.append({"start": slot_start_utc.isoformat(), "end": slot_end_utc.isoformat()})

    return {"available_slots": available, "booked": booked, "coach_timezone": coach_tz_name or "UTC"}

# Analytics

@router.get("/stats/coach/{coach_id}")
async def get_coach_stats(coach_id: str, request: Request):
    """Get session statistics for a coach"""
    sessions = await _load_sessions_pf(request)
    coach_sessions = [s for s in sessions if s.get("coach_id") == coach_id]
    
    completed = [s for s in coach_sessions if s.get("status") == "completed"]
    cancelled = [s for s in coach_sessions if s.get("status") == "cancelled"]
    scheduled = [s for s in coach_sessions if s.get("status") == "scheduled"]
    
    total_minutes = sum(s.get("duration_minutes", 0) for s in completed)
    
    # This month
    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0)
    this_month = [s for s in completed if datetime.fromisoformat(s.get("actual_end", "2000-01-01")) >= month_start]
    
    return {
        "total_sessions": len(coach_sessions),
        "completed": len(completed),
        "cancelled": len(cancelled),
        "scheduled": len(scheduled),
        "total_hours": round(total_minutes / 60, 1),
        "sessions_this_month": len(this_month),
        "unique_clients": len(set(s.get("client_id") for s in coach_sessions))
    }


# =============================================================================
# FREE CONSULTATION STATUS
# =============================================================================

@router.get("/consultation-status/{assistant_username}")
async def consultation_status(assistant_username: str, request: Request):
    """Check if an assistant coach has used their daily free consultation (1 per day per assistant)."""
    db = _get_db(request)
    if not db:
        return {"used_today": False, "last_consultation": None}

    try:
        # Resolve assistant_username -> hardware_id (coach_id in sessions is hardware_id)
        hw_row = await db.fetchrow(
            """SELECT hardware_id FROM users WHERE (username = $1 OR hardware_id = $1) AND role = 'COACH' LIMIT 1""",
            assistant_username,
        )
        coach_hw_id = hw_row["hardware_id"] if hw_row else assistant_username
        row = await db.fetchrow(
            """SELECT scheduled_start FROM coaching_sessions
               WHERE coach_id = $1
                 AND session_type = 'MASTER_CONSULTATION'
                 AND (payment_status = 'waived' OR (session_data->>'payment_status') = 'waived')
                 AND scheduled_start::date = CURRENT_DATE
                 AND status NOT IN ('cancelled', 'declined')
               ORDER BY scheduled_start DESC LIMIT 1""",
            coach_hw_id,
        )
        if row:
            return {
                "used_today": True,
                "last_consultation": str(row["scheduled_start"]),
            }
    except Exception as e:
        _logger.warning("consultation_status: query failed: %s", e)

    return {"used_today": False, "last_consultation": None}


# =============================================================================
# CLASSROOM VIDEO UPLOAD
# =============================================================================

ALLOWED_VIDEO_TYPES = {
    "video/mp4", "video/quicktime", "video/webm", "video/x-msvideo",
    "video/mpeg", "video/x-matroska", "application/octet-stream"
}
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "webm", "avi", "mkv", "mpeg"}
MAX_VIDEO_SIZE = 500 * 1024 * 1024  # 500MB
CHUNK_SIZE = 1024 * 1024  # 1MB read chunks

# Magic-byte signatures for video container formats
_VIDEO_SIGNATURES = [
    (4, b"ftyp"),       # MP4 / MOV (at offset 4)
    (0, b"\x1a\x45\xdf\xa3"),  # WebM / MKV (EBML header)
    (0, b"RIFF"),       # AVI (RIFF container)
    (0, b"\x00\x00\x01\xba"),  # MPEG-PS
    (0, b"\x00\x00\x01\xb3"),  # MPEG-1/2 video
]


def _sanitize_filename(raw: str) -> str:
    """Strip path separators, null bytes, and non-printable chars."""
    import re
    name = raw.replace("\x00", "").replace("/", "_").replace("\\", "_")
    name = re.sub(r"[^\w.\-() ]", "_", name)
    return name[:200] or "video"


def _validate_video_magic(header: bytes) -> bool:
    """Return True if header bytes match a known video container signature."""
    for offset, sig in _VIDEO_SIGNATURES:
        if len(header) > offset + len(sig):
            if header[offset : offset + len(sig)] == sig:
                return True
    return False


@router.post("/classroom/upload-video")
async def upload_classroom_video(
    file: UploadFile = File(...),
    coach_id: str = Form(...),
    client_id: str = Form(...),
    family_id: str = Form(""),
    description: str = Form(""),
):
    """Upload a video from device for Classroom analysis."""
    content_type = file.content_type or ""
    raw_filename = file.filename or "video.mp4"
    safe_filename = _sanitize_filename(raw_filename)
    ext = safe_filename.rsplit(".", 1)[-1].lower() if "." in safe_filename else "mp4"

    if content_type not in ALLOWED_VIDEO_TYPES and ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(400, f"Invalid file type: {content_type}. Allowed: MP4, MOV, WEBM, AVI, MKV")

    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        ext = "mp4"

    video_id = f"VID_{datetime.now().strftime('%Y%m%d')}_{secrets.token_hex(4).upper()}"
    safe_coach_id = _sanitize_filename(coach_id)
    video_dir = DATA_DIR / "classroom_videos" / safe_coach_id
    video_dir.mkdir(parents=True, exist_ok=True)
    video_path = video_dir / f"{video_id}.{ext}"

    total_bytes = 0
    header_bytes = b""
    try:
        with open(video_path, "wb") as f:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_VIDEO_SIZE:
                    f.close()
                    video_path.unlink(missing_ok=True)
                    raise HTTPException(413, f"File too large. Maximum size: {MAX_VIDEO_SIZE // (1024*1024)}MB")
                if len(header_bytes) < 32:
                    header_bytes += chunk[:32 - len(header_bytes)]
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        video_path.unlink(missing_ok=True)
        _logger.warning("classroom upload I/O error: %s", e)
        raise HTTPException(500, "Upload failed due to server error")

    if total_bytes == 0:
        video_path.unlink(missing_ok=True)
        raise HTTPException(400, "Empty file")

    if not _validate_video_magic(header_bytes):
        video_path.unlink(missing_ok=True)
        raise HTTPException(
            400, "File does not appear to be a valid video. "
                 "The first bytes do not match any known video format."
        )

    classroom_sessions_file = DATA_DIR / "classroom_sessions.json"
    sessions = load_json(classroom_sessions_file, [])

    r2_key = f"classroom_videos/{safe_coach_id}/{video_id}.{ext}"
    r2_location = str(video_path)
    try:
        from app.services.blob_storage import upload_bytes as blob_upload
        _kind, r2_location = blob_upload(
            rel_path=r2_key, content=video_path.read_bytes(), content_type=content_type,
        )
        _logger.info("Classroom video %s backed up to %s", video_id, _kind)
    except Exception as e:
        _logger.debug("R2 backup of classroom video skipped: %s", e)

    video_session = {
        "session_id": video_id,
        "coach_id": coach_id,
        "client_id": client_id,
        "family_id": family_id,
        "source": "device_upload",
        "filename": safe_filename,
        "video_path": str(video_path),
        "r2_key": r2_key,
        "description": description[:500],
        "content_type": content_type,
        "file_size": total_bytes,
        "status": "uploaded",
        "created_at": str(datetime.now()),
    }

    sessions.append(video_session)
    save_json(classroom_sessions_file, sessions)

    return {
        "video_id": video_id,
        "filename": safe_filename,
        "file_size": total_bytes,
        "message": "Video uploaded successfully. Ready for analysis.",
    }


CHUNK_UPLOAD_DIR = DATA_DIR / "classroom_chunks"
CHUNK_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_CHUNK_SIZE = 60 * 1024 * 1024  # 60MB per chunk (within Cloudflare's 100MB limit)


@router.post("/classroom/upload-chunk")
async def upload_classroom_chunk(
    file: UploadFile = File(...),
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    filename: str = Form("video.mp4"),
    coach_id: str = Form(...),
    client_id: str = Form(""),
):
    """Receive a single chunk of a large video upload."""
    if total_chunks < 1 or total_chunks > 20:
        raise HTTPException(400, "total_chunks must be 1-20")
    if chunk_index < 0 or chunk_index >= total_chunks:
        raise HTTPException(400, f"chunk_index must be 0-{total_chunks - 1}")

    safe_id = _sanitize_filename(upload_id)
    chunk_dir = CHUNK_UPLOAD_DIR / safe_id
    chunk_dir.mkdir(parents=True, exist_ok=True)

    chunk_path = chunk_dir / f"chunk_{chunk_index:04d}"
    total_bytes = 0
    try:
        with open(chunk_path, "wb") as f:
            while True:
                data = await file.read(CHUNK_SIZE)
                if not data:
                    break
                total_bytes += len(data)
                if total_bytes > MAX_CHUNK_SIZE:
                    chunk_path.unlink(missing_ok=True)
                    raise HTTPException(413, f"Chunk too large. Max {MAX_CHUNK_SIZE // (1024*1024)}MB per chunk")
                f.write(data)
    except HTTPException:
        raise
    except Exception as e:
        chunk_path.unlink(missing_ok=True)
        _logger.warning("chunk upload I/O error: %s", e)
        raise HTTPException(500, "Chunk upload failed")

    meta_path = chunk_dir / "meta.json"
    meta = load_json(meta_path, {})
    meta.update({
        "upload_id": upload_id,
        "filename": filename,
        "coach_id": coach_id,
        "client_id": client_id,
        "total_chunks": total_chunks,
        f"chunk_{chunk_index}_size": total_bytes,
        f"chunk_{chunk_index}_at": str(datetime.now()),
    })
    save_json(meta_path, meta)

    received = sum(1 for i in range(total_chunks) if (chunk_dir / f"chunk_{i:04d}").exists())
    return {
        "upload_id": upload_id,
        "chunk_index": chunk_index,
        "chunk_size": total_bytes,
        "received": received,
        "total_chunks": total_chunks,
        "complete": received == total_chunks,
    }


@router.post("/classroom/upload-finalize")
async def finalize_classroom_upload(
    upload_id: str = Form(...),
):
    """Reassemble chunks into a final video file and register it."""
    safe_id = _sanitize_filename(upload_id)
    chunk_dir = CHUNK_UPLOAD_DIR / safe_id
    meta_path = chunk_dir / "meta.json"

    if not meta_path.exists():
        raise HTTPException(404, "Upload not found")

    meta = load_json(meta_path, {})
    total_chunks = meta.get("total_chunks", 0)
    filename = meta.get("filename", "video.mp4")
    coach_id = meta.get("coach_id", "unknown")
    client_id = meta.get("client_id", "")

    missing = [i for i in range(total_chunks) if not (chunk_dir / f"chunk_{i:04d}").exists()]
    if missing:
        raise HTTPException(400, f"Missing chunks: {missing}")

    safe_filename = _sanitize_filename(filename)
    ext = safe_filename.rsplit(".", 1)[-1].lower() if "." in safe_filename else "mp4"
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        ext = "mp4"

    video_id = f"VID_{datetime.now().strftime('%Y%m%d')}_{secrets.token_hex(4).upper()}"
    safe_coach_id = _sanitize_filename(coach_id)
    video_dir = DATA_DIR / "classroom_videos" / safe_coach_id
    video_dir.mkdir(parents=True, exist_ok=True)
    video_path = video_dir / f"{video_id}.{ext}"

    total_bytes = 0
    header_bytes = b""
    try:
        with open(video_path, "wb") as out:
            for i in range(total_chunks):
                chunk_path = chunk_dir / f"chunk_{i:04d}"
                with open(chunk_path, "rb") as inp:
                    while True:
                        data = inp.read(CHUNK_SIZE)
                        if not data:
                            break
                        if len(header_bytes) < 32:
                            header_bytes += data[: 32 - len(header_bytes)]
                        total_bytes += len(data)
                        out.write(data)
    except Exception as e:
        video_path.unlink(missing_ok=True)
        _logger.warning("chunk reassembly error: %s", e)
        raise HTTPException(500, "Failed to reassemble video")

    if total_bytes == 0:
        video_path.unlink(missing_ok=True)
        raise HTTPException(400, "Empty file after reassembly")

    if total_bytes > MAX_VIDEO_SIZE:
        video_path.unlink(missing_ok=True)
        raise HTTPException(413, f"Combined file too large. Max {MAX_VIDEO_SIZE // (1024*1024)}MB")

    if not _validate_video_magic(header_bytes):
        video_path.unlink(missing_ok=True)
        raise HTTPException(400, "File does not appear to be a valid video")

    # Clean up chunks
    import shutil
    shutil.rmtree(chunk_dir, ignore_errors=True)

    r2_key = f"classroom_videos/{safe_coach_id}/{video_id}.{ext}"
    try:
        from app.services.blob_storage import upload_bytes as blob_upload
        _kind, _loc = blob_upload(
            rel_path=r2_key, content=video_path.read_bytes(), content_type=f"video/{ext}",
        )
        _logger.info("Chunked classroom video %s backed up to %s", video_id, _kind)
    except Exception as e:
        _logger.debug("R2 backup of chunked video skipped: %s", e)

    classroom_sessions_file = DATA_DIR / "classroom_sessions.json"
    sessions = load_json(classroom_sessions_file, [])
    sessions.append({
        "session_id": video_id,
        "coach_id": coach_id,
        "client_id": client_id,
        "family_id": "",
        "source": "device_upload",
        "filename": safe_filename,
        "video_path": str(video_path),
        "r2_key": r2_key,
        "description": "",
        "content_type": f"video/{ext}",
        "file_size": total_bytes,
        "status": "uploaded",
        "created_at": str(datetime.now()),
    })
    save_json(classroom_sessions_file, sessions)

    return {
        "video_id": video_id,
        "filename": safe_filename,
        "file_size": total_bytes,
        "message": "Video uploaded successfully. Ready for analysis.",
    }


@router.post("/classroom/auto-upload")
async def auto_upload_recording(
    request: Request,
    session_id: str = Form(""),
    coach_id: str = Form(""),
    client_id: str = Form(""),
    recording_url: str = Form(""),
):
    """Little Nate auto-uploads a session recording for Classroom analysis."""
    db = getattr(request.app.state, "db_pool", None)

    video_id = f"AUTO_{datetime.now().strftime('%Y%m%d')}_{secrets.token_hex(4).upper()}"

    classroom_sessions_file = DATA_DIR / "classroom_sessions.json"
    sessions = load_json(classroom_sessions_file, [])

    auto_session = {
        "session_id": video_id,
        "coach_id": coach_id,
        "client_id": client_id,
        "source": "auto_recording",
        "recording_url": recording_url,
        "status": "processing",
        "created_at": str(datetime.now()),
    }

    sessions.append(auto_session)
    save_json(classroom_sessions_file, sessions)

    if db:
        try:
            async with db.acquire() as conn:
                await conn.execute(
                    """INSERT INTO coach_folder_files (folder_id, filename, file_type, storage_url, uploaded_by, metadata)
                       SELECT id, $2, 'recording', $3, $4, $5::jsonb
                       FROM coach_folders WHERE coach_id = $4 AND entity_id = $6 AND folder_type = 'client'
                       LIMIT 1""",
                    video_id, f"Session Recording {video_id}", recording_url, coach_id,
                    json.dumps({"auto_uploaded": True, "session_id": session_id}),
                    client_id,
                )
        except Exception as e:
            _logger.warning("auto_upload_recording: folder file insert failed: %s", e)

    return {"video_id": video_id, "status": "processing"}


@router.get("/classroom/session/{session_id}/dojo-feedback")
async def get_dojo_feedback(session_id: str, request: Request):
    """Get DOJO-specific feedback for a classroom session recording."""
    db = getattr(request.app.state, "db_pool", None)

    classroom_sessions_file = DATA_DIR / "classroom_sessions.json"
    sessions = load_json(classroom_sessions_file, [])

    session_data = None
    for s in sessions:
        if s.get("session_id") == session_id:
            session_data = s
            break

    if not session_data:
        raise HTTPException(404, "Session not found")

    coach_id = session_data.get("coach_id", "")
    dojo_feedback = []

    if db and coach_id:
        try:
            async with db.acquire() as conn:
                coach_row = await conn.fetchrow(
                    "SELECT profile_data FROM users WHERE hardware_id = $1 AND role = 'COACH'", coach_id
                )
                if coach_row:
                    profile = coach_row["profile_data"]
                    if isinstance(profile, str):
                        profile = json.loads(profile)
                    subs = profile.get("dojo_subscriptions", {})
                    for dojo_key, sub in subs.items():
                        if isinstance(sub, dict) and sub.get("status") == "active":
                            dojo_feedback.append({
                                "dojo": dojo_key,
                                "status": "pending_analysis",
                                "feedback": None,
                                "rubric_dimensions": [],
                            })
        except Exception as e:
            _logger.warning("get_dojo_feedback: profile query failed: %s", e)

    return {
        "session_id": session_id,
        "dojo_feedback": dojo_feedback,
        "status": session_data.get("status", "unknown"),
    }
