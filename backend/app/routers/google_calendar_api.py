"""Google Calendar API — per-user OAuth + connection management for two-way sync.

Two routers exported:
  - router        (auth-gated, get_current_user — works for COACH, CLIENT, ADMIN)
  - oauth_router  (public — handles Google OAuth callback)

Mirrors the QuickBooks multi-tenant pattern. All tokens encrypted at rest
via TokenCipher (Fernet).

Endpoints
---------
GET  /api/calendar/google/health         — public-ish health
GET  /api/calendar/google/connect        — returns oauth_url (rate-limited)
GET  /api/calendar/google/status         — connection status for caller
GET  /api/calendar/google/calendars      — list user's writable calendars
POST /api/calendar/google/settings       — set target_calendar_id, sync_enabled
POST /api/calendar/google/disconnect     — revoke + delete connection
POST /api/calendar/google/sync-now       — force a pull from Google (rate-limited)
GET  /api/calendar/google/callback       — OAuth callback (public)
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

try:
    from app.services.api_server import get_current_user, _get_auth_redis
except ImportError:
    from backend.app.services.api_server import get_current_user, _get_auth_redis

try:
    from app.services.skyeye_platform_base import TokenCipher
except ImportError:
    from backend.app.services.skyeye_platform_base import TokenCipher

try:
    from app.services import google_calendar_client as gcc
except ImportError:
    from backend.app.services import google_calendar_client as gcc

logger = logging.getLogger("google_calendar_api")

router = APIRouter(
    prefix="/api/calendar/google",
    tags=["calendar-google"],
    dependencies=[Depends(get_current_user)],
)
oauth_router = APIRouter(
    prefix="/api/calendar/google",
    tags=["calendar-google-oauth"],
)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "https://api.sovereignsanctuary.net/api/calendar/google/callback",
)
GOOGLE_POST_AUTH_REDIRECT = os.getenv(
    "GOOGLE_POST_AUTH_REDIRECT",
    "https://app.sovereignsanctuary.net/?google_calendar=connected",
)

_cipher = TokenCipher.get()

# ── Rate Limiting (per-user, per-action) ────────────────────────────────
_rate_limits: dict = defaultdict(list)
RATE_WINDOW = 3600
MAX_AUTH_PER_HOUR = 30
MAX_SYNC_PER_HOUR = 12


def _check_rate(user_key: str, action: str, limit: int) -> None:
    key = f"{user_key}:{action}"
    now = time.time()
    _rate_limits[key] = [t for t in _rate_limits[key] if now - t < RATE_WINDOW]
    if len(_rate_limits[key]) >= limit:
        raise HTTPException(429, f"Rate limit exceeded: max {limit} {action} per hour")
    _rate_limits[key].append(now)


def _user_id(user: Dict) -> str:
    uid = (user.get("username") or user.get("user_id") or "").strip()
    if not uid:
        raise HTTPException(400, "Could not determine user identity")
    return uid


def _user_role(user: Dict) -> str:
    role = (user.get("role") or "CLIENT").upper()
    if role not in ("COACH", "CLIENT", "ADMIN"):
        role = "CLIENT"
    return role


# ── Settings model ──────────────────────────────────────────────────────
class CalendarSettingsRequest(BaseModel):
    target_calendar_id: Optional[str] = None
    sync_enabled: Optional[bool] = None


# ═══════════════════════════════════════════════════════════════════════
# Auth-gated endpoints
# ═══════════════════════════════════════════════════════════════════════

@router.get("/health")
async def google_health():
    return {
        "status": "ok",
        "service": "google_calendar",
        "configured": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
    }


@router.get("/connect")
async def google_connect(request: Request, user: Dict = Depends(get_current_user)):
    """Generate OAuth URL with CSRF state token scoped to user."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "GOOGLE_CLIENT_ID/SECRET not configured")

    uid = _user_id(user)
    role = _user_role(user)
    _check_rate(uid, "auth", MAX_AUTH_PER_HOUR)

    state_token = secrets.token_urlsafe(32)
    r = await _get_auth_redis()
    if not r:
        raise HTTPException(503, "Redis unavailable — cannot issue OAuth state")
    await r.setex(
        f"google_oauth_state:{state_token}",
        300,
        json.dumps({"user_id": uid, "role": role}),
    )

    url = gcc.build_oauth_url(GOOGLE_CLIENT_ID, GOOGLE_REDIRECT_URI, state_token,
                              login_hint=user.get("email"))
    return {"oauth_url": url}


@router.get("/status")
async def google_status(request: Request, user: Dict = Depends(get_current_user)):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    uid = _user_id(user)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM google_calendar_connection WHERE user_id = $1", uid
        )
    if not row:
        return {"connected": False}

    expiry = row["token_expiry"]
    expired = expiry < datetime.now(timezone.utc) if expiry else True
    return {
        "connected": True,
        "google_email": row["google_email"],
        "target_calendar_id": row["target_calendar_id"] or "primary",
        "sync_enabled": bool(row["sync_enabled"]),
        "last_sync_at": row["last_sync_at"].isoformat() if row["last_sync_at"] else None,
        "token_expired": expired,
        "error_message": row["error_message"],
        "error_count": row["error_count"] or 0,
    }


@router.get("/calendars")
async def google_calendars_list(request: Request, user: Dict = Depends(get_current_user)):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    uid = _user_id(user)
    access_token = await _ensure_valid_access_token(pool, uid)
    items = await gcc.list_calendars(access_token)
    return [
        {
            "id": c.get("id"),
            "summary": c.get("summary"),
            "primary": bool(c.get("primary")),
            "accessRole": c.get("accessRole"),
            "timeZone": c.get("timeZone"),
        }
        for c in items
    ]


@router.post("/settings")
async def google_settings(req: CalendarSettingsRequest, request: Request,
                           user: Dict = Depends(get_current_user)):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    uid = _user_id(user)
    fields = []
    args = []
    if req.target_calendar_id is not None:
        fields.append(f"target_calendar_id = ${len(args)+1}")
        args.append(req.target_calendar_id.strip() or "primary")
    if req.sync_enabled is not None:
        fields.append(f"sync_enabled = ${len(args)+1}")
        args.append(bool(req.sync_enabled))
    if not fields:
        raise HTTPException(400, "No settings provided")
    fields.append("updated_at = NOW()")
    sql = (
        f"UPDATE google_calendar_connection SET {', '.join(fields)} "
        f"WHERE user_id = ${len(args)+1}"
    )
    args.append(uid)
    async with pool.acquire() as conn:
        await conn.execute(sql, *args)
    return {"status": "ok"}


@router.post("/disconnect")
async def google_disconnect(request: Request, user: Dict = Depends(get_current_user)):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    uid = _user_id(user)
    _check_rate(uid, "auth", MAX_AUTH_PER_HOUR)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT refresh_token FROM google_calendar_connection WHERE user_id = $1", uid
        )
        if row and row["refresh_token"]:
            try:
                refresh = _cipher.decrypt(row["refresh_token"])
                await gcc.revoke_token(refresh)
            except Exception as e:
                logger.warning("Google revoke failed (non-fatal): %s", e)
        await conn.execute(
            "DELETE FROM google_calendar_connection WHERE user_id = $1", uid
        )
    return {"status": "disconnected"}


@router.post("/sync-now")
async def google_sync_now(request: Request, user: Dict = Depends(get_current_user)):
    """Trigger an immediate pull from Google. Push happens inline at booking time."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    uid = _user_id(user)
    _check_rate(uid, "sync", MAX_SYNC_PER_HOUR)

    agent = getattr(request.app.state, "google_calendar_sync_agent", None)
    if not agent:
        raise HTTPException(503, "Google Calendar sync agent not running")
    try:
        result = await agent.pull_user(uid)
        return {"status": "ok", **(result or {})}
    except Exception as e:
        logger.warning("Manual google sync failed for %s: %s", uid, e)
        raise HTTPException(500, "Sync failed")


# ═══════════════════════════════════════════════════════════════════════
# Public OAuth callback
# ═══════════════════════════════════════════════════════════════════════

@oauth_router.get("/callback")
async def google_callback(request: Request, code: str = "", state: str = "",
                           error: str = ""):
    """Exchange code for tokens, validate CSRF state, encrypt and store."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    if error:
        return HTMLResponse(
            f"<h2>Google Calendar connection failed</h2><p>{error}</p>",
            status_code=400,
        )
    if not code or not state:
        raise HTTPException(400, "Missing code or state parameter")
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "Google credentials not configured")

    r = await _get_auth_redis()
    if not r:
        raise HTTPException(503, "Redis unavailable — cannot validate OAuth state")
    state_data = await r.get(f"google_oauth_state:{state}")
    if not state_data:
        raise HTTPException(400, "Invalid or expired OAuth state")
    await r.delete(f"google_oauth_state:{state}")
    try:
        parsed = json.loads(state_data)
    except Exception:
        raise HTTPException(400, "Corrupt OAuth state")
    uid = parsed.get("user_id")
    role = (parsed.get("role") or "CLIENT").upper()
    if not uid:
        raise HTTPException(400, "OAuth state missing user_id")

    try:
        tokens = await gcc.exchange_code(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
                                          GOOGLE_REDIRECT_URI, code)
    except Exception as e:
        logger.error("Google code exchange failed for %s: %s", uid, e)
        raise HTTPException(502, "Google code exchange failed")

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = int(tokens.get("expires_in") or 3600)
    scope = tokens.get("scope") or gcc.GOOGLE_SCOPES
    if not access_token or not refresh_token:
        # If refresh_token missing, user has prior consent — must revoke + reconnect.
        raise HTTPException(400, "Google did not return refresh_token. Please disconnect prior consent and reconnect.")

    user_info = await gcc.fetch_user_info(access_token)
    google_email = user_info.get("email") or ""
    google_sub = user_info.get("sub") or ""

    enc_access = _cipher.encrypt(access_token)
    enc_refresh = _cipher.encrypt(refresh_token)
    expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO google_calendar_connection
                 (user_id, user_role, google_email, google_user_id,
                  access_token, refresh_token, token_expiry, scopes,
                  target_calendar_id, sync_enabled,
                  connected_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'primary', true, NOW(), NOW())
               ON CONFLICT (user_id) DO UPDATE SET
                  user_role = EXCLUDED.user_role,
                  google_email = EXCLUDED.google_email,
                  google_user_id = EXCLUDED.google_user_id,
                  access_token = EXCLUDED.access_token,
                  refresh_token = EXCLUDED.refresh_token,
                  token_expiry = EXCLUDED.token_expiry,
                  scopes = EXCLUDED.scopes,
                  sync_enabled = true,
                  error_message = NULL,
                  error_count = 0,
                  updated_at = NOW()""",
            uid, role, google_email, google_sub,
            enc_access, enc_refresh, expiry, scope,
        )
    return RedirectResponse(GOOGLE_POST_AUTH_REDIRECT, status_code=302)


# ═══════════════════════════════════════════════════════════════════════
# Internal helpers (also used by sync agent + schedule wiring)
# ═══════════════════════════════════════════════════════════════════════

async def _ensure_valid_access_token(pool, user_id: str) -> str:
    """Return a valid access_token for user_id, refreshing if needed."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT access_token, refresh_token, token_expiry "
            "FROM google_calendar_connection WHERE user_id = $1",
            user_id,
        )
    if not row:
        raise HTTPException(400, "No Google Calendar connection for this user")
    expiry = row["token_expiry"]
    now = datetime.now(timezone.utc)
    if expiry and (expiry - now).total_seconds() > 300:
        return _cipher.decrypt(row["access_token"])

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "Google credentials not configured")

    refresh = _cipher.decrypt(row["refresh_token"])
    try:
        tokens = await gcc.refresh_access_token(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, refresh)
    except Exception as e:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE google_calendar_connection SET error_message = $1, "
                "error_count = error_count + 1, updated_at = NOW() "
                "WHERE user_id = $2",
                f"Token refresh failed: {e}",
                user_id,
            )
        raise HTTPException(502, "Google token refresh failed")

    new_access = tokens.get("access_token")
    new_expiry = now + timedelta(seconds=int(tokens.get("expires_in") or 3600))
    enc_access = _cipher.encrypt(new_access)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE google_calendar_connection SET access_token = $1, "
            "token_expiry = $2, error_message = NULL, updated_at = NOW() "
            "WHERE user_id = $3",
            enc_access, new_expiry, user_id,
        )
    return new_access
