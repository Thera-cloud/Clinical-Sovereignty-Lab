"""Coach Workspace OAuth URL builder (GOOGLE_WS_*).

Separate from google_calendar_client.GOOGLE_SCOPES (calendar-only, 183).
incremental=false: include_granted_scopes is omitted/false. Never gmail.send.
"""

from __future__ import annotations

import urllib.parse
from typing import Optional

GOOGLE_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"

# Full Workspace grant — COACH only. Do not copy into GOOGLE_SCOPES.
GOOGLE_WS_SCOPES = " ".join([
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.file",
])


def build_workspace_oauth_url(
    client_id: str,
    redirect_uri: str,
    state_token: str,
    *,
    login_hint: Optional[str] = None,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_WS_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state_token,
        "include_granted_scopes": "false",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{GOOGLE_AUTH_BASE}?{urllib.parse.urlencode(params)}"
