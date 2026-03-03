"""QuickBooks Online integration router — admin-only OAuth + sync management.

Two routers exported:
  - router        (auth-gated, require_admin)
  - oauth_router  (public — handles Intuit OAuth callback)
"""

import json
import os
import secrets
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

try:
    from app.secure_logger import get_secure_logger
except ImportError:
    from backend.app.secure_logger import get_secure_logger

logger = get_secure_logger(__name__)

try:
    from app.services.api_server import require_admin, _get_auth_redis
except ImportError:
    from backend.app.services.api_server import require_admin, _get_auth_redis

try:
    from app.services.skyeye_platform_base import TokenCipher
except ImportError:
    from backend.app.services.skyeye_platform_base import TokenCipher

router = APIRouter(
    prefix="/api/admin/quickbooks",
    tags=["QuickBooks"],
    dependencies=[Depends(require_admin)],
)

oauth_router = APIRouter(
    prefix="/api/admin/quickbooks",
    tags=["quickbooks-admin-oauth"],
)

QB_CLIENT_ID = os.getenv("QB_CLIENT_ID", "")
QB_CLIENT_SECRET = os.getenv("QB_CLIENT_SECRET", "")
QB_ENVIRONMENT = os.getenv("QB_ENVIRONMENT", "sandbox")
QB_REDIRECT_URI = os.getenv(
    "QB_REDIRECT_URI",
    "https://api.sovereignsanctuary.net/api/admin/quickbooks/callback",
)

QB_AUTH_BASE = "https://appcenter.intuit.com/connect/oauth2"
QB_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QB_REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"
QB_API_BASE = (
    "https://quickbooks.api.intuit.com"
    if QB_ENVIRONMENT == "production"
    else "https://sandbox-quickbooks.api.intuit.com"
)
QB_SCOPES = "com.intuit.quickbooks.accounting"

_cipher = TokenCipher.get()

# ── Rate Limiting ────────────────────────────────────────────────────────
_rate_limits: dict = defaultdict(list)
RATE_WINDOW = 3600
MAX_SYNC_PER_HOUR = 10
MAX_AUTH_PER_HOUR = 30


def _check_rate(user_id: str, action: str, limit: int):
    key = f"{user_id}:{action}"
    now = time.time()
    _rate_limits[key] = [t for t in _rate_limits[key] if now - t < RATE_WINDOW]
    if len(_rate_limits[key]) >= limit:
        raise HTTPException(429, f"Rate limit exceeded: max {limit} {action} per hour")
    _rate_limits[key].append(now)


class AccountMappingRequest(BaseModel):
    internal_category: str
    qb_account_id: str
    qb_account_name: Optional[str] = None


@router.get("/health")
async def qb_health():
    return {"status": "ok", "service": "quickbooks", "environment": QB_ENVIRONMENT}


@router.get("/connect")
async def qb_connect(request: Request, admin=Depends(require_admin)):
    """Generate OAuth 2.0 authorization URL with CSRF state token."""
    if not QB_CLIENT_ID:
        raise HTTPException(503, "QB_CLIENT_ID not configured")

    admin_name = admin.get("username", "admin") if isinstance(admin, dict) else "admin"
    _check_rate(admin_name, "auth", MAX_AUTH_PER_HOUR)

    state_token = secrets.token_urlsafe(32)
    r = await _get_auth_redis()
    if r:
        await r.setex(
            f"qb_oauth_state:{state_token}",
            300,
            json.dumps({"role": "admin", "scope_id": "platform"}),
        )

    params = urllib.parse.urlencode({
        "client_id": QB_CLIENT_ID,
        "response_type": "code",
        "scope": QB_SCOPES,
        "redirect_uri": QB_REDIRECT_URI,
        "state": state_token,
    })
    return {"oauth_url": f"{QB_AUTH_BASE}?{params}"}


@oauth_router.get("/callback")
async def qb_callback(code: str, realmId: str, request: Request, state: str = ""):
    """Handle OAuth callback — validate CSRF, exchange code, encrypt and store tokens."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    if not QB_CLIENT_ID or not QB_CLIENT_SECRET:
        raise HTTPException(503, "QB credentials not configured")

    r = await _get_auth_redis()
    if r and state:
        state_data = await r.get(f"qb_oauth_state:{state}")
        if not state_data:
            raise HTTPException(400, "Invalid or expired OAuth state")
        await r.delete(f"qb_oauth_state:{state}")
        parsed = json.loads(state_data)
        if parsed.get("role") != "admin":
            raise HTTPException(400, "State mismatch: expected admin")
    elif not state:
        logger.warning("Admin QB callback received without state parameter")

    import aiohttp
    import base64

    auth_header = base64.b64encode(
        f"{QB_CLIENT_ID}:{QB_CLIENT_SECRET}".encode()
    ).decode()

    async with aiohttp.ClientSession() as session:
        async with session.post(
            QB_TOKEN_URL,
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": QB_REDIRECT_URI,
            },
        ) as resp:
            if resp.status != 200:
                logger.error("QB token exchange failed: status=%d", resp.status)
                raise HTTPException(502, "QuickBooks token exchange failed")
            tokens = await resp.json()

    expiry = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))

    encrypted_access = _cipher.encrypt(tokens["access_token"])
    encrypted_refresh = _cipher.encrypt(tokens["refresh_token"])

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM qb_connection")
        await conn.execute(
            """INSERT INTO qb_connection
               (realm_id, access_token, refresh_token, token_expiry, connected_by)
               VALUES ($1, $2, $3, $4, $5)""",
            realmId,
            encrypted_access,
            encrypted_refresh,
            expiry,
            "admin",
        )

    from fastapi.responses import HTMLResponse
    return HTMLResponse("""<!DOCTYPE html><html><body style="background:#050505;color:#F5F5F5;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh">
<div style="text-align:center"><h2 style="color:#C9A962">QuickBooks Connected</h2><p>You may close this tab.</p>
<script>try{window.opener&&window.opener.postMessage({type:'qb_connected'},'*')}catch(e){}</script></div></body></html>""")


@router.get("/status")
async def qb_status(request: Request):
    """Get current QB connection status."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM qb_connection ORDER BY created_at DESC LIMIT 1")

    if not row:
        return {"connected": False, "message": "No QuickBooks connection"}

    now = datetime.now(timezone.utc)
    token_expiry = row["token_expiry"]
    expired = token_expiry < now if token_expiry else True

    refresh_issued = row.get("refresh_token_issued_at") or row["connected_at"]
    refresh_expires_at = refresh_issued + timedelta(days=100) if refresh_issued else None
    refresh_days_remaining = None
    if refresh_expires_at:
        delta = refresh_expires_at - now
        refresh_days_remaining = max(0, delta.days)

    return {
        "connected": True,
        "realm_id": row["realm_id"],
        "company_name": row["company_name"],
        "connected_by": row["connected_by"],
        "connected_at": row["connected_at"].isoformat() if row["connected_at"] else None,
        "last_sync_at": row["last_sync_at"].isoformat() if row["last_sync_at"] else None,
        "token_expired": expired,
        "token_expiry": token_expiry.isoformat() if token_expiry else None,
        "token_healthy": not expired,
        "error_message": row["error_message"],
        "refresh_token_issued_at": refresh_issued.isoformat() if refresh_issued else None,
        "refresh_token_expires_at": refresh_expires_at.isoformat() if refresh_expires_at else None,
        "refresh_days_remaining": refresh_days_remaining,
    }


@router.post("/refresh-token")
async def qb_refresh_token_now(request: Request, admin=Depends(require_admin)):
    """Manually refresh the QB access token (and get a new refresh token)."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    admin_name = admin.get("username", "admin") if isinstance(admin, dict) else "admin"
    _check_rate(admin_name, "auth", MAX_AUTH_PER_HOUR)

    if not QB_CLIENT_ID or not QB_CLIENT_SECRET:
        raise HTTPException(503, "QB credentials not configured")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT refresh_token FROM qb_connection ORDER BY created_at DESC LIMIT 1"
        )
    if not row or not row["refresh_token"]:
        raise HTTPException(400, "No refresh token available")

    refresh_token = _cipher.decrypt(row["refresh_token"])
    if not refresh_token:
        raise HTTPException(400, "Could not decrypt refresh token")

    import aiohttp
    import base64

    auth_header = base64.b64encode(
        f"{QB_CLIENT_ID}:{QB_CLIENT_SECRET}".encode()
    ).decode()

    now = datetime.now(timezone.utc)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                QB_TOKEN_URL,
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("QB manual refresh failed: %d — %s", resp.status, body)
                    raise HTTPException(502, f"Intuit token refresh failed: {resp.status}")
                tokens = await resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("QB manual refresh exception: %s", e)
        raise HTTPException(502, f"Token refresh request failed: {e}")

    new_expiry = now + timedelta(seconds=tokens.get("expires_in", 3600))
    enc_access = _cipher.encrypt(tokens["access_token"])
    new_refresh = tokens.get("refresh_token", refresh_token)
    enc_refresh = _cipher.encrypt(new_refresh)

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE qb_connection SET
                 access_token = $1, refresh_token = $2,
                 token_expiry = $3, refresh_token_issued_at = $4,
                 error_message = NULL""",
            enc_access,
            enc_refresh,
            new_expiry,
            now,
        )

    new_refresh_expires = now + timedelta(days=100)
    logger.info("QB refresh token manually renewed by %s — new expiry %s", admin_name, new_refresh_expires.isoformat())

    return {
        "status": "refreshed",
        "access_token_expiry": new_expiry.isoformat(),
        "refresh_token_issued_at": now.isoformat(),
        "refresh_token_expires_at": new_refresh_expires.isoformat(),
        "refresh_days_remaining": 100,
    }


@router.post("/disconnect")
async def qb_disconnect(request: Request, admin=Depends(require_admin)):
    """Revoke QB tokens and clear connection."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    admin_name = admin.get("username", "admin") if isinstance(admin, dict) else "admin"
    _check_rate(admin_name, "auth", MAX_AUTH_PER_HOUR)

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT refresh_token FROM qb_connection LIMIT 1")
        if row and row["refresh_token"] and QB_CLIENT_ID and QB_CLIENT_SECRET:
            import aiohttp
            import base64

            refresh = _cipher.decrypt(row["refresh_token"])
            auth_header = base64.b64encode(
                f"{QB_CLIENT_ID}:{QB_CLIENT_SECRET}".encode()
            ).decode()
            try:
                async with aiohttp.ClientSession() as session:
                    await session.post(
                        QB_REVOKE_URL,
                        headers={
                            "Authorization": f"Basic {auth_header}",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                        json={"token": refresh},
                    )
            except Exception as e:
                logger.warning("QB revoke failed (non-fatal): %s", e)

        await conn.execute("DELETE FROM qb_connection")

    return {"status": "disconnected"}


@router.post("/sync/trigger")
async def qb_sync_trigger(request: Request, admin=Depends(require_admin)):
    """Trigger an immediate sync cycle."""
    admin_name = admin.get("username", "admin") if isinstance(admin, dict) else "admin"
    _check_rate(admin_name, "sync", MAX_SYNC_PER_HOUR)

    agent = getattr(request.app.state, "quickbooks_sync_agent", None)
    if not agent:
        raise HTTPException(503, "QuickBooks sync agent not available")

    import asyncio
    asyncio.create_task(agent._run_one_cycle())
    return {"status": "sync_triggered", "message": "Sync cycle started in background"}


@router.get("/sync/history")
async def qb_sync_history(request: Request, limit: int = 50):
    """Get recent sync log entries."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, sync_type, source_table, source_id, qb_entity_type,
                      qb_entity_id, amount_cents, status, error_message, created_at
               FROM qb_sync_log ORDER BY created_at DESC LIMIT $1""",
            limit,
        )

    return [
        {
            "id": str(r["id"]),
            "sync_type": r["sync_type"],
            "source_table": r["source_table"],
            "source_id": str(r["source_id"]),
            "qb_entity_type": r["qb_entity_type"],
            "qb_entity_id": r["qb_entity_id"],
            "amount_cents": r["amount_cents"],
            "status": r["status"],
            "error_message": r["error_message"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.get("/account-mapping")
async def qb_get_mapping(request: Request):
    """Get current QB account mappings."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM qb_account_mapping ORDER BY internal_category"
        )

    return [
        {
            "id": str(r["id"]),
            "internal_category": r["internal_category"],
            "qb_account_id": r["qb_account_id"],
            "qb_account_name": r["qb_account_name"],
        }
        for r in rows
    ]


@router.post("/account-mapping")
async def qb_set_mapping(req: AccountMappingRequest, request: Request):
    """Set or update a QB account mapping."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    valid_categories = [
        "subscription_revenue", "token_sales", "gkm_donations",
        "coach_payouts", "corporate_revenue",
    ]
    if req.internal_category not in valid_categories:
        raise HTTPException(400, f"internal_category must be one of: {valid_categories}")

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO qb_account_mapping (internal_category, qb_account_id, qb_account_name)
               VALUES ($1, $2, $3)
               ON CONFLICT (internal_category) DO UPDATE SET
                 qb_account_id = EXCLUDED.qb_account_id,
                 qb_account_name = EXCLUDED.qb_account_name""",
            req.internal_category,
            req.qb_account_id,
            req.qb_account_name or "",
        )

    return {"status": "ok", "category": req.internal_category, "qb_account_id": req.qb_account_id}
