"""
Zoom integration (Server-to-Server OAuth) for meeting automation.

Design goals:
- No Zoom email/password automation.
- Token cached in-memory; safe to restart.
- Strictly additive: if env vars missing, functions raise clear errors.
"""

from __future__ import annotations

import base64
import datetime as dt
import logging
import os
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

_ZOOM_MEETING_ID_RE = re.compile(
    r"zoom\.us/(?:j|s|wc|w)/(\d+)",
    re.IGNORECASE,
)


def zoom_start_differs(existing_start: str, requested_iso: str) -> bool:
    """True when Zoom's stored start is not the requested minute (UTC)."""
    def _norm(s: str) -> str:
        raw = (s or "").strip().replace("Z", "+00:00")
        if not raw:
            return ""
        try:
            parsed = dt.datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M")
        except Exception:
            return raw[:16]
    req = (requested_iso or "").strip()
    if not req:
        return False
    return _norm(existing_start) != _norm(req)


def parse_zoom_meeting_id(*urls: Any) -> str:
    """Extract numeric Zoom meeting id from join/host URLs."""
    for raw in urls:
        m = _ZOOM_MEETING_ID_RE.search(str(raw or ""))
        if m:
            return m.group(1)
    return ""


def host_start_url(meeting_id: str, zak: str) -> str:
    mid = (meeting_id or "").strip()
    token = (zak or "").strip()
    if not mid or not token:
        return ""
    return f"https://zoom.us/s/{mid}?zak={token}"


def double_encode_meeting_uuid(meeting_uuid: str) -> str:
    """Zoom requires double URL-encoding when UUID contains '/' or '//'."""
    raw = (meeting_uuid or "").strip()
    return urllib.parse.quote(urllib.parse.quote(raw, safe=""), safe="")


@dataclass
class ZoomToken:
    access_token: str
    expires_at: dt.datetime  # UTC

    def is_valid(self, skew_seconds: int = 30) -> bool:
        return dt.datetime.utcnow() + dt.timedelta(seconds=skew_seconds) < self.expires_at


class ZoomClient:
    """
    Zoom Server-to-Server OAuth client.

    Required env:
      - ZOOM_ACCOUNT_ID
      - ZOOM_CLIENT_ID
      - ZOOM_CLIENT_SECRET
    """

    def __init__(
        self,
        account_id: str,
        client_id: str,
        client_secret: str,
        host_user: str = "me",
        default_timezone: str = "America/Los_Angeles",
        default_waiting_room: bool = True,
        default_join_before_host: bool = False,
        default_auto_recording: str = "none",
    ) -> None:
        self.account_id = (account_id or "").strip()
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        self.host_user = (host_user or "me").strip() or "me"
        self.default_timezone = (default_timezone or "America/Los_Angeles").strip()
        self.default_waiting_room = bool(default_waiting_room)
        self.default_join_before_host = bool(default_join_before_host)
        self.default_auto_recording = (default_auto_recording or "none").strip()

        self._token: Optional[ZoomToken] = None

    @staticmethod
    def from_env() -> "ZoomClient":
        return ZoomClient(
            account_id=os.getenv("ZOOM_ACCOUNT_ID", ""),
            client_id=os.getenv("ZOOM_CLIENT_ID", ""),
            client_secret=os.getenv("ZOOM_CLIENT_SECRET", ""),
            host_user=os.getenv("ZOOM_HOST_USER", "me"),
            default_timezone=os.getenv("ZOOM_DEFAULT_TIMEZONE", "America/Los_Angeles"),
            default_waiting_room=os.getenv("ZOOM_DEFAULT_WAITING_ROOM", "true").lower() in ("1", "true", "yes"),
            default_join_before_host=os.getenv("ZOOM_DEFAULT_JOIN_BEFORE_HOST", "false").lower() in ("1", "true", "yes"),
            default_auto_recording=os.getenv("ZOOM_DEFAULT_AUTO_RECORDING", "none"),
        )

    def _ensure_configured(self) -> None:
        missing = []
        if not self.account_id:
            missing.append("ZOOM_ACCOUNT_ID")
        if not self.client_id:
            missing.append("ZOOM_CLIENT_ID")
        if not self.client_secret:
            missing.append("ZOOM_CLIENT_SECRET")
        if missing:
            raise RuntimeError(f"Zoom not configured. Missing: {', '.join(missing)}")

    async def _get_access_token(self) -> str:
        self._ensure_configured()
        if self._token and self._token.is_valid():
            return self._token.access_token

        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode("utf-8")).decode("ascii")
        url = "https://zoom.us/oauth/token"
        params = {
            "grant_type": "account_credentials",
            "account_id": self.account_id,
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, params=params, headers={"Authorization": f"Basic {auth}"})
            resp.raise_for_status()
            data = resp.json()

        access_token = data.get("access_token") or ""
        expires_in = int(data.get("expires_in") or 0)
        if not access_token or expires_in <= 0:
            raise RuntimeError("Failed to obtain Zoom access token.")

        self._token = ZoomToken(
            access_token=access_token,
            expires_at=dt.datetime.utcnow() + dt.timedelta(seconds=expires_in),
        )
        return access_token

    async def create_meeting(
        self,
        *,
        topic: str,
        start_time_iso: str,
        duration_minutes: int,
        agenda: str = "",
        meeting_type: int = 2,  # scheduled
        settings: Optional[Dict[str, Any]] = None,
        host_user: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a Zoom meeting. Returns Zoom API response including join_url and id.
        """
        token = await self._get_access_token()
        user = (host_user or self.host_user or "me").strip() or "me"

        url = f"https://api.zoom.us/v2/users/{user}/meetings"
        payload: Dict[str, Any] = {
            "topic": topic,
            "type": meeting_type,
            "start_time": start_time_iso,
            "duration": int(duration_minutes),
            "timezone": self.default_timezone,
            "agenda": agenda,
            "settings": {
                "waiting_room": self.default_waiting_room,
                "join_before_host": self.default_join_before_host,
                "auto_recording": self.default_auto_recording,
            },
        }
        if settings:
            # shallow merge
            payload["settings"].update(settings)

        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            return resp.json()

    async def update_meeting(
        self,
        *,
        meeting_id: str,
        start_time_iso: str = "",
        duration_minutes: Optional[int] = None,
        topic: Optional[str] = None,
        host_user: Optional[str] = None,
    ) -> Dict[str, Any]:
        """PATCH start_time / duration on an existing scheduled meeting."""
        token = await self._get_access_token()
        mid = (meeting_id or "").strip()
        if not mid:
            raise ValueError("Missing meeting_id")
        payload: Dict[str, Any] = {}
        if start_time_iso:
            payload["start_time"] = start_time_iso
        if duration_minutes is not None:
            payload["duration"] = int(duration_minutes)
        if topic:
            payload["topic"] = topic
        if not payload:
            return {}
        url = f"https://api.zoom.us/v2/meetings/{mid}"
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.patch(url, json=payload, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 404:
                return {"code": 3001, "deleted": True}
            try:
                data = resp.json() if resp.content else {}
            except Exception:
                data = {}
            if isinstance(data, dict) and data.get("code") == 3001:
                return {"code": 3001, "deleted": True}
            resp.raise_for_status()
            return data if isinstance(data, dict) else {}

    async def delete_meeting(self, *, meeting_id: str, host_user: Optional[str] = None) -> None:
        """
        Delete a Zoom meeting by meeting_id.

        Notes:
        - This deletes the meeting object (not recordings).
        - Requires meeting write scopes on the Zoom app.
        """
        token = await self._get_access_token()
        mid = (meeting_id or "").strip()
        if not mid:
            raise ValueError("Missing meeting_id")
        url = f"https://api.zoom.us/v2/meetings/{mid}"
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.delete(url, headers={"Authorization": f"Bearer {token}"})
            # Zoom returns 204 No Content on success.
            if resp.status_code not in (200, 204):
                resp.raise_for_status()

    async def get_meeting_recordings(self, *, meeting_id: str) -> Dict[str, Any]:
        """
        Get cloud recording metadata for a meeting.
        Requires cloud_recording:read scope.
        """
        token = await self._get_access_token()
        mid = (meeting_id or "").strip()
        if not mid:
            raise ValueError("Missing meeting_id")
        url = f"https://api.zoom.us/v2/meetings/{mid}/recordings"
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            return resp.json()

    async def delete_meeting_recordings(self, *, meeting_id: str) -> None:
        """
        Delete cloud recordings for a meeting to reduce storage.
        Requires cloud_recording:write / delete scopes.
        """
        token = await self._get_access_token()
        mid = (meeting_id or "").strip()
        if not mid:
            raise ValueError("Missing meeting_id")
        url = f"https://api.zoom.us/v2/meetings/{mid}/recordings"
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.delete(url, params={"action": "delete"}, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code not in (200, 204):
                resp.raise_for_status()

    async def get_meeting_summary(
        self,
        *,
        meeting_id: str,
        meeting_uuid: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch Zoom AI Companion meeting summary.
        Requires meeting:read:summary:admin scope and AI Companion enabled.

        Use meeting_uuid (from webhooks) when available — numeric meeting_id alone
        returns 400 Invalid meeting id from Zoom.

        Returns the parsed JSON body on 200, None on 404 / not generated yet,
        and None (with a debug log) on any other non-200. Never raises.
        """
        log = logging.getLogger("zoom_client")
        uuid = (meeting_uuid or "").strip()
        if uuid:
            payload = await self._get_meeting_summary_by_uuid(uuid)
            if payload:
                return payload
        mid = (meeting_id or "").strip()
        if not mid:
            return None
        try:
            token = await self._get_access_token()
        except Exception as e:
            log.debug("get_meeting_summary token error for %s: %s", mid, e)
            return None
        url = f"https://api.zoom.us/v2/meetings/{mid}/meeting_summary"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 200:
                try:
                    return resp.json()
                except Exception:
                    return None
            if resp.status_code in (404, 400):
                return None
            log.debug(
                "Zoom meeting_summary %s for %s: %s",
                resp.status_code,
                mid,
                (resp.text or "")[:200],
            )
            return None
        except Exception as e:
            log.debug("Zoom meeting_summary fetch failed for %s: %s", mid, e)
            return None

    async def _get_meeting_summary_by_uuid(self, meeting_uuid: str) -> Optional[Dict[str, Any]]:
        uuid = (meeting_uuid or "").strip()
        if not uuid:
            return None
        log = logging.getLogger("zoom_client")
        try:
            token = await self._get_access_token()
        except Exception as e:
            log.debug("get_meeting_summary_by_uuid token error: %s", e)
            return None
        enc = double_encode_meeting_uuid(uuid)
        url = f"https://api.zoom.us/v2/meetings/{enc}/meeting_summary"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 200:
                try:
                    return resp.json()
                except Exception:
                    return None
            if resp.status_code == 404:
                return None
            log.debug(
                "Zoom meeting_summary uuid %s → %s: %s",
                uuid[:16],
                resp.status_code,
                (resp.text or "")[:200],
            )
            return None
        except Exception as e:
            log.debug("Zoom meeting_summary uuid fetch failed: %s", e)
            return None

    async def download_recording_file(self, *, download_url: str) -> bytes:
        """
        Download a recording artifact (e.g., transcript VTT) using the Zoom access token.
        """
        token = await self._get_access_token()
        url = (download_url or "").strip()
        if not url:
            raise ValueError("Missing download_url")

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            # Preferred: Authorization header
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code in (401, 403):
                # Fallback: some Zoom download URLs accept access_token query
                join = "&" if ("?" in url) else "?"
                resp = await client.get(f"{url}{join}access_token={token}")
            resp.raise_for_status()
            return resp.content
    
    async def check_recording_availability(self, *, meeting_id: str) -> Dict[str, Any]:
        """
        Check if a recording is available for a meeting and its status.
        
        Returns:
            {
                "available": bool,
                "status": "recording" | "processing" | "completed" | "unavailable",
                "recording_files": [...],
                "recording_start": str (ISO),
                "recording_end": str (ISO),
                "days_remaining": int (days until 30-day deletion)
            }
        """
        token = await self._get_access_token()
        mid = (meeting_id or "").strip()
        if not mid:
            return {"available": False, "status": "unavailable"}
        
        try:
            url = f"https://api.zoom.us/v2/meetings/{mid}/recordings"
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                
                if resp.status_code == 404:
                    return {"available": False, "status": "unavailable"}
                
                resp.raise_for_status()
                data = resp.json()
                
                recording_files = data.get("recording_files") or []
                if not recording_files:
                    return {"available": False, "status": "unavailable"}
                
                # Calculate days remaining until 30-day deletion
                recording_start = data.get("recording_start") or data.get("start_time")
                days_remaining = 30
                
                if recording_start:
                    try:
                        from datetime import datetime
                        start_dt = datetime.fromisoformat(recording_start.replace("Z", "+00:00"))
                        now = datetime.now(start_dt.tzinfo or dt.timezone.utc)
                        days_elapsed = (now - start_dt).days
                        days_remaining = max(0, 30 - days_elapsed)
                    except Exception:
                        pass
                
                # Check status of recordings
                statuses = {f.get("status") for f in recording_files if f.get("status")}
                
                if "recording" in statuses:
                    status = "recording"
                elif "processing" in statuses:
                    status = "processing"
                elif "completed" in statuses or not statuses:
                    status = "completed"
                else:
                    status = "completed"
                
                return {
                    "available": True,
                    "status": status,
                    "recording_files": recording_files,
                    "recording_start": data.get("recording_start"),
                    "recording_end": data.get("recording_end"),
                    "days_remaining": days_remaining,
                    "total_size": data.get("total_size", 0),
                    "share_url": data.get("share_url", ""),
                }
                
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"available": False, "status": "unavailable"}
            raise
        except Exception as e:
            print(f"[Zoom] Recording check failed: {e}")
            return {"available": False, "status": "unavailable", "error": str(e)}
    
    async def get_live_transcript(self, *, meeting_id: str) -> Optional[str]:
        """
        Get live transcript from a recording in progress or recently completed.
        
        Returns the VTT content or None if not available.
        """
        try:
            availability = await self.check_recording_availability(meeting_id=meeting_id)
            
            if not availability.get("available"):
                return None
            
            recording_files = availability.get("recording_files") or []
            
            # Find transcript file (VTT or TXT)
            transcript_file = None
            for f in recording_files:
                file_type = (f.get("file_type") or "").upper()
                file_ext = (f.get("file_extension") or "").upper()
                
                if file_type in ("TRANSCRIPT", "CC") or file_ext in ("VTT", "TXT"):
                    if f.get("status") == "completed":
                        transcript_file = f
                        break
            
            if not transcript_file:
                return None
            
            download_url = transcript_file.get("download_url")
            if not download_url:
                return None
            
            content = await self.download_recording_file(download_url=download_url)
            return content.decode("utf-8", errors="ignore")
            
        except Exception as e:
            print(f"[Zoom] Live transcript fetch failed: {e}")
            return None
    
    async def get_meeting_status(self, *, meeting_id: str) -> Dict[str, Any]:
        """
        Get the current status of a meeting (live/ended).
        
        Returns:
            {
                "status": "waiting" | "started" | "ended",
                "start_time": str (ISO),
                "end_time": str (ISO) if ended,
                "duration": int (minutes)
            }
        """
        token = await self._get_access_token()
        mid = (meeting_id or "").strip()
        if not mid:
            return {"status": "unknown"}
        
        try:
            url = f"https://api.zoom.us/v2/meetings/{mid}"
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                
                if resp.status_code == 404:
                    return {"status": "ended"}
                
                resp.raise_for_status()
                data = resp.json()
                
                # Check meeting status
                status = data.get("status", "scheduled")
                
                if status == "waiting":
                    return {
                        "status": "waiting",
                        "start_time": data.get("start_time"),
                    }
                elif status == "started":
                    return {
                        "status": "started",
                        "start_time": data.get("start_time"),
                    }
                else:
                    return {
                        "status": "ended",
                        "start_time": data.get("start_time"),
                        "duration": data.get("duration"),
                    }
                    
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"status": "ended"}
            raise
        except Exception as e:
            print(f"[Zoom] Meeting status check failed: {e}")
            return {"status": "unknown", "error": str(e)}

    async def get_meeting(self, *, meeting_id: str) -> Optional[Dict[str, Any]]:
        """Return Zoom meeting JSON, or None when the meeting does not exist (404 / code 3001)."""
        token = await self._get_access_token()
        mid = (meeting_id or "").strip()
        if not mid:
            return None
        url = f"https://api.zoom.us/v2/meetings/{mid}"
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 404:
            return None
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {}
        if isinstance(data, dict) and data.get("code") == 3001:
            return None
        resp.raise_for_status()
        return data if isinstance(data, dict) else None

    async def get_zak_token(self, host_user: Optional[str] = None) -> str:
        """Fresh host ZAK. Stored start_url zak tokens expire in hours."""
        token = await self._get_access_token()
        user = (host_user or self.host_user or "me").strip() or "me"
        url = f"https://api.zoom.us/v2/users/{user}/token"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                url,
                params={"type": "zak"},
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json() or {}
        return str(data.get("token") or "").strip()

    async def ensure_scheduled_meeting(
        self,
        *,
        meeting_id: str = "",
        topic: str,
        start_time_iso: str,
        duration_minutes: int,
        agenda: str = "",
        settings: Optional[Dict[str, Any]] = None,
        host_user: Optional[str] = None,
        allow_time_patch: bool = True,
    ) -> Dict[str, Any]:
        """
        Keep a live scheduled meeting + fresh host start_url.

        Zoom 404 / code 3001 means the stored meeting was deleted. Recreate it.
        If the meeting still exists, mint a new ZAK so Open Zoom is host, not guest.
        PATCH start_time when the stored start differs and allow_time_patch is True
        (caller must skip PATCH when this meeting_id is shared with another session).
        """
        mid = (meeting_id or "").strip()
        existing = None
        if mid:
            existing = await self.get_meeting(meeting_id=mid)
        status = str((existing or {}).get("status") or "").lower()
        if existing and status not in ("finished", "ended"):
            live_id = str(existing.get("id") or mid)
            if allow_time_patch and zoom_start_differs(
                str(existing.get("start_time") or ""), start_time_iso
            ):
                try:
                    patched = await self.update_meeting(
                        meeting_id=live_id,
                        start_time_iso=start_time_iso,
                        duration_minutes=int(duration_minutes or 50),
                        topic=topic,
                        host_user=host_user,
                    )
                    if patched.get("deleted") or patched.get("code") == 3001:
                        existing = None
                    else:
                        existing = {**existing, **{k: v for k, v in patched.items() if v}}
                        status = str(existing.get("status") or status).lower()
                except Exception as e:
                    logging.getLogger("zoom_client").warning(
                        "ensure_scheduled_meeting PATCH start_time failed for %s: %s", live_id, e
                    )
            if existing and status not in ("finished", "ended"):
                join_url = str(existing.get("join_url") or "")
                start_url = str(existing.get("start_url") or "")
                try:
                    zak = await self.get_zak_token(host_user=host_user)
                    refreshed = host_start_url(live_id, zak)
                    if refreshed:
                        start_url = refreshed
                except Exception as e:
                    logging.getLogger("zoom_client").warning(
                        "ensure_scheduled_meeting ZAK refresh failed for %s: %s", live_id, e
                    )
                return {
                    "id": live_id,
                    "join_url": join_url,
                    "start_url": start_url,
                    "recreated": False,
                    "status": status or "waiting",
                }

        created = await self.create_meeting(
            topic=topic,
            start_time_iso=start_time_iso,
            duration_minutes=int(duration_minutes or 50),
            agenda=agenda,
            settings=settings,
            host_user=host_user,
        )
        return {
            "id": str(created.get("id") or ""),
            "join_url": str(created.get("join_url") or ""),
            "start_url": str(created.get("start_url") or ""),
            "recreated": True,
            "status": str(created.get("status") or "waiting"),
        }

