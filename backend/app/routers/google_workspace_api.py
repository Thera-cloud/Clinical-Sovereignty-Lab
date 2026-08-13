"""Coach Google Workspace OAuth (GOOGLE_WS_*). Default ENABLE_WS_OAUTH=off.

183 calendar OAuth stays on /api/calendar/google with calendar-only scopes.
This router never uses GOOGLE_CLIENT_ID.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

try:
    from app.services.api_server import get_current_user, require_coach, _get_auth_redis
except ImportError:
    from backend.app.services.api_server import get_current_user, require_coach, _get_auth_redis

try:
    from app.services.skyeye_platform_base import TokenCipher
except ImportError:
    from backend.app.services.skyeye_platform_base import TokenCipher

try:
    from app.services.google_workspace_oauth import (
        GOOGLE_WS_SCOPES,
        build_workspace_oauth_url,
    )
    from app.services.google_workspace_service import get_google_svc
    from app.services import google_calendar_client as gcc
except ImportError:
    from backend.app.services.google_workspace_oauth import (
        GOOGLE_WS_SCOPES,
        build_workspace_oauth_url,
    )
    from backend.app.services.google_workspace_service import get_google_svc
    from backend.app.services import google_calendar_client as gcc

logger = logging.getLogger("google_workspace_api")

router = APIRouter(
    prefix="/api/workspace/google",
    tags=["google-workspace"],
    dependencies=[Depends(get_current_user)],
)
oauth_router = APIRouter(
    prefix="/api/workspace/google",
    tags=["google-workspace-oauth"],
)

GOOGLE_WS_CLIENT_ID = os.getenv("GOOGLE_WS_CLIENT_ID", "")
GOOGLE_WS_CLIENT_SECRET = os.getenv("GOOGLE_WS_CLIENT_SECRET", "")
GOOGLE_WS_REDIRECT_URI = os.getenv(
    "GOOGLE_WS_REDIRECT_URI",
    "https://api.sovereignsanctuary.net/api/workspace/google/callback",
)
GOOGLE_WS_POST_AUTH_REDIRECT = os.getenv(
    "GOOGLE_WS_POST_AUTH_REDIRECT",
    "https://coach.sovereignsanctuary.net/?google_workspace=connected",
)

_cipher = TokenCipher.get()
_rate_limits: dict = defaultdict(list)


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


def _check_rate(user_key: str, action: str, limit: int = 30) -> None:
    key = f"{user_key}:{action}"
    now = time.time()
    _rate_limits[key] = [t for t in _rate_limits[key] if now - t < 3600]
    if len(_rate_limits[key]) >= limit:
        raise HTTPException(429, f"Rate limit exceeded: max {limit} {action} per hour")
    _rate_limits[key].append(now)


def _require_ws_oauth() -> None:
    if not _flag_on("ENABLE_WS_OAUTH"):
        raise HTTPException(403, "temporarily unavailable")


@router.get("/health")
async def workspace_health():
    return {
        "status": "ok",
        "service": "google_workspace",
        "oauth_enabled": _flag_on("ENABLE_WS_OAUTH"),
        "configured": bool(GOOGLE_WS_CLIENT_ID and GOOGLE_WS_CLIENT_SECRET),
        "token_app": "workspace_ws",
    }


@router.get("/connect")
async def workspace_connect(request: Request, user: Dict = Depends(require_coach)):
    """Coach-only Workspace consent. Hidden/403 in prod until O9 + ENABLE_WS_OAUTH."""
    _require_ws_oauth()
    if not GOOGLE_WS_CLIENT_ID or not GOOGLE_WS_CLIENT_SECRET:
        raise HTTPException(503, "GOOGLE_WS_CLIENT_ID/SECRET not configured")

    uid = (user.get("username") or "").strip()
    hw = (user.get("hardware_id") or "").strip()
    if not uid:
        raise HTTPException(400, "Could not determine user identity")
    _check_rate(uid, "ws_auth")

    state_token = secrets.token_urlsafe(32)
    r = await _get_auth_redis()
    if not r:
        raise HTTPException(503, "Redis unavailable — cannot issue OAuth state")
    await r.setex(
        f"google_ws_oauth_state:{state_token}",
        300,
        json.dumps({"user_id": uid, "hardware_id": hw, "role": "COACH"}),
    )
    url = build_workspace_oauth_url(
        GOOGLE_WS_CLIENT_ID,
        GOOGLE_WS_REDIRECT_URI,
        state_token,
        login_hint=user.get("email"),
    )
    return {"oauth_url": url, "incremental": False}


@router.get("/status")
async def workspace_status(request: Request, user: Dict = Depends(require_coach)):
    pool = getattr(request.app.state, "db_pool", None)
    hw = (user.get("hardware_id") or "").strip()
    svc = get_google_svc(pool)
    return await svc.status(hw)


@oauth_router.get("/callback")
async def workspace_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        raise HTTPException(400, f"Google OAuth error: {error}")
    _require_ws_oauth()
    if not code or not state:
        raise HTTPException(400, "Missing code or state")
    r = await _get_auth_redis()
    if not r:
        raise HTTPException(503, "Redis unavailable")
    raw = await r.get(f"google_ws_oauth_state:{state}")
    await r.delete(f"google_ws_oauth_state:{state}")
    if not raw:
        raise HTTPException(400, "Invalid or expired OAuth state")
    meta = json.loads(raw if isinstance(raw, str) else raw.decode())
    uid = meta.get("user_id") or ""
    hw = meta.get("hardware_id") or ""
    tokens = await gcc.exchange_code(
        GOOGLE_WS_CLIENT_ID, GOOGLE_WS_CLIENT_SECRET, GOOGLE_WS_REDIRECT_URI, code
    )
    access = tokens.get("access_token") or ""
    refresh = tokens.get("refresh_token") or ""
    if not access or not refresh:
        raise HTTPException(400, "Google did not return refresh_token")
    scope = tokens.get("scope") or GOOGLE_WS_SCOPES
    expiry = tokens.get("expires_in")
    info = await gcc.fetch_user_info(access)
    pool = getattr(request.app.state, "db_pool", None)
    if pool:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO google_workspace_connection
                  (user_id, hardware_id, user_role, google_email, google_user_id,
                   access_token, refresh_token, token_expiry, scopes,
                   token_app, consent_recorded_at)
                VALUES ($1,$2,'COACH',$3,$4,$5,$6,
                        NOW() + ($7::int * INTERVAL '1 second'), $8,
                        'workspace_ws', NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                  hardware_id = EXCLUDED.hardware_id,
                  google_email = EXCLUDED.google_email,
                  access_token = EXCLUDED.access_token,
                  refresh_token = EXCLUDED.refresh_token,
                  token_expiry = EXCLUDED.token_expiry,
                  scopes = EXCLUDED.scopes,
                  revoked_at = NULL,
                  consent_recorded_at = NOW(),
                  updated_at = NOW()
                """,
                uid,
                hw,
                (info or {}).get("email"),
                (info or {}).get("id") or (info or {}).get("sub"),
                _cipher.encrypt(access),
                _cipher.encrypt(refresh),
                str(int(expiry or 3600)),
                scope,
            )
    return RedirectResponse(GOOGLE_WS_POST_AUTH_REDIRECT)
