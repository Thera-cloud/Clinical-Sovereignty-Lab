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

# Mounted at /api/classroom/* so Flutter can POST /api/classroom/upload-video (not under /api/sessions).
classroom_router = APIRouter(
    prefix="/api/classroom",
    tags=["classroom"],
    dependencies=[Depends(_require_auth)],
)

from app.config import settings as _settings
DATA_DIR = Path(_settings.DATA_DIR)
WORKBOOKS_DIR = Path(_settings.WORKBOOKS_DIR)

from app.services.pg_data_helpers import (
    load_sessions_pg,
    upsert_session_pg,
    delete_session_pg,
    load_registry_pg,
    find_user_pg,
    upsert_classroom_analysis_pg,
)

try:
    from app.services.google_calendar_session_sync import sync_session_for_participants as _gcal_sync
except Exception:
    _gcal_sync = None

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

        try:
            from app.main import app as _app

            db_pg = getattr(_app.state, "db_pool", None) if _app else None
            if db_pg:
                await upsert_classroom_analysis_pg(db_pg, analysis)
        except Exception as _ae_pg:
            print(f"[AutoAnalysis] PG classroom dual-write (non-fatal): {_ae_pg}")

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


async def _ensure_local_copy_for_analysis(video_id: str) -> None:
    """
    If a classroom_sessions.json record points at an R2 key but the local
    video file is missing (i.e. it was uploaded direct-to-R2 from the
    browser), stream the R2 object down to the canonical local path so
    the existing analyzer can operate on it unchanged.

    Best-effort: failures are logged and the analyzer will simply find
    no local file (analysis falls back to its no-frames branch).
    """
    try:
        from app.services import r2_storage  # local import to avoid cycle
    except Exception as e:
        _logger.warning("[ClassroomVideo] R2 import failed for %s: %s", video_id, e)
        return

    classroom_sessions_file = (
        Path(os.getenv("CLASSROOM_SESSIONS_FILE", str(DATA_DIR / "classroom_sessions.json")))
    )
    try:
        with open(classroom_sessions_file, "r", encoding="utf-8") as f:
            sessions = json.load(f)
    except Exception:
        return

    target = None
    for s in sessions:
        if s.get("session_id") == video_id:
            target = s
            break
    if not target:
        return

    r2_key = (target.get("r2_key") or "").strip()
    r2_bucket = (target.get("r2_bucket") or "").strip() or None
    video_path_str = target.get("video_path") or ""

    if not r2_key:
        return  # not an R2-sourced upload
    if video_path_str and Path(video_path_str).exists():
        return  # already cached locally

    coach_id = target.get("coach_id") or "unknown"
    ext = (target.get("filename") or r2_key).rsplit(".", 1)[-1].lower()
    if ext not in ("mp4", "mov", "webm", "avi", "mkv"):
        ext = "mp4"

    local_dir = DATA_DIR / "classroom_videos" / coach_id
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / f"{video_id}.{ext}"

    _logger.info(
        "[ClassroomVideo] Streaming R2 object to local for analysis: %s → %s",
        r2_key,
        local_path,
    )
    ok = await r2_storage.download_to_file_async(
        key=r2_key, dest_path=str(local_path), bucket=r2_bucket
    )
    if not ok:
        _logger.warning(
            "[ClassroomVideo] R2 download failed for %s key=%s; analyzer will see no local file",
            video_id,
            r2_key,
        )
        return

    target["video_path"] = str(local_path)
    try:
        with open(classroom_sessions_file, "w", encoding="utf-8") as f:
            json.dump(sessions, f, indent=2, default=str)
    except Exception as e:
        _logger.warning(
            "[ClassroomVideo] Could not persist video_path back to classroom_sessions.json: %s",
            e,
        )


async def auto_analyze_classroom_video(
    video_id: str,
    coach_id: str,
    client_id: str,
    family_id: str,
    description: str,
):
    """
    Run Classroom video analysis after HTTP upload completes.
    Fire-and-forget from upload handler so the API returns immediately.
    """
    if not _classroom_analyzer:
        _logger.warning("[ClassroomVideo] Auto-analysis skipped: analyzer unavailable")
        return

    # If the source is R2 (direct browser upload), pull down a local copy first.
    await _ensure_local_copy_for_analysis(video_id)

    client_name = ""
    fam = family_id or ""
    try:
        registry_path = DATA_DIR / "registry.json"
        if registry_path.exists() and client_id:
            with open(registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
            for _, v in registry.items():
                p = v.get("profile") or {}
                if p.get("hardware_id") == client_id:
                    if not fam:
                        fam = p.get("family_id", "") or ""
                    client_name = p.get("name", "") or ""
                    break
    except Exception as e:
        _logger.warning("[ClassroomVideo] Registry lookup error: %s", e)

    try:
        _logger.info("[ClassroomVideo] Starting auto-analysis for %s", video_id)
        analysis = await _classroom_analyzer.analyze_video(
            video_id=video_id,
            coach_id=coach_id,
            client_id=client_id or "",
            coach_query=(description or "").strip(),
            focus_area="general",
            family_id=fam,
            client_name=client_name,
        )
        _logger.info("[ClassroomVideo] Auto-analysis finished for %s", video_id)

        try:
            from app.main import app as _app
            from datetime import datetime, timezone

            _pool = getattr(_app.state, "db_pool", None) if _app else None
            if _pool and analysis and not analysis.get("error"):
                from app.services.pg_data_helpers import upsert_session_pg

                _now = datetime.now(timezone.utc)
                _prev = (analysis.get("visual_insights") or "")[:12000]
                await upsert_session_pg(
                    _pool,
                    {
                        "session_id": video_id,
                        "coach_id": coach_id,
                        "client_id": client_id or "",
                        "client_name": client_name or "",
                        "session_type": "CLASSROOM",
                        "status": "completed",
                        "scheduled_start": _now,
                        "duration_minutes": 0,
                        "transcript_archived_at": analysis.get("analyzed_at") or _now.isoformat(),
                        "transcript_location": f"classroom://video/{video_id}",
                        "classroom_device_upload": True,
                        "classroom_video_summary": _prev[:4000],
                    },
                )
        except Exception as _pg_err:
            _logger.warning("[ClassroomVideo] PG mirror for upload failed: %s", _pg_err)
    except Exception as e:
        _logger.exception("[ClassroomVideo] Auto-analysis failed for %s: %s", video_id, e)


# Models
class ScheduleSessionRequest(BaseModel):
    client_id: str
    coach_id: str
    family_id: Optional[str] = ""  # optional linkage for families
    client_name: Optional[str] = ""  # optional display label
    scheduled_start: str  # ISO format
    scheduled_end: str
    session_type: str = "COACH"  # COACH, FAMILY, GROUP, MASTER_CONSULTATION
    notes: Optional[str] = ""
    zoom_link: Optional[str] = ""
    disable_recording: Optional[bool] = False  # Coach can opt-out of auto-recording

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
    # Encrypt session files at rest if encryption key is available.
    # Exclude classroom_sessions.json: it is shared cross-container with the
    # bridge's ClassroomAnalyzer, which reads via plain json.loads. Encrypting
    # it silently breaks the Coach Command "Select Session to Analyze"
    # dropdown. Transcripts themselves live in blob storage and are protected
    # there; this file is just metadata (session_id, coach_id, video_path).
    fernet = _get_fernet()
    name = filepath.name
    if fernet and 'sessions' in str(filepath) and name != 'classroom_sessions.json':
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
    """PG-first session loader. Falls back to JSON."""
    db = _get_db(request)
    if db:
        try:
            pg_sessions = await load_sessions_pg(db)
            if pg_sessions:
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


async def _lookup_client_contact(db_pool, client_id: str) -> dict:
    """Resolve client email / phone / name from users.profile_data."""
    if not db_pool or not client_id:
        return {}
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT profile_data->>'email' AS email, "
                "       profile_data->>'phone' AS phone, "
                "       profile_data->>'name'  AS name "
                "FROM users "
                "WHERE hardware_id = $1 OR username = $1 "
                "LIMIT 1",
                client_id,
            )
        if not row:
            return {}
        return {
            "email": (row["email"] or "").strip(),
            "phone": (row["phone"] or "").strip(),
            "name": (row["name"] or "").strip(),
        }
    except Exception as e:
        _logger.warning("_lookup_client_contact failed for %s: %s", client_id, e)
        return {}


async def _lookup_coach_display(db_pool, coach_id: str) -> dict:
    """Resolve coach display name / credentials from users.profile_data."""
    if not db_pool or not coach_id:
        return {"name": "Your coach", "credentials": ""}
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT profile_data->>'name' AS name, "
                "       profile_data->>'credentials' AS credentials, "
                "       username "
                "FROM users "
                "WHERE hardware_id = $1 OR username = $1 "
                "LIMIT 1",
                coach_id,
            )
        if not row:
            return {"name": "Your coach", "credentials": ""}
        nm = (row["name"] or row["username"] or "Your coach").strip()
        return {
            "name": nm,
            "credentials": (row["credentials"] or "").strip(),
        }
    except Exception:
        return {"name": "Your coach", "credentials": ""}


async def _send_session_link(request: Request, session: dict) -> dict:
    """
    Email + SMS the Zoom join link to the client (and external consultee, if present).
    Mirrors what Zoom sends natively: subject, time, host, agenda, join URL.
    Returns a dict with per-channel delivery results.
    """
    result = {"email": False, "sms": False, "channels": []}
    join_url = (session.get("zoom_link") or "").strip()
    if not join_url:
        result["error"] = "no_zoom_link"
        return result

    db = _get_db(request)
    client_id = (session.get("client_id") or "").strip()
    contact = await _lookup_client_contact(db, client_id)

    # External consultee path overrides registered client contact when present.
    consult_email = (session.get("consultation_email") or "").strip()
    consult_name = (session.get("consultation_name") or "").strip()
    if consult_email and "@" in consult_email:
        contact["email"] = consult_email
    if consult_name:
        contact["name"] = consult_name

    coach_id = (session.get("coach_id") or "").strip()
    coach = await _lookup_coach_display(db, coach_id)
    coach_name = coach["name"]
    coach_initials = (coach_name[:1] or "C").upper()

    # Format date / time from scheduled_start (ISO).
    start_iso = (session.get("scheduled_start") or "").strip()
    date_str = start_iso
    time_str = ""
    try:
        dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        date_str = dt.strftime("%B %d, %Y")
        time_str = dt.strftime("%I:%M %p UTC").lstrip("0")
    except Exception:
        pass

    # ── EMAIL via SendGrid (coaching_confirmation template)
    email_addr = (contact.get("email") or "").strip()
    if email_addr and "@" in email_addr:
        try:
            from app.services.notifications_service import EmailService
            email_svc = EmailService()
            ok = await email_svc.send_coaching_confirmation(
                to_email=email_addr,
                date=date_str,
                time=time_str or start_iso,
                timezone="UTC",
                coach_name=coach_name,
                coach_initials=coach_initials,
                coach_credentials=coach.get("credentials") or "",
                join_url=join_url,
            )
            result["email"] = bool(ok)
            if ok:
                result["channels"].append(f"email:{email_addr}")
        except Exception as e:
            _logger.warning("_send_session_link: email failed: %s", e)

    # ── SMS via NotificationSystem (Twilio)
    phone = (contact.get("phone") or "").strip()
    if phone:
        try:
            notify_sys = getattr(request.app.state, "notification_system", None)
            if notify_sys is None:
                from app.websocket.notification_system import NotificationSystem
                notify_sys = NotificationSystem(
                    data_dir=os.environ.get("DATA_DIR", "/app/data"),
                    sendgrid_key=os.environ.get("SENDGRID_API_KEY"),
                )
                request.app.state.notification_system = notify_sys
            body = (
                f"Sanctuary: Your session with {coach_name}"
                + (f" on {date_str}" if date_str else "")
                + (f" at {time_str}" if time_str else "")
                + f"\nJoin Zoom: {join_url}"
            )
            ok = await notify_sys.send_sms(phone, body)
            result["sms"] = bool(ok)
            if ok:
                result["channels"].append(f"sms:{phone}")
        except Exception as e:
            _logger.warning("_send_session_link: sms failed: %s", e)

    return result


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
                raise HTTPException(409, "Time slot conflict with existing session")
    
    session_id = generate_session_id()

    _is_consultation = req.session_type == "MASTER_CONSULTATION"

    session = {
        "session_id": session_id,
        "client_id": req.client_id,
        "coach_id": req.coach_id,
        "family_id": req.family_id or "",
        "client_name": req.client_name or "",
        "session_type": req.session_type,
        "status": "scheduled",
        "scheduled_start": req.scheduled_start,
        "scheduled_end": req.scheduled_end,
        "actual_start": None,
        "actual_end": None,
        "duration_minutes": 0,
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
        "price_cents": 0 if _is_consultation else None,
        "payment_status": "waived" if _is_consultation else "pending",
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

    # Fire-and-forget Google Calendar push for both coach and client (if connected).
    if _gcal_sync:
        try:
            db_pool = getattr(request.app.state, "db_pool", None)
            if db_pool:
                asyncio.create_task(_gcal_sync(db_pool, session, action="create"))
        except Exception:
            pass

    # Auto-send Zoom join link via email + SMS if a link exists.
    notify_result = None
    if (session.get("zoom_link") or "").strip():
        try:
            notify_result = await _send_session_link(request, session)
            print(f">>> [SESSION] Auto-sent link for {session_id}: {notify_result}")
        except Exception as e:
            print(f">>> [SESSION] Auto-send link failed for {session_id}: {e}")

    resp = {"session": session}
    if zoom_error:
        resp["zoom_error"] = zoom_error
    if notify_result is not None:
        resp["notification"] = notify_result
    return resp


@router.post("/{session_id}/resend-link")
async def resend_session_link(session_id: str, request: Request):
    """
    Resend the Zoom join link to the client via email + SMS.
    Triggered from the coach's Schedule tab "Resend Link" action.
    """
    sessions = await _load_sessions_pf(request)
    session = next((s for s in sessions if s.get("session_id") == session_id), None)
    if not session:
        raise HTTPException(404, f"Session {session_id} not found")
    if not (session.get("zoom_link") or "").strip():
        raise HTTPException(400, "Session has no Zoom link to resend")

    notify_result = await _send_session_link(request, session)
    if not notify_result.get("email") and not notify_result.get("sms"):
        # Surface a useful error so the UI can render a snackbar.
        return {
            "session_id": session_id,
            "sent": False,
            "notification": notify_result,
            "message": "No deliverable channels — client has no email or phone on file.",
        }
    return {
        "session_id": session_id,
        "sent": True,
        "notification": notify_result,
    }

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
            s["actual_start"] = str(datetime.now())
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
            s["status"] = "completed"
            s["actual_end"] = str(datetime.now())
            s["mood_at_end"] = mood_at_end
            s["nate_summary"] = summary
            
            if s.get("actual_start"):
                try:
                    start = datetime.fromisoformat(s["actual_start"])
                    end = datetime.now()
                    s["duration_minutes"] = int((end - start).total_seconds() / 60)
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
            
            print(f"[Archive] Step 2: Metrics extracted - {analysis_result.get('metrics', {}).get('total_duration_minutes', 0):.1f} min session")
            target["nate_read_transcript_at"] = str(datetime.now())
            target["nate_extracted_metrics"] = True

            try:
                db_pg = _get_db(request)
                if db_pg:
                    await upsert_classroom_analysis_pg(db_pg, analysis_result)
            except Exception as _arc_pg:
                _logger.warning(
                    "archive_zoom_transcript: PG classroom dual-write: %s", _arc_pg
                )

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
            if _gcal_sync:
                try:
                    db_pool = getattr(request.app.state, "db_pool", None)
                    if db_pool:
                        action = "delete" if s.get("status") in ("cancelled", "no_show") else "update"
                        asyncio.create_task(_gcal_sync(db_pool, s, action=action))
                except Exception:
                    pass
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
                if _gcal_sync:
                    try:
                        db_pool = getattr(request.app.state, "db_pool", None)
                        if db_pool:
                            asyncio.create_task(_gcal_sync(db_pool, deleted_session, action="delete"))
                    except Exception:
                        pass
                return {"message": "Session permanently deleted", "session": deleted_session}
            else:
                s["status"] = "cancelled"
                s["cancellation_reason"] = reason
                s["cancelled_at"] = str(datetime.now())
                await _save_session_dual(request, s, sessions)
                if _gcal_sync:
                    try:
                        db_pool = getattr(request.app.state, "db_pool", None)
                        if db_pool:
                            asyncio.create_task(_gcal_sync(db_pool, s, action="delete"))
                    except Exception:
                        pass
                return {"message": "Session cancelled", "session": s}

    raise HTTPException(404, "Session not found")

# Coach Availability

@router.post("/availability")
async def set_coach_availability(req: CoachAvailabilityRequest):
    """Set coach's availability slots"""
    availability_file = DATA_DIR / "Vaults" / "Coaches" / req.coach_id / "availability.json"
    availability_file.parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        "coach_id": req.coach_id,
        "timezone": req.timezone,
        "slots": req.slots,
        "updated_at": str(datetime.now())
    }
    
    save_json(availability_file, data)
    return {"availability": data}

@router.get("/availability/{coach_id}")
async def get_coach_availability(coach_id: str):
    """Get coach's availability"""
    availability_file = DATA_DIR / "Vaults" / "Coaches" / coach_id / "availability.json"
    availability = load_json(availability_file, {"slots": [], "timezone": "America/New_York"})
    return {"availability": availability}

@router.get("/available-slots/{coach_id}")
async def get_available_slots(coach_id: str, date: str, request: Request):
    """Get available time slots for a specific date"""
    availability_file = DATA_DIR / "Vaults" / "Coaches" / coach_id / "availability.json"
    availability = load_json(availability_file, {"slots": []})

    sessions = await _load_sessions_pf(request)
    
    # Parse date
    try:
        target_date = _parse_iso_dt(date) or datetime.fromisoformat(date)
        day_name = target_date.strftime("%A").lower()
    except:
        raise HTTPException(400, "Invalid date format")
    
    # Find slots for this day of week
    day_slots = [s for s in availability.get("slots", []) if s.get("day", "").lower() == day_name]
    
    # Get booked times for this date
    booked = []
    for s in sessions:
        if s.get("coach_id") == coach_id and s.get("status") in ["scheduled", "active"]:
            try:
                start = _parse_iso_dt(s.get("scheduled_start", ""))
                if not start:
                    continue
                if start.date() == target_date.date():
                    booked.append({
                        "start": s["scheduled_start"],
                        "end": s["scheduled_end"]
                    })
            except:
                pass
    
    # Generate available 1-hour slots
    available = []
    for slot in day_slots:
        start_hour = int(slot.get("start", "09:00").split(":")[0])
        end_hour = int(slot.get("end", "17:00").split(":")[0])
        
        for hour in range(start_hour, end_hour):
            slot_start = target_date.replace(hour=hour, minute=0, second=0)
            slot_end = slot_start + timedelta(hours=1)
            
            # Check if slot is available
            is_available = True
            for b in booked:
                b_start = _parse_iso_dt(b.get("start", ""))
                b_end = _parse_iso_dt(b.get("end", ""))
                if not (b_start and b_end):
                    continue
                if slot_start < b_end and slot_end > b_start:
                    is_available = False
                    break
            
            if is_available and slot_start > datetime.now(timezone.utc):
                available.append({
                    "start": slot_start.isoformat(),
                    "end": slot_end.isoformat()
                })
    
    return {"available_slots": available, "booked": booked}

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
# CLASSROOM VIDEO UPLOAD
# =============================================================================

ALLOWED_VIDEO_TYPES = {
    "video/mp4", "video/quicktime", "video/webm", "video/x-msvideo",
    "video/mpeg", "video/x-matroska", "application/octet-stream"
}
MAX_VIDEO_SIZE = 500 * 1024 * 1024  # 500MB


@classroom_router.post("/upload-video")
async def upload_classroom_video(
    request: Request,
    file: UploadFile = File(...),
    coach_id: str = Form(...),
    client_id: str = Form(...),
    family_id: str = Form(""),
    description: str = Form(""),
):
    """Upload a video from device for Classroom analysis."""
    # Validate file type
    content_type = file.content_type or ""
    if content_type not in ALLOWED_VIDEO_TYPES:
        ext = (file.filename or "").rsplit(".", 1)[-1].lower()
        if ext not in ("mp4", "mov", "webm", "avi", "mkv", "mpeg"):
            raise HTTPException(400, f"Invalid file type: {content_type}. Allowed: MP4, MOV, WEBM, AVI")
    
    # Read file content
    content = await file.read()
    if len(content) > MAX_VIDEO_SIZE:
        raise HTTPException(413, f"File too large. Maximum size: {MAX_VIDEO_SIZE // (1024*1024)}MB")
    
    # Generate video ID
    video_id = f"VID_{datetime.now().strftime('%Y%m%d')}_{secrets.token_hex(4).upper()}"
    
    # Save to classroom_videos directory
    video_dir = DATA_DIR / "classroom_videos" / coach_id
    video_dir.mkdir(parents=True, exist_ok=True)
    
    ext = (file.filename or "video.mp4").rsplit(".", 1)[-1].lower()
    if ext not in ("mp4", "mov", "webm", "avi", "mkv"):
        ext = "mp4"
    video_path = video_dir / f"{video_id}.{ext}"
    
    with open(video_path, "wb") as f:
        f.write(content)
    
    # Create a pseudo-session record for the classroom
    classroom_sessions_file = DATA_DIR / "classroom_sessions.json"
    sessions = load_json(classroom_sessions_file, [])
    
    video_session = {
        "session_id": video_id,
        "coach_id": coach_id,
        "client_id": client_id,
        "family_id": family_id,
        "source": "device_upload",
        "filename": file.filename or f"{video_id}.{ext}",
        "video_path": str(video_path),
        "description": description,
        "content_type": content_type,
        "file_size": len(content),
        "status": "uploaded",
        "created_at": str(datetime.now()),
    }
    
    sessions.append(video_session)
    save_json(classroom_sessions_file, sessions)

    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool:
        try:
            await upsert_session_pg(
                db_pool,
                {
                    "session_id": video_id,
                    "coach_id": coach_id,
                    "client_id": client_id,
                    "client_name": "",
                    "family_id": family_id or "",
                    "session_type": "classroom_upload",
                    "status": "uploaded",
                    "scheduled_start": datetime.now(timezone.utc).isoformat(),
                    "duration_minutes": 0,
                    "classroom_device_upload": "true",
                    "filename": video_session["filename"],
                    "video_path": str(video_path),
                },
            )
        except Exception as _pg_exc:
            _logger.warning("classroom upload: coaching_sessions upsert failed: %s", _pg_exc)

    # Option A: analyze in background so upload response returns immediately (same analyzer as WebSocket path)
    asyncio.create_task(
        auto_analyze_classroom_video(
            video_id=video_id,
            coach_id=coach_id,
            client_id=client_id,
            family_id=family_id or "",
            description=description or "",
        )
    )

    return {
        "video_id": video_id,
        "filename": file.filename,
        "file_size": len(content),
        "message": "Video uploaded successfully. Analysis running in the background.",
    }


# =============================================================================
# CLASSROOM VIDEO UPLOAD — Direct-to-R2 multipart (large files: up to 5GB+)
#
# The legacy /upload-video endpoint above streams bytes through the FastAPI
# origin (capped at 500MB by both FastAPI memory and the Cloudflare proxy's
# 100MB upload limit). For 3 GB+ recordings the browser PUTs each chunk
# directly to R2 using presigned URLs — bytes never traverse our origin.
# =============================================================================

# Hard upper bound at the API layer. R2 supports up to 5 TiB; we cap at 5 GiB
# for sanity and to avoid a single coach accidentally pushing TBs of footage.
MAX_DIRECT_VIDEO_SIZE = 5 * 1024 * 1024 * 1024  # 5 GiB


class _MultipartInitRequest(BaseModel):
    coach_id: str
    client_id: str
    family_id: Optional[str] = ""
    description: Optional[str] = ""
    filename: str
    content_type: Optional[str] = "video/mp4"
    file_size: int  # bytes


class _MultipartCompletePart(BaseModel):
    PartNumber: int
    ETag: str


class _MultipartCompleteRequest(BaseModel):
    video_id: str
    parts: List[_MultipartCompletePart]


class _MultipartAbortRequest(BaseModel):
    video_id: str


def _validate_video_filename(name: str) -> str:
    """Return a sanitized extension for a classroom video filename."""
    ext = (name or "video.mp4").rsplit(".", 1)[-1].lower()
    if ext not in ("mp4", "mov", "webm", "avi", "mkv", "mpeg"):
        ext = "mp4"
    return ext


@classroom_router.post("/upload-video/init")
async def upload_classroom_video_init(request: Request, body: _MultipartInitRequest):
    """
    Begin a direct-browser → R2 multipart upload.

    Returns the per-part presigned PUT URLs the browser uses to push each
    chunk straight to R2 storage (no CF proxy, no origin memory pressure).

    The browser MUST:
      1. Slice the local file with `Blob.slice(start, end)` per part.
      2. PUT each chunk to its presigned URL (no auth header — the URL
         is signed). Capture the `ETag` response header per part.
      3. Call POST /api/classroom/upload-video/complete with the parts list.

    On any failure / cancellation, call POST /api/classroom/upload-video/abort
    so R2 releases staged-part storage.
    """
    from app.services import r2_storage

    if not r2_storage.is_r2_configured():
        raise HTTPException(503, "R2 storage is not configured on this deployment")
    if body.file_size <= 0:
        raise HTTPException(400, "file_size must be > 0")
    if body.file_size > MAX_DIRECT_VIDEO_SIZE:
        raise HTTPException(
            413,
            f"File too large: {body.file_size} bytes. "
            f"Maximum is {MAX_DIRECT_VIDEO_SIZE // (1024 ** 3)} GiB.",
        )

    ext = _validate_video_filename(body.filename)
    video_id = f"VID_{datetime.now().strftime('%Y%m%d')}_{secrets.token_hex(4).upper()}"
    key = f"classroom_videos/{body.coach_id}/{video_id}.{ext}"

    part_size = r2_storage.DEFAULT_MULTIPART_PART_SIZE
    total_parts = (body.file_size + part_size - 1) // part_size
    if total_parts > r2_storage.MAX_MULTIPART_PARTS:
        # Re-derive a larger part size to fit within the 10000-part S3 cap.
        part_size = ((body.file_size + r2_storage.MAX_MULTIPART_PARTS - 1) //
                     r2_storage.MAX_MULTIPART_PARTS)
        # Round up to nearest MiB for niceness.
        part_size = ((part_size + (1024 * 1024) - 1) // (1024 * 1024)) * (1024 * 1024)
        total_parts = (body.file_size + part_size - 1) // part_size

    mpu = r2_storage.create_multipart_upload(
        key=key,
        content_type=body.content_type or "application/octet-stream",
        metadata={
            "coach_id": body.coach_id,
            "client_id": body.client_id,
            "video_id": video_id,
        },
    )
    if not mpu:
        raise HTTPException(502, "Failed to initiate R2 multipart upload")

    upload_id = mpu["upload_id"]
    bucket = mpu["bucket"]

    # Presign every part up front. Each URL is valid for 6 hours which is
    # ample headroom for a 3 GB upload over a slow connection.
    parts: List[Dict] = []
    for part_number in range(1, total_parts + 1):
        url = r2_storage.generate_presigned_part_url(
            key=key,
            upload_id=upload_id,
            part_number=part_number,
            bucket=bucket,
        )
        if not url:
            r2_storage.abort_multipart_upload(key=key, upload_id=upload_id, bucket=bucket)
            raise HTTPException(502, f"Failed to presign part {part_number}")
        parts.append({"part_number": part_number, "url": url})

    classroom_sessions_file = (
        Path(os.getenv("CLASSROOM_SESSIONS_FILE", str(DATA_DIR / "classroom_sessions.json")))
    )
    sessions = load_json(classroom_sessions_file, [])
    sessions.append({
        "session_id": video_id,
        "coach_id": body.coach_id,
        "client_id": body.client_id,
        "family_id": body.family_id or "",
        "source": "device_upload_r2",
        "filename": body.filename or f"{video_id}.{ext}",
        "video_path": "",  # populated after analysis pulls a local copy
        "r2_bucket": bucket,
        "r2_key": key,
        "r2_upload_id": upload_id,
        "description": body.description or "",
        "content_type": body.content_type or "video/mp4",
        "file_size": body.file_size,
        "status": "uploading",
        "created_at": str(datetime.now()),
    })
    try:
        save_json(classroom_sessions_file, sessions)
    except OSError as e:
        # Avoid orphaned R2 multipart uploads if bind-mounted /app/data is not writable.
        r2_storage.abort_multipart_upload(key=key, upload_id=upload_id, bucket=bucket)
        _logger.error(
            "upload_classroom_video_init: cannot write %s: %s",
            classroom_sessions_file,
            e,
        )
        raise HTTPException(
            503,
            "Cannot persist classroom session metadata (check DATA_DIR permissions on the host).",
        ) from e

    return {
        "video_id": video_id,
        "upload_id": upload_id,
        "bucket": bucket,
        "key": key,
        "part_size": part_size,
        "total_parts": total_parts,
        "parts": parts,
    }


@classroom_router.post("/upload-video/complete")
async def upload_classroom_video_complete(
    request: Request, body: _MultipartCompleteRequest
):
    """
    Finalize a multipart upload after the browser has PUT every part.

    Persists the session record in coaching_sessions and kicks off the
    same auto_analyze_classroom_video pipeline used by the legacy path
    (which now knows how to stream the object back from R2 for analysis).
    """
    from app.services import r2_storage

    classroom_sessions_file = (
        Path(os.getenv("CLASSROOM_SESSIONS_FILE", str(DATA_DIR / "classroom_sessions.json")))
    )
    sessions = load_json(classroom_sessions_file, [])

    target_idx = -1
    for i, s in enumerate(sessions):
        if s.get("session_id") == body.video_id:
            target_idx = i
            break
    if target_idx < 0:
        raise HTTPException(404, f"Upload session {body.video_id} not found")

    target = sessions[target_idx]
    upload_id = target.get("r2_upload_id") or ""
    key = target.get("r2_key") or ""
    bucket = target.get("r2_bucket") or None
    if not upload_id or not key:
        raise HTTPException(400, "Session does not have an R2 upload in progress")

    parts_payload = [
        {"PartNumber": p.PartNumber, "ETag": p.ETag} for p in body.parts
    ]
    result = r2_storage.complete_multipart_upload(
        key=key, upload_id=upload_id, parts=parts_payload, bucket=bucket
    )
    if not result:
        raise HTTPException(502, "R2 complete_multipart_upload failed")

    target["status"] = "uploaded"
    target["completed_at"] = str(datetime.now())
    target["r2_etag"] = result.get("ETag", "")
    target["r2_location"] = f"r2://{bucket}/{key}"
    sessions[target_idx] = target
    save_json(classroom_sessions_file, sessions)

    coach_id = target.get("coach_id") or ""
    client_id = target.get("client_id") or ""
    family_id = target.get("family_id") or ""
    description = target.get("description") or ""

    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool:
        try:
            await upsert_session_pg(
                db_pool,
                {
                    "session_id": body.video_id,
                    "coach_id": coach_id,
                    "client_id": client_id,
                    "client_name": "",
                    "family_id": family_id,
                    "session_type": "classroom_upload",
                    "status": "uploaded",
                    "scheduled_start": datetime.now(timezone.utc).isoformat(),
                    "duration_minutes": 0,
                    "classroom_device_upload": "true",
                    "filename": target.get("filename"),
                    "video_path": f"r2://{bucket}/{key}",
                },
            )
        except Exception as _pg_exc:
            _logger.warning(
                "[ClassroomVideo] coaching_sessions upsert failed (R2 path): %s", _pg_exc
            )

    asyncio.create_task(
        auto_analyze_classroom_video(
            video_id=body.video_id,
            coach_id=coach_id,
            client_id=client_id,
            family_id=family_id,
            description=description,
        )
    )

    return {
        "video_id": body.video_id,
        "status": "uploaded",
        "r2_location": target["r2_location"],
        "file_size": target.get("file_size"),
        "message": "Upload finalized. Analysis running in the background.",
    }


@classroom_router.post("/upload-video/abort")
async def upload_classroom_video_abort(
    request: Request, body: _MultipartAbortRequest
):
    """
    Abort an in-flight multipart upload (frees R2-side staged-part storage).
    Removes the placeholder session record from classroom_sessions.json.
    """
    from app.services import r2_storage

    classroom_sessions_file = (
        Path(os.getenv("CLASSROOM_SESSIONS_FILE", str(DATA_DIR / "classroom_sessions.json")))
    )
    sessions = load_json(classroom_sessions_file, [])

    target = None
    remaining: List[Dict] = []
    for s in sessions:
        if s.get("session_id") == body.video_id:
            target = s
        else:
            remaining.append(s)
    if target is None:
        raise HTTPException(404, f"Upload session {body.video_id} not found")

    upload_id = target.get("r2_upload_id") or ""
    key = target.get("r2_key") or ""
    bucket = target.get("r2_bucket") or None

    aborted = False
    if upload_id and key:
        aborted = r2_storage.abort_multipart_upload(
            key=key, upload_id=upload_id, bucket=bucket
        )

    save_json(classroom_sessions_file, remaining)
    return {"video_id": body.video_id, "aborted": aborted}


@classroom_router.post("/auto-upload")
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


@classroom_router.get("/session/{session_id}/dojo-feedback")
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
