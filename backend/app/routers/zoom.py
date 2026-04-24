"""
Zoom integration endpoints (FastAPI):
- Webhook receiver with signature verification
- Meeting creation endpoint (optional convenience)
- Transcript ingestion pipeline (Patent 2 Section 16)

This stays additive: if ENABLE_ZOOM is false, endpoints still exist but will return
clear errors when called without configuration.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from app.config import settings
from app.services.api_server import require_coach, require_admin
from app.services.zoom_client import ZoomClient
from app.services.zoom_webhook import verify_signature, url_validation_response


logger = logging.getLogger("zoom_integration")

router = APIRouter(prefix="/api/zoom", tags=["zoom"])

from app.config import settings as _settings
DATA_DIR = Path(_settings.DATA_DIR)
ZOOM_EVENTS_FILE = DATA_DIR / "zoom_events.json"
ZOOM_MEETING_MAP_FILE = DATA_DIR / "zoom_meeting_map.json"  # meeting_id -> internal session metadata
ZOOM_WEBHOOK_ERRORS_FILE = DATA_DIR / "zoom_webhook_errors.json"
ZOOM_INGESTED_FILE = DATA_DIR / "zoom_ingested_sessions.json"  # ingested transcripts log

# In-memory dedup for recording events (WH-M10)
_processed_zoom_events: set = set()


def _load_json(path: Path, default: Any):
    try:
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

def _append_json_list(path: Path, item: Any, cap: int = 3000) -> None:
    """
    Best-effort append to a JSON list on disk.
    Used for webhook diagnostics; never raises.
    L9: File size check and rotation when too large.
    """
    try:
        # L9: Refuse to append if file exceeds 50MB
        if path.exists() and path.stat().st_size > 50_000_000:
            # Rotate: rename to .old and start fresh
            try:
                path.rename(path.with_suffix(path.suffix + ".old"))
            except Exception:
                pass
        items = _load_json(path, []) or []
        if not isinstance(items, list):
            items = []
        items.append(item)
        _save_json(path, items[-cap:])
    except Exception:
        return


class CreateMeetingRequest(BaseModel):
    # Internal linkage (optional but recommended)
    schedule_session_id: Optional[str] = None
    client_id: Optional[str] = None
    family_id: Optional[str] = None

    topic: str
    start_time_iso: str  # ISO string
    duration_minutes: int = 50
    agenda: str = ""


@router.post("/meetings/create", dependencies=[Depends(require_coach)])
async def create_meeting(req: CreateMeetingRequest):
    if not settings.ENABLE_ZOOM:
        raise HTTPException(status_code=400, detail="Zoom disabled (ENABLE_ZOOM=false)")
    if not settings.ZOOM_ACCOUNT_ID or not settings.ZOOM_CLIENT_ID or not settings.ZOOM_CLIENT_SECRET:
        raise HTTPException(status_code=400, detail="Zoom not configured (missing env vars)")

    client = ZoomClient(
        account_id=settings.ZOOM_ACCOUNT_ID,
        client_id=settings.ZOOM_CLIENT_ID,
        client_secret=settings.ZOOM_CLIENT_SECRET,
        host_user=settings.ZOOM_HOST_USER,
        default_timezone=settings.ZOOM_DEFAULT_TIMEZONE,
        default_waiting_room=settings.ZOOM_DEFAULT_WAITING_ROOM,
        default_join_before_host=settings.ZOOM_DEFAULT_JOIN_BEFORE_HOST,
        default_auto_recording=settings.ZOOM_DEFAULT_AUTO_RECORDING,
    )

    try:
        zoom_resp = await client.create_meeting(
            topic=req.topic,
            start_time_iso=req.start_time_iso,
            duration_minutes=req.duration_minutes,
            agenda=req.agenda,
        )
    except httpx.HTTPStatusError as e:
        # Surface the response body (trimmed) so you can fix scopes/config quickly.
        body = ""
        try:
            body = (e.response.text or "")[:2000]
        except Exception:
            body = ""
        raise HTTPException(
            status_code=502,
            detail={
                "error": "zoom_api_error",
                "zoom_status": getattr(e.response, "status_code", None),
                "zoom_body": body,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "zoom_create_failed", "message": str(e)})

    # Save mapping so webhooks can attach to the correct internal session/folder
    meeting_id = str(zoom_resp.get("id") or "")
    if meeting_id:
        mm = _load_json(ZOOM_MEETING_MAP_FILE, {}) or {}
        if not isinstance(mm, dict):
            mm = {}
        mm[meeting_id] = {
            "updated_at": dt.datetime.utcnow().isoformat(),
            "schedule_session_id": req.schedule_session_id or "",
            "client_id": req.client_id or "",
            "family_id": req.family_id or "",
            "topic": req.topic,
        }
        _save_json(ZOOM_MEETING_MAP_FILE, mm)

    return {"zoom_meeting": zoom_resp}


@router.post("/webhook")
async def zoom_webhook(
    request: Request,
    x_zm_request_timestamp: Optional[str] = Header(default=None),
    x_zm_signature: Optional[str] = Header(default=None),
):
    if not settings.ENABLE_ZOOM:
        raise HTTPException(status_code=404, detail="Not Found")
    raw = await request.body()
    secret = (settings.ZOOM_WEBHOOK_SECRET_TOKEN or "").strip()

    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        _append_json_list(
            ZOOM_WEBHOOK_ERRORS_FILE,
            {
                "received_at": dt.datetime.utcnow().isoformat(),
                "error": "invalid_json",
                "content_length": len(raw or b""),
                "has_signature_headers": bool(x_zm_request_timestamp and x_zm_signature),
            },
        )
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = (payload.get("event") or "").strip()

    # URL validation handshake
    if event == "endpoint.url_validation":
        # Zoom's url_validation handshake is commonly sent without the signature headers.
        # We still require the configured secret token so we can generate encryptedToken.
        if not secret:
            _append_json_list(
                ZOOM_WEBHOOK_ERRORS_FILE,
                {
                    "received_at": dt.datetime.utcnow().isoformat(),
                    "error": "missing_secret_for_url_validation",
                    "event": event,
                },
            )
            raise HTTPException(status_code=400, detail="Missing ZOOM_WEBHOOK_SECRET_TOKEN")
        plain = (((payload.get("payload") or {}).get("plainToken")) or "").strip()
        if not plain:
            _append_json_list(
                ZOOM_WEBHOOK_ERRORS_FILE,
                {
                    "received_at": dt.datetime.utcnow().isoformat(),
                    "error": "missing_plainToken",
                    "event": event,
                    "has_signature_headers": bool(x_zm_request_timestamp and x_zm_signature),
                },
            )
            raise HTTPException(status_code=400, detail="Missing plainToken")
        plain_token, encrypted = url_validation_response(secret, plain)
        _append_json_list(
            ZOOM_WEBHOOK_ERRORS_FILE,
            {
                "received_at": dt.datetime.utcnow().isoformat(),
                "event": event,
                "status": "url_validation_responded",
                "has_signature_headers": bool(x_zm_request_timestamp and x_zm_signature),
            },
        )
        return {"plainToken": plain_token, "encryptedToken": encrypted}

    # Verify signature for all other events when enabled (fail closed).
    if settings.ENABLE_ZOOM:
        if not secret:
            _append_json_list(
                ZOOM_WEBHOOK_ERRORS_FILE,
                {
                    "received_at": dt.datetime.utcnow().isoformat(),
                    "error": "missing_secret",
                    "event": event,
                    "has_signature_headers": bool(x_zm_request_timestamp and x_zm_signature),
                },
            )
            raise HTTPException(status_code=400, detail="Missing ZOOM_WEBHOOK_SECRET_TOKEN")
        if not x_zm_request_timestamp or not x_zm_signature:
            _append_json_list(
                ZOOM_WEBHOOK_ERRORS_FILE,
                {
                    "received_at": dt.datetime.utcnow().isoformat(),
                    "error": "missing_signature_headers",
                    "event": event,
                    "has_timestamp": bool(x_zm_request_timestamp),
                    "has_signature": bool(x_zm_signature),
                },
            )
            raise HTTPException(status_code=400, detail="Missing Zoom signature headers")
        if not verify_signature(secret, x_zm_request_timestamp, x_zm_signature, raw):
            _append_json_list(
                ZOOM_WEBHOOK_ERRORS_FILE,
                {
                    "received_at": dt.datetime.utcnow().isoformat(),
                    "error": "invalid_signature",
                    "event": event,
                    "x_zm_request_timestamp": x_zm_request_timestamp,
                    "x_zm_signature": x_zm_signature,
                    "content_length": len(raw or b""),
                },
            )
            raise HTTPException(status_code=401, detail="Invalid Zoom signature")

    # Persist raw event (append)
    events = _load_json(ZOOM_EVENTS_FILE, []) or []
    if not isinstance(events, list):
        events = []

    # Attach internal mapping if possible
    meeting_id = ""
    try:
        meeting_id = str((((payload.get("payload") or {}).get("object") or {}).get("id")) or "")
    except Exception:
        meeting_id = ""

    mapping = {}
    if meeting_id:
        mm = _load_json(ZOOM_MEETING_MAP_FILE, {}) or {}
        if isinstance(mm, dict):
            mapping = mm.get(meeting_id, {}) or {}

    events.append({
        "received_at": dt.datetime.utcnow().isoformat(),
        "event": event,
        "meeting_id": meeting_id,
        "mapping": mapping,
        "payload": payload,
    })
    # cap size
    events = events[-3000:]
    _save_json(ZOOM_EVENTS_FILE, events)

    # =========================================================================
    # TRANSCRIPT INGESTION TRIGGER (Patent 2, Section 16)
    # On recording.completed or phone.recording_completed, spawn background
    # task to download transcript and feed through MetricsEngine.
    # =========================================================================
    if event in ("recording.completed", "phone.recording_completed"):
        dedup_key = f"{meeting_id}_{event}"
        if dedup_key in _processed_zoom_events:
            return {"status": "already_processed"}
        _processed_zoom_events.add(dedup_key)
        if len(_processed_zoom_events) > 10000:
            _processed_zoom_events.clear()

        session_source = "zoom_phone" if "phone" in event else "zoom_meeting"
        try:
            asyncio.create_task(
                _process_recording_event(payload, meeting_id, mapping, session_source)
            )
            logger.info(f"[Zoom] Spawned ingestion task for {event}, meeting={meeting_id}")
        except Exception as e:
            logger.error(f"[Zoom] Failed to spawn ingestion task: {e}")
            _append_json_list(ZOOM_WEBHOOK_ERRORS_FILE, {
                "received_at": dt.datetime.utcnow().isoformat(),
                "error": "ingestion_spawn_failed",
                "event": event,
                "meeting_id": meeting_id,
                "detail": str(e),
            })

    # =========================================================================
    # MEETING UPDATE / DELETE → mirror to coaching_sessions + Google Calendar
    # =========================================================================
    if event in ("meeting.updated", "meeting.deleted") and meeting_id:
        dedup_key = f"{meeting_id}_{event}_{(payload.get('event_ts') or '')}"
        if dedup_key in _processed_zoom_events:
            return {"status": "already_processed"}
        _processed_zoom_events.add(dedup_key)
        if len(_processed_zoom_events) > 10000:
            _processed_zoom_events.clear()
        try:
            asyncio.create_task(
                _process_meeting_lifecycle_event(event, payload, meeting_id, mapping)
            )
        except Exception as e:
            logger.error(f"[Zoom] Failed to spawn meeting lifecycle task: {e}")

    return {"status": "ok"}


# =============================================================================
# BACKGROUND: meeting.updated / meeting.deleted → coaching_sessions + Google
# =============================================================================
async def _process_meeting_lifecycle_event(
    event: str,
    payload: Dict[str, Any],
    meeting_id: str,
    mapping: Dict[str, Any],
) -> None:
    """Mirror Zoom meeting.updated/deleted into coaching_sessions and push to
    Google Calendar (best-effort, fire-and-forget)."""
    try:
        from app.main import app  # late import to avoid circular at module load
    except Exception:
        return
    db_pool = getattr(app.state, "db_pool", None) if app else None
    if not db_pool:
        return

    obj = (payload.get("payload") or {}).get("object") or {}
    new_start = obj.get("start_time") or ""  # ISO 8601, e.g. 2026-04-20T14:00:00Z
    new_duration = obj.get("duration") or 0  # minutes
    new_topic = obj.get("topic") or ""

    session_id = (mapping or {}).get("session_id") or ""
    try:
        async with db_pool.acquire() as conn:
            row = None
            if session_id:
                row = await conn.fetchrow(
                    "SELECT * FROM coaching_sessions WHERE session_id = $1",
                    session_id,
                )
            if row is None:
                # Fallback: look up by zoom_meeting_id
                row = await conn.fetchrow(
                    "SELECT * FROM coaching_sessions WHERE zoom_meeting_id = $1 "
                    "ORDER BY scheduled_at DESC LIMIT 1",
                    str(meeting_id),
                )
            if row is None:
                logger.info(f"[Zoom] meeting {meeting_id} not mapped to a session; skipping")
                return

            updated_session: Dict[str, Any] = dict(row)
            if event == "meeting.deleted":
                await conn.execute(
                    "UPDATE coaching_sessions SET status = 'cancelled', updated_at = NOW() "
                    "WHERE session_id = $1",
                    updated_session.get("session_id"),
                )
                _gcal_action = "delete"
            else:
                # meeting.updated — refresh time / title if provided
                if new_start:
                    try:
                        start_dt = dt.datetime.fromisoformat(new_start.replace("Z", "+00:00"))
                        end_dt = start_dt + dt.timedelta(minutes=int(new_duration or 60))
                        await conn.execute(
                            "UPDATE coaching_sessions SET scheduled_at = $1, ended_at = $2, "
                            "scheduled_start = $1, scheduled_end = $2, updated_at = NOW() "
                            "WHERE session_id = $3",
                            start_dt, end_dt, updated_session.get("session_id"),
                        )
                        updated_session["scheduled_start"] = start_dt.isoformat()
                        updated_session["scheduled_end"] = end_dt.isoformat()
                    except Exception as e:
                        logger.warning(f"[Zoom] failed to parse start_time {new_start}: {e}")
                if new_topic:
                    await conn.execute(
                        "UPDATE coaching_sessions SET title = $1 WHERE session_id = $2",
                        new_topic[:200], updated_session.get("session_id"),
                    )
                    updated_session["title"] = new_topic
                _gcal_action = "update"

        # Best-effort Google Calendar mirror (skip if helper unavailable).
        try:
            from app.services.google_calendar_session_sync import sync_session_for_participants
            asyncio.create_task(
                sync_session_for_participants(db_pool, updated_session, action=_gcal_action)
            )
        except Exception:
            pass
    except Exception as e:
        logger.error(f"[Zoom] meeting lifecycle handler failed: {e}")
        _append_json_list(ZOOM_WEBHOOK_ERRORS_FILE, {
            "received_at": dt.datetime.utcnow().isoformat(),
            "error": "meeting_lifecycle_failed",
            "event": event,
            "meeting_id": meeting_id,
            "detail": str(e),
        })


def _pick_transcript_from_recording_files(recording_files: List[Any]) -> tuple[Optional[str], Optional[str]]:
    """Return (download_url, extension) for first completed transcript/CC file."""
    for rf in recording_files or []:
        if not isinstance(rf, dict):
            continue
        file_type = (rf.get("file_type") or "").upper()
        file_ext = (rf.get("file_extension") or "").upper()
        if file_type in ("TRANSCRIPT", "CC") or file_ext in ("VTT", "TXT"):
            if (rf.get("status") or "").lower() == "completed":
                url = (rf.get("download_url") or "").strip()
                if url:
                    ext = (rf.get("file_extension") or "vtt").strip().lower() or "vtt"
                    return url, ext
    return None, None


async def _try_whisper_audio_fallback(
    recording_files: List[Any],
    zc: "ZoomClient",
    meeting_id: str,
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    If no transcript file is available, attempt to synthesize one from the
    Zoom audio (M4A) via Whisper. Returns (vtt_bytes, "vtt") on success or
    (None, None) on failure / when fallback is disabled / unconfigured.
    """
    try:
        from app.services.zoom_audio_fallback import (
            is_fallback_enabled, pick_audio_file, transcribe_zoom_audio_to_vtt,
        )
    except Exception as e:
        logger.warning("[Zoom] whisper fallback module import failed: %s", e)
        return None, None
    if not is_fallback_enabled():
        return None, None
    audio_url, _audio_ext = pick_audio_file(recording_files)
    if not audio_url:
        return None, None
    try:
        audio_bytes = await zc.download_recording_file(download_url=audio_url)
    except Exception as e:
        logger.warning("[Zoom] whisper fallback: audio download failed for %s: %s", meeting_id, e)
        return None, None
    vtt_bytes = await transcribe_zoom_audio_to_vtt(audio_bytes)
    if not vtt_bytes:
        logger.warning("[Zoom] whisper fallback produced no transcript for %s", meeting_id)
        return None, None
    logger.info("[Zoom] whisper fallback synthesized %d-byte VTT for meeting %s", len(vtt_bytes), meeting_id)
    return vtt_bytes, "vtt"


def _recording_has_completed_files(recording_files: List[Any]) -> bool:
    for rf in recording_files or []:
        if isinstance(rf, dict) and (rf.get("status") or "").lower() == "completed":
            return True
    return False


def _get_app_db_pool():
    try:
        from app.main import app
        return getattr(app.state, "db_pool", None) if app else None
    except Exception:
        return None


async def _patch_coaching_session_data(conn, session_id: str, patch: Dict[str, Any]) -> None:
    if not session_id or not patch:
        return
    await conn.execute(
        """
        UPDATE coaching_sessions
        SET session_data = COALESCE(session_data, '{}'::jsonb) || $2::jsonb,
            updated_at = NOW()
        WHERE session_id = $1
        """,
        session_id,
        json.dumps(patch, default=str),
    )


async def _fetch_coaching_session_by_zoom(conn, meeting_id: str) -> Optional[Dict[str, Any]]:
    if not meeting_id:
        return None
    row = await conn.fetchrow(
        """
        SELECT session_id, coach_id, client_id, client_name, zoom_meeting_id, session_data
        FROM coaching_sessions
        WHERE zoom_meeting_id = $1
        ORDER BY scheduled_start DESC NULLS LAST
        LIMIT 1
        """,
        str(meeting_id),
    )
    return dict(row) if row else None


def _session_data_dict(pg_row: Dict[str, Any]) -> Dict[str, Any]:
    sd = pg_row.get("session_data") or {}
    if isinstance(sd, str):
        try:
            return json.loads(sd) if sd else {}
        except Exception:
            return {}
    return sd if isinstance(sd, dict) else {}


async def _archive_transcript_and_classroom_for_pg_session(
    db_pool,
    pg_row: Dict[str, Any],
    vtt_bytes: bytes,
    ext: str,
    meeting_id: str,
    transcript_source: str = "zoom_native",
) -> None:
    """
    Upload transcript to blob/local storage, merge session_data on coaching_sessions,
    run ClassroomAnalyzer (metrics + queued AI) for Little Nate learning.
    """
    session_id = (pg_row.get("session_id") or "").strip()
    if not session_id or not vtt_bytes:
        return
    sd0 = _session_data_dict(pg_row)
    if (sd0.get("transcript_location") or "").strip():
        logger.info("[Zoom] PG session %s already has transcript; skipping re-archive", session_id)
        return

    from app.services.blob_storage import upload_bytes

    rel_path = f"sessions/{session_id}/{meeting_id}/transcript.{ext}"
    storage_kind, location = upload_bytes(
        rel_path=rel_path,
        content=vtt_bytes,
        content_type="text/vtt" if ext == "vtt" else "text/plain",
    )
    now_iso = dt.datetime.utcnow().isoformat()
    patch = {
        "transcript_archived_at": now_iso,
        "transcript_storage": storage_kind,
        "transcript_location": location,
        "transcript_file_extension": ext,
        "transcript_source": transcript_source,
        "recording_ready": False,
        "transcript_pending": False,
        "classroom_analysis_available": False,
        "zoom_auto_archived_at": now_iso,
    }
    async with db_pool.acquire() as conn:
        await _patch_coaching_session_data(conn, session_id, patch)

    vtt_text = vtt_bytes.decode("utf-8", errors="ignore")
    coach_id = str(pg_row.get("coach_id") or "")
    client_id = str(pg_row.get("client_id") or "")
    client_name = str(pg_row.get("client_name") or "")
    family_id = ""

    zoom_ai_summary: Optional[Dict[str, Any]] = None
    zoom_ai_summary_text: str = ""
    try:
        _zc = ZoomClient.from_env()
        zoom_ai_summary = await _zc.get_meeting_summary(meeting_id=str(meeting_id))
        if zoom_ai_summary:
            _det = ((zoom_ai_summary.get("summary") or {}).get("summary_details")) if isinstance(zoom_ai_summary.get("summary"), dict) else None
            zoom_ai_summary_text = (
                _det
                or zoom_ai_summary.get("summary_details")
                or zoom_ai_summary.get("summary_overview")
                or ""
            )
            zoom_ai_summary_text = str(zoom_ai_summary_text or "").strip()
            try:
                async with db_pool.acquire() as conn:
                    await _patch_coaching_session_data(
                        conn,
                        session_id,
                        {
                            "zoom_ai_summary": zoom_ai_summary,
                            "zoom_ai_summary_text": zoom_ai_summary_text or None,
                            "zoom_ai_summary_fetched_at": dt.datetime.utcnow().isoformat(),
                        },
                    )
                logger.info(
                    "[Zoom] AI summary archived for session %s (chars=%d)",
                    session_id,
                    len(zoom_ai_summary_text),
                )
            except Exception as _se:
                logger.warning("[Zoom] AI summary patch for %s: %s", session_id, _se)
        else:
            logger.info("[Zoom] No AI Companion summary available for meeting %s", meeting_id)
    except Exception as _zse:
        logger.warning("[Zoom] AI summary fetch for meeting %s: %s", meeting_id, _zse)

    try:
        from app.routers.sessions import CLASSROOM_AVAILABLE, _classroom_analyzer
        from app.services.pg_data_helpers import find_user_pg
    except Exception as _imp_err:
        logger.warning("[Zoom] Classroom/PG import for auto-archive: %s", _imp_err)
        return

    if not CLASSROOM_AVAILABLE or not _classroom_analyzer:
        logger.info("[Zoom] Classroom analyzer unavailable; transcript archived only for %s", session_id)
        async with db_pool.acquire() as conn:
            await _patch_coaching_session_data(conn, session_id, {"classroom_analysis_available": False})
        return

    coach_name = "Coach"
    if db_pool and coach_id:
        try:
            cp = await find_user_pg(db_pool, hardware_id=coach_id)
            if cp:
                cpd = cp.get("profile_data") or {}
                if isinstance(cpd, str):
                    try:
                        cpd = json.loads(cpd) if cpd else {}
                    except Exception:
                        cpd = {}
                coach_name = cpd.get("name") or "Coach"
            if not family_id and client_id:
                clp = await find_user_pg(db_pool, hardware_id=client_id)
                if clp:
                    cld = clp.get("profile_data") or {}
                    if isinstance(cld, str):
                        try:
                            cld = json.loads(cld) if cld else {}
                        except Exception:
                            cld = {}
                    family_id = str(cld.get("family_id") or "")
                    if not client_name:
                        client_name = str(cld.get("name") or "")
        except Exception as _lu_err:
            logger.warning("[Zoom] find_user_pg during auto-archive: %s", _lu_err)

    if zoom_ai_summary_text:
        analyzer_input = (
            "[ZOOM AI SUMMARY]\n"
            f"{zoom_ai_summary_text}\n\n"
            "[TRANSCRIPT]\n"
            f"{vtt_text}"
        )
    else:
        analyzer_input = vtt_text

    learning_ok = False
    try:
        _classroom_analyzer.analyze_transcript(
            session_id=session_id,
            coach_id=coach_id,
            client_id=client_id,
            coach_name=coach_name,
            vtt_content=analyzer_input,
            focus_area="general therapeutic skills",
            due_date=None,
            family_id=family_id or None,
            client_name=client_name or None,
        )
        _classroom_analyzer.queue_ai_analysis(
            session_id=session_id,
            coach_id=coach_id,
            coach_name=coach_name,
            vtt_content=analyzer_input,
            focus_area="general therapeutic skills",
        )
        learning_ok = True
    except Exception as _ca_err:
        logger.warning("[Zoom] Classroom analyze/queue for %s: %s", session_id, _ca_err)

    if zoom_ai_summary_text and (vtt_text or "").strip() and client_id:
        async def _cross_ref_crystal():
            try:
                from app.websocket.crystal_recall_bridge import (
                    crystallize_from_conversation,
                )

                nate_summary = ""
                try:
                    _ana = _classroom_analyzer.get_session_analysis(session_id)
                    if isinstance(_ana, dict):
                        for _k in (
                            "summary",
                            "transcript_summary",
                            "session_summary",
                            "phd_summary",
                        ):
                            _v = _ana.get(_k)
                            if isinstance(_v, str) and _v.strip():
                                nate_summary = _v.strip()
                                break
                        if not nate_summary:
                            _nested = _ana.get("analysis") if isinstance(_ana.get("analysis"), dict) else None
                            if _nested:
                                for _k in ("summary", "transcript_summary"):
                                    _v = _nested.get(_k)
                                    if isinstance(_v, str) and _v.strip():
                                        nate_summary = _v.strip()
                                        break
                except Exception:
                    nate_summary = ""

                if not nate_summary:
                    nate_summary = (vtt_text or "").strip()[:500]

                cross_ref = (
                    f"Zoom AI observed: {zoom_ai_summary_text[:500]}\n"
                    f"Little Nate observed: {nate_summary[:500]}"
                )
                await crystallize_from_conversation(
                    db_pool,
                    client_id,
                    cross_ref,
                    "Cross-modal session intelligence",
                    user_name=client_name or "",
                    domain="clinical",
                    min_score=0,
                    origin_surface="zoom_cross_reference",
                )
                logger.info(
                    "[Zoom] Cross-reference crystal queued for session %s", session_id
                )
            except Exception as _xrr:
                logger.debug("[Zoom] Cross-reference crystal failed: %s", _xrr)

        try:
            asyncio.create_task(_cross_ref_crystal())
        except Exception:
            pass

    async with db_pool.acquire() as conn:
        await _patch_coaching_session_data(
            conn,
            session_id,
            {
                "nate_read_transcript_at": now_iso,
                "nate_learning_queued_at": now_iso if learning_ok else "",
                "classroom_analysis_available": learning_ok,
            },
        )
    logger.info("[Zoom] Auto-archived + classroom pipeline for session %s", session_id)

    if db_pool and coach_id and (vtt_text or "").strip():
        async def _wisdom_followup():
            try:
                uid = None
                async with db_pool.acquire() as c:
                    uid = await c.fetchval(
                        "SELECT id::text FROM users WHERE hardware_id = $1 LIMIT 1",
                        coach_id,
                    )
                if not uid:
                    return
                from app.services.wisdom_lifecycle_manager import WisdomLifecycleManager

                mgr = WisdomLifecycleManager(db_pool, None)
                await mgr.extract_wisdom(
                    source="classroom_zoom",
                    content=(vtt_text or "")[:20000],
                    user_id=uid,
                    domain="coaching",
                    confidence=0.45,
                )
            except Exception as _w_err:
                logger.debug("[Zoom] classroom wisdom follow-up: %s", _w_err)

        try:
            asyncio.create_task(_wisdom_followup())
        except Exception:
            pass


async def poll_pending_zoom_classroom_transcripts(db_pool) -> int:
    """
    Drip-scheduler job: coaching_sessions with transcript_pending poll Zoom until
    transcript files appear, then archive + classroom (same as webhook path).
    """
    if not db_pool or not getattr(settings, "ENABLE_ZOOM", False):
        return 0
    archived = 0
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, coach_id, client_id, client_name, zoom_meeting_id, session_data
                FROM coaching_sessions
                WHERE COALESCE(zoom_meeting_id, '') <> ''
                  AND (session_data->>'transcript_pending') = 'true'
                ORDER BY updated_at DESC NULLS LAST
                LIMIT 25
                """
            )
        zc = ZoomClient.from_env()
        for row in rows:
            r = dict(row)
            mid = str(r.get("zoom_meeting_id") or "").strip()
            if not mid:
                continue
            try:
                rec = await zc.get_meeting_recordings(meeting_id=mid)
                files = rec.get("recording_files") or []
                t_url, t_ext = _pick_transcript_from_recording_files(files)
                if t_url:
                    vtt_bytes = await zc.download_recording_file(download_url=t_url)
                    transcript_source = "zoom_native"
                else:
                    vtt_bytes, t_ext = await _try_whisper_audio_fallback(files, zc, mid)
                    if not vtt_bytes:
                        continue
                    transcript_source = "whisper_fallback"
                await _archive_transcript_and_classroom_for_pg_session(
                    db_pool, r, vtt_bytes, t_ext or "vtt", mid,
                    transcript_source=transcript_source,
                )
                archived += 1
            except Exception as pe:
                logger.warning("[Zoom] Pending transcript poll failed for %s: %s", mid, pe)
    except Exception as e:
        logger.warning("[Zoom] poll_pending_zoom_classroom_transcripts: %s", e)
    return archived


# =============================================================================
# BACKGROUND: Process recording event → download transcript → ingest
# =============================================================================
async def _process_recording_event(
    payload: Dict[str, Any],
    meeting_id: str,
    mapping: Dict[str, Any],
    session_source: str,
) -> None:
    """
    Background task triggered by recording.completed / phone.recording_completed.
    Downloads the transcript VTT, parses it, matches to a client, and feeds
    through the MetricsEngine pipeline. Also auto-archives to coaching_sessions
    and runs Classroom when a PG session matches zoom_meeting_id.
    """
    db_pool = _get_app_db_pool()
    pg_row: Optional[Dict[str, Any]] = None
    try:
        if db_pool and meeting_id:
            async with db_pool.acquire() as conn:
                pg_row = await _fetch_coaching_session_by_zoom(conn, meeting_id)
    except Exception as e:
        logger.warning("[Zoom] PG lookup for meeting %s: %s", meeting_id, e)

    try:
        from app.services.zoom_ingestion import ZoomIngestionService
        ingestion = ZoomIngestionService()

        obj = (payload.get("payload") or {}).get("object") or {}
        recording_files = obj.get("recording_files") or []
        topic = obj.get("topic") or ""
        start_time = obj.get("start_time") or ""
        duration = obj.get("duration") or 0

        participant_emails = []
        for p in (obj.get("participants") or obj.get("registrants") or []):
            email = p.get("email") or p.get("user_email") or ""
            if email:
                participant_emails.append(email)
        host_email = obj.get("host_email") or ""
        if host_email:
            participant_emails.append(host_email)

        transcript_url, transcript_ext = _pick_transcript_from_recording_files(recording_files)

        if not transcript_url:
            logger.warning(f"[Zoom] No completed transcript file yet for meeting {meeting_id}")
            if pg_row and db_pool and _recording_has_completed_files(recording_files):
                try:
                    async with db_pool.acquire() as conn:
                        await _patch_coaching_session_data(
                            conn,
                            pg_row["session_id"],
                            {
                                "recording_ready": True,
                                "transcript_pending": True,
                                "zoom_recording_webhook_at": dt.datetime.utcnow().isoformat(),
                            },
                        )
                    logger.info("[Zoom] Marked session %s transcript_pending", pg_row.get("session_id"))
                except Exception as pe:
                    logger.warning("[Zoom] Failed to set transcript_pending: %s", pe)
            _append_json_list(ZOOM_INGESTED_FILE, {
                "timestamp": dt.datetime.utcnow().isoformat(),
                "meeting_id": meeting_id,
                "status": "no_transcript_yet",
                "topic": topic,
                "session_source": session_source,
            })
            return

        client = ZoomClient.from_env()
        vtt_bytes = await client.download_recording_file(download_url=transcript_url)
        vtt_text = vtt_bytes.decode("utf-8", errors="ignore")

        turns = ingestion.parse_transcript(vtt_text)
        if not turns:
            logger.warning(f"[Zoom] Transcript parsed but no turns found for meeting {meeting_id}")
            _append_json_list(ZOOM_INGESTED_FILE, {
                "timestamp": dt.datetime.utcnow().isoformat(),
                "meeting_id": meeting_id,
                "status": "empty_transcript",
                "topic": topic,
                "session_source": session_source,
            })
            return

        client_id = (mapping.get("client_id") or "").strip()
        if not client_id:
            client_id = await ingestion.match_client(
                meeting_topic=topic,
                participant_emails=participant_emails,
            )
        if not client_id and pg_row:
            client_id = str(pg_row.get("client_id") or "").strip()

        if not client_id:
            logger.warning(f"[Zoom] Could not match meeting {meeting_id} to a client")
            _append_json_list(ZOOM_INGESTED_FILE, {
                "timestamp": dt.datetime.utcnow().isoformat(),
                "meeting_id": meeting_id,
                "status": "no_client_match",
                "topic": topic,
                "participant_emails": participant_emails,
                "session_source": session_source,
                "turns_count": len(turns),
            })
            if pg_row and db_pool:
                try:
                    ext = transcript_ext or "vtt"
                    await _archive_transcript_and_classroom_for_pg_session(
                        db_pool, pg_row, vtt_bytes, ext, str(meeting_id)
                    )
                except Exception as ae:
                    logger.warning("[Zoom] Archive without metrics client failed: %s", ae)
            return

        result = await ingestion.ingest_session(
            client_id=client_id,
            transcript_turns=turns,
            session_source=session_source,
            meeting_id=meeting_id,
            topic=topic,
            start_time=start_time,
            duration=duration,
        )

        _append_json_list(ZOOM_INGESTED_FILE, {
            "timestamp": dt.datetime.utcnow().isoformat(),
            "meeting_id": meeting_id,
            "client_id": client_id,
            "status": "ingested",
            "topic": topic,
            "session_source": session_source,
            "turns_count": len(turns),
            "client_turns_processed": result.get("client_turns_processed", 0),
            "start_time": start_time,
            "duration": duration,
        })
        logger.info(f"[Zoom] Successfully ingested meeting {meeting_id} for client {client_id}")

        if pg_row and db_pool:
            try:
                await _archive_transcript_and_classroom_for_pg_session(
                    db_pool,
                    pg_row,
                    vtt_bytes,
                    transcript_ext or "vtt",
                    str(meeting_id),
                )
            except Exception as ae:
                logger.error("[Zoom] Auto classroom archive after ingest failed: %s", ae, exc_info=True)

    except Exception as e:
        logger.error(f"[Zoom] Ingestion failed for meeting {meeting_id}: {e}", exc_info=True)
        _append_json_list(ZOOM_INGESTED_FILE, {
            "timestamp": dt.datetime.utcnow().isoformat(),
            "meeting_id": meeting_id,
            "status": "ingestion_error",
            "error": str(e),
            "session_source": session_source,
        })


# =============================================================================
# ADMIN: List ingested Zoom sessions
# =============================================================================
@router.get("/ingested-sessions", dependencies=[Depends(require_admin)])
async def get_ingested_sessions():
    """Return list of Zoom sessions that have been ingested."""
    if not settings.ENABLE_ZOOM:
        raise HTTPException(status_code=400, detail="Zoom disabled")
    sessions = _load_json(ZOOM_INGESTED_FILE, []) or []
    return {"sessions": sessions, "total": len(sessions)}

