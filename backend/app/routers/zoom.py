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
from typing import Any, Dict, List, Optional

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

    return {"status": "ok"}


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
    through the MetricsEngine pipeline.
    """
    try:
        from app.services.zoom_ingestion import ZoomIngestionService
        ingestion = ZoomIngestionService()

        obj = (payload.get("payload") or {}).get("object") or {}
        recording_files = obj.get("recording_files") or []
        topic = obj.get("topic") or ""
        participants = obj.get("participant_audio_files") or []
        start_time = obj.get("start_time") or ""
        duration = obj.get("duration") or 0

        # Also extract participant emails from the meeting object
        participant_emails = []
        for p in (obj.get("participants") or obj.get("registrants") or []):
            email = p.get("email") or p.get("user_email") or ""
            if email:
                participant_emails.append(email)
        # Host email
        host_email = obj.get("host_email") or ""
        if host_email:
            participant_emails.append(host_email)

        # Find transcript file (VTT or TRANSCRIPT type)
        transcript_url = None
        for rf in recording_files:
            file_type = (rf.get("file_type") or "").upper()
            file_ext = (rf.get("file_extension") or "").upper()
            if file_type in ("TRANSCRIPT", "CC") or file_ext in ("VTT", "TXT"):
                if rf.get("status") == "completed":
                    transcript_url = rf.get("download_url")
                    break

        if not transcript_url:
            logger.warning(f"[Zoom] No transcript file found for meeting {meeting_id}")
            _append_json_list(ZOOM_INGESTED_FILE, {
                "timestamp": dt.datetime.utcnow().isoformat(),
                "meeting_id": meeting_id,
                "status": "no_transcript",
                "topic": topic,
                "session_source": session_source,
            })
            return

        # Download transcript
        client = ZoomClient.from_env()
        vtt_bytes = await client.download_recording_file(download_url=transcript_url)
        vtt_text = vtt_bytes.decode("utf-8", errors="ignore")

        # Parse transcript into conversation turns
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

        # Match to client using mapping (preferred) or participant emails
        client_id = mapping.get("client_id") or ""
        if not client_id:
            client_id = await ingestion.match_client(
                meeting_topic=topic,
                participant_emails=participant_emails,
            )

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
            return

        # Ingest through MetricsEngine
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

