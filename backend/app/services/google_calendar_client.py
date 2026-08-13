"""Google Calendar API client.

Pure data-plane operations:
  - exchange_code(code, redirect_uri) -> token bundle
  - refresh_access_token(refresh_token) -> new access_token + expiry
  - list_calendars(access_token) -> [{id,summary,primary,...}]
  - create_event(access_token, calendar_id, payload) -> event dict
  - update_event(access_token, calendar_id, event_id, payload) -> event dict
  - delete_event(access_token, calendar_id, event_id) -> bool
  - list_events_incremental(access_token, calendar_id, sync_token=None,
                             time_min=None) -> (events, next_sync_token)
  - freebusy(access_token, calendar_ids, time_min, time_max) -> {cal: [{start,end}]}
  - revoke_token(token) -> bool

This module never touches the database or TokenCipher — callers handle
encryption and persistence. This keeps the client testable in isolation
and mirrors the QuickBooks pattern.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger("google_calendar_client")

GOOGLE_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_API_BASE = "https://www.googleapis.com/calendar/v3"

# Required scopes for two-way sync + freebusy
GOOGLE_SCOPES = " ".join([
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.freebusy",
])


def build_oauth_url(client_id: str, redirect_uri: str, state_token: str,
                    *, login_hint: Optional[str] = None) -> str:
    """Construct the user-facing Google consent URL."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",  # force refresh_token issuance
        "state": state_token,
        "include_granted_scopes": "true",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{GOOGLE_AUTH_BASE}?{urllib.parse.urlencode(params)}"


async def exchange_code(client_id: str, client_secret: str,
                        redirect_uri: str, code: str) -> Dict[str, Any]:
    """Exchange OAuth authorization code for access + refresh tokens."""
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(GOOGLE_TOKEN_URL, data=data) as resp:
            body = await resp.text()
            if resp.status != 200:
                logger.error("Google token exchange failed: %d %s", resp.status, body[:200])
                raise RuntimeError(f"Google token exchange failed (HTTP {resp.status})")
            return json.loads(body)


async def refresh_access_token(client_id: str, client_secret: str,
                                refresh_token: str) -> Dict[str, Any]:
    """Refresh access token. Returns dict with access_token, expires_in, scope, token_type."""
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(GOOGLE_TOKEN_URL, data=data) as resp:
            body = await resp.text()
            if resp.status != 200:
                logger.error("Google token refresh failed: %d %s", resp.status, body[:200])
                raise RuntimeError(f"Google token refresh failed (HTTP {resp.status})")
            return json.loads(body)


async def revoke_token(token: str) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GOOGLE_REVOKE_URL, params={"token": token}) as resp:
                return resp.status == 200
    except Exception as e:
        logger.warning("Google revoke failed (non-fatal): %s", e)
        return False


async def fetch_user_info(access_token: str) -> Dict[str, Any]:
    """OIDC userinfo — returns sub, email, etc."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        ) as resp:
            if resp.status != 200:
                return {}
            return await resp.json()


async def list_calendars(access_token: str) -> List[Dict[str, Any]]:
    """List calendars the user can write to."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{GOOGLE_API_BASE}/users/me/calendarList",
            headers={"Authorization": f"Bearer {access_token}"},
        ) as resp:
            if resp.status != 200:
                logger.warning("Google list_calendars failed: %d", resp.status)
                return []
            data = await resp.json()
            return data.get("items", [])


def _build_event_payload(*, summary: str, description: str,
                         start_iso: str, end_iso: str,
                         timezone_str: str = "America/New_York",
                         location: Optional[str] = None,
                         attendees: Optional[List[str]] = None,
                         conference_link: Optional[str] = None,
                         source_session_id: Optional[str] = None) -> Dict[str, Any]:
    """Compose a Google Calendar event payload."""
    payload: Dict[str, Any] = {
        "summary": summary,
        "description": description or "",
        "start": {"dateTime": start_iso, "timeZone": timezone_str},
        "end": {"dateTime": end_iso, "timeZone": timezone_str},
    }
    if location:
        payload["location"] = location
    if attendees:
        payload["attendees"] = [{"email": e} for e in attendees if e]
    if conference_link:
        # Use conferenceData entryPoint or stuff the link into description
        payload["description"] = (payload["description"] + f"\n\nJoin: {conference_link}").strip()
    if source_session_id:
        payload["extendedProperties"] = {
            "private": {"sanctuary_session_id": source_session_id}
        }
    return payload


def _event_url(calendar_id: str, event_id: Optional[str] = None,
               *, send_updates: Optional[str] = None,
               conference_data: bool = False) -> str:
    base = f"{GOOGLE_API_BASE}/calendars/{urllib.parse.quote(calendar_id)}/events"
    if event_id:
        base = f"{base}/{urllib.parse.quote(event_id)}"
    params = []
    if send_updates:
        params.append(f"sendUpdates={urllib.parse.quote(send_updates)}")
    if conference_data:
        params.append("conferenceDataVersion=1")
    return f"{base}?{'&'.join(params)}" if params else base


async def create_event(access_token: str, calendar_id: str,
                       payload: Dict[str, Any],
                       send_updates: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Create a calendar event. ``send_updates`` e.g. ``all`` emails attendees."""
    url = _event_url(
        calendar_id,
        send_updates=send_updates,
        conference_data=bool(payload.get("conferenceData")),
    )
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        ) as resp:
            body = await resp.text()
            if resp.status not in (200, 201):
                logger.warning("Google create_event failed: %d %s", resp.status, body[:200])
                return None
            return json.loads(body)


async def update_event(access_token: str, calendar_id: str, event_id: str,
                        payload: Dict[str, Any], etag: Optional[str] = None
                        ) -> Optional[Dict[str, Any]]:
    url = _event_url(
        calendar_id,
        event_id,
        conference_data=bool(payload.get("conferenceData")),
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    if etag:
        headers["If-Match"] = etag
    async with aiohttp.ClientSession() as session:
        async with session.patch(url, headers=headers, json=payload) as resp:
            body = await resp.text()
            if resp.status == 412:  # Precondition failed — etag stale
                logger.info("Google update_event etag stale for %s — caller should re-fetch", event_id)
                return None
            if resp.status not in (200, 201):
                logger.warning("Google update_event failed: %d %s", resp.status, body[:200])
                return None
            return json.loads(body)


async def delete_event(access_token: str, calendar_id: str, event_id: str) -> bool:
    url = (f"{GOOGLE_API_BASE}/calendars/{urllib.parse.quote(calendar_id)}"
           f"/events/{urllib.parse.quote(event_id)}")
    async with aiohttp.ClientSession() as session:
        async with session.delete(
            url, headers={"Authorization": f"Bearer {access_token}"}
        ) as resp:
            # 204 = deleted, 410 = already gone (treat as success), 404 = not found (success)
            return resp.status in (204, 404, 410)


async def list_events_incremental(access_token: str, calendar_id: str,
                                   sync_token: Optional[str] = None,
                                   time_min: Optional[str] = None,
                                   time_max: Optional[str] = None
                                   ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Incremental sync. If sync_token is None, performs a bounded full sync.

    Returns (events, next_sync_token). If Google returns 410 (sync token
    invalidated), caller should retry with sync_token=None.
    """
    url = f"{GOOGLE_API_BASE}/calendars/{urllib.parse.quote(calendar_id)}/events"
    headers = {"Authorization": f"Bearer {access_token}"}
    all_events: List[Dict[str, Any]] = []
    next_sync_token: Optional[str] = None
    page_token: Optional[str] = None

    base_params: Dict[str, str] = {"singleEvents": "true", "maxResults": "250"}
    if sync_token:
        base_params["syncToken"] = sync_token
    else:
        # Full sync — bound to a sane window unless caller provided one
        base_params["timeMin"] = time_min or (
            datetime.now(timezone.utc) - timedelta(days=7)
        ).isoformat().replace("+00:00", "Z")
        if time_max:
            base_params["timeMax"] = time_max
        base_params["showDeleted"] = "true"

    async with aiohttp.ClientSession() as session:
        while True:
            params = dict(base_params)
            if page_token:
                params["pageToken"] = page_token
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 410:
                    # Sync token expired — caller must retry full sync
                    logger.info("Google sync token expired for %s — full resync needed", calendar_id)
                    return [], None
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("Google list_events failed: %d %s", resp.status, body[:200])
                    return all_events, sync_token
                data = await resp.json()
            for item in data.get("items", []):
                all_events.append(item)
            page_token = data.get("nextPageToken")
            if not page_token:
                next_sync_token = data.get("nextSyncToken") or sync_token
                break
    return all_events, next_sync_token


async def freebusy(access_token: str, calendar_ids: List[str],
                    time_min: str, time_max: str) -> Dict[str, List[Dict[str, str]]]:
    """Returns {calendar_id: [{start, end}, ...]} for busy windows."""
    if not calendar_ids:
        return {}
    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "items": [{"id": cid} for cid in calendar_ids],
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{GOOGLE_API_BASE}/freeBusy",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=body,
        ) as resp:
            if resp.status != 200:
                logger.warning("Google freebusy failed: %d", resp.status)
                return {}
            data = await resp.json()
            calendars = data.get("calendars", {})
            return {
                cid: cal.get("busy", [])
                for cid, cal in calendars.items()
            }


__all__ = [
    "GOOGLE_SCOPES",
    "build_oauth_url",
    "exchange_code",
    "refresh_access_token",
    "revoke_token",
    "fetch_user_info",
    "list_calendars",
    "create_event",
    "update_event",
    "delete_event",
    "list_events_incremental",
    "freebusy",
    "_build_event_payload",
]
