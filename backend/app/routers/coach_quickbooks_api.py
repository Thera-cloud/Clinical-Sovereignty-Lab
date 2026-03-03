"""Coach QuickBooks API — coach-scoped QB Online sync for individual coaches.

Two routers exported:
  - router        (auth-gated, require_coach)
  - oauth_router  (public — handles Intuit OAuth callback)
"""

import asyncio
import base64
import json
import os
import random
import secrets
import time
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

try:
    from app.secure_logger import get_secure_logger
except ImportError:
    from backend.app.secure_logger import get_secure_logger

logger = get_secure_logger(__name__)

try:
    from app.services.api_server import require_coach, _get_auth_redis
except ImportError:
    from backend.app.services.api_server import require_coach, _get_auth_redis

try:
    from app.services.skyeye_platform_base import TokenCipher
except ImportError:
    from backend.app.services.skyeye_platform_base import TokenCipher

router = APIRouter(
    prefix="/api/coach/quickbooks",
    tags=["coach-quickbooks"],
    dependencies=[Depends(require_coach)],
)

oauth_router = APIRouter(
    prefix="/api/coach/quickbooks",
    tags=["coach-quickbooks-oauth"],
)

QB_CLIENT_ID = os.getenv("QB_CLIENT_ID", "")
QB_CLIENT_SECRET = os.getenv("QB_CLIENT_SECRET", "")
QB_ENVIRONMENT = os.getenv("QB_ENVIRONMENT", "sandbox")
QB_REDIRECT_URI = os.getenv(
    "QB_COACH_REDIRECT_URI",
    "https://api.sovereignsanctuary.net/api/coach/quickbooks/callback",
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
BATCH_SIZE = 50

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


class CoachAccountMappingRequest(BaseModel):
    internal_category: str
    qb_account_id: str
    qb_account_name: Optional[str] = None


def _get_coach_username(user: Dict) -> str:
    username = user.get("username", "")
    if not username:
        raise HTTPException(400, "Could not determine coach username")
    return username


# ═══════════════════════════════════════════════════════════════════════════
# QB API helpers with exponential backoff + jitter
# ═══════════════════════════════════════════════════════════════════════════

async def _qb_api(
    session: aiohttp.ClientSession, method: str, path: str,
    access_token: str, realm_id: str, json_body: Optional[Dict] = None,
) -> Optional[Dict]:
    url = f"{QB_API_BASE}/v3/company/{realm_id}/{path}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        async with session.request(method, url, headers=headers, json=json_body) as resp:
            if resp.status in (200, 201):
                return await resp.json()
            logger.warning("Coach QB API %s %s → %d", method, path, resp.status)
            return None
    except Exception as e:
        logger.warning("Coach QB API %s %s error: %s", method, path, e)
        return None


async def _qb_api_with_retry(
    session: aiohttp.ClientSession, method: str, path: str,
    access_token: str, realm_id: str, json_body: Optional[Dict] = None,
    max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 30.0,
) -> Optional[Dict]:
    for attempt in range(max_retries + 1):
        result = await _qb_api(session, method, path, access_token, realm_id, json_body)
        if result is not None:
            return result
        if attempt < max_retries:
            delay = min(base_delay * (2 ** attempt), max_delay)
            jitter = random.uniform(0, delay * 0.1)
            await asyncio.sleep(delay + jitter)
    return None


async def _ensure_valid_token(pool, coach_username: str) -> tuple:
    """Returns (access_token, realm_id) or raises."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM qb_coach_connection WHERE coach_username = $1", coach_username
        )
    if not row:
        raise HTTPException(400, "No QuickBooks connection for this coach")

    access_token = _cipher.decrypt(row["access_token"])
    refresh_token = _cipher.decrypt(row["refresh_token"])
    expiry = row["token_expiry"]
    now = datetime.now(timezone.utc)

    if expiry and (expiry - now).total_seconds() > 300:
        return access_token, row["realm_id"]

    if not QB_CLIENT_ID or not QB_CLIENT_SECRET:
        raise HTTPException(503, "QB credentials not configured for token refresh")

    auth_header = base64.b64encode(f"{QB_CLIENT_ID}:{QB_CLIENT_SECRET}".encode()).decode()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                QB_TOKEN_URL,
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            ) as resp:
                if resp.status != 200:
                    logger.error("Coach QB token refresh failed: status=%d", resp.status)
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE qb_coach_connection SET error_message = $1 WHERE coach_username = $2",
                            f"Token refresh failed: {resp.status}", coach_username,
                        )
                    raise HTTPException(502, "QB token refresh failed")
                tokens = await resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Coach QB token refresh exception: %s", e)
        raise HTTPException(502, "QB token refresh error")

    new_expiry = now + timedelta(seconds=tokens.get("expires_in", 3600))
    enc_access = _cipher.encrypt(tokens["access_token"])
    enc_refresh = _cipher.encrypt(tokens.get("refresh_token", refresh_token))

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE qb_coach_connection SET
                 access_token = $1, refresh_token = $2,
                 token_expiry = $3, error_message = NULL, updated_at = NOW()
               WHERE coach_username = $4""",
            enc_access, enc_refresh, new_expiry, coach_username,
        )
    return tokens["access_token"], row["realm_id"]


async def _log_sync(conn, coach_username, sync_type, source_table, source_id,
                     qb_entity_type, qb_entity_id, amount_cents,
                     status="synced", error_message=None):
    await conn.execute(
        """INSERT INTO qb_coach_sync_log
           (coach_username, sync_type, source_table, source_id, qb_entity_type,
            qb_entity_id, amount_cents, status, error_message)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
        coach_username, sync_type, source_table, source_id, qb_entity_type,
        qb_entity_id or "", amount_cents, status, error_message,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Auth-gated endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/health")
async def coach_qb_health():
    return {"status": "ok", "service": "coach_quickbooks"}


@router.get("/connect")
async def coach_qb_connect(request: Request, user: Dict = Depends(require_coach)):
    """Generate OAuth URL with CSRF state token scoped to coach."""
    if not QB_CLIENT_ID:
        raise HTTPException(503, "QB_CLIENT_ID not configured")

    coach_username = _get_coach_username(user)
    _check_rate(coach_username, "auth", MAX_AUTH_PER_HOUR)

    state_token = secrets.token_urlsafe(32)
    r = await _get_auth_redis()
    if r:
        await r.setex(
            f"qb_oauth_state:{state_token}",
            300,
            json.dumps({"role": "coach", "scope_id": coach_username}),
        )

    params = urllib.parse.urlencode({
        "client_id": QB_CLIENT_ID,
        "response_type": "code",
        "scope": QB_SCOPES,
        "redirect_uri": QB_REDIRECT_URI,
        "state": state_token,
    })
    return {"oauth_url": f"{QB_AUTH_BASE}?{params}"}


@router.get("/status")
async def coach_qb_status(request: Request, user: Dict = Depends(require_coach)):
    """Connection status for this coach's QB link."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    coach_username = _get_coach_username(user)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM qb_coach_connection WHERE coach_username = $1", coach_username
        )

    if not row:
        return {"connected": False, "message": "No QuickBooks connection"}

    now = datetime.now(timezone.utc)
    token_expiry = row["token_expiry"]
    expired = token_expiry < now if token_expiry else True

    return {
        "connected": True,
        "realm_id": row["realm_id"],
        "company_name": row["company_name"],
        "connected_by": row["connected_by"],
        "connected_at": row["connected_at"].isoformat() if row["connected_at"] else None,
        "last_sync_at": row["last_sync_at"].isoformat() if row["last_sync_at"] else None,
        "token_expired": expired,
        "token_expiry": token_expiry.isoformat() if token_expiry else None,
        "error_message": row["error_message"],
    }


@router.post("/disconnect")
async def coach_qb_disconnect(request: Request, user: Dict = Depends(require_coach)):
    """Revoke tokens and delete coach QB connection."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    coach_username = _get_coach_username(user)
    _check_rate(coach_username, "auth", MAX_AUTH_PER_HOUR)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT refresh_token FROM qb_coach_connection WHERE coach_username = $1",
            coach_username,
        )
        if row and row["refresh_token"] and QB_CLIENT_ID and QB_CLIENT_SECRET:
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
                logger.warning("Coach QB revoke failed (non-fatal): %s", e)

        await conn.execute(
            "DELETE FROM qb_coach_connection WHERE coach_username = $1", coach_username
        )

    return {"status": "disconnected"}


@router.post("/sync/trigger")
async def coach_qb_sync_trigger(request: Request, user: Dict = Depends(require_coach)):
    """Trigger on-demand sync for this coach."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    coach_username = _get_coach_username(user)
    _check_rate(coach_username, "sync", MAX_SYNC_PER_HOUR)

    access_token, realm_id = await _ensure_valid_token(pool, coach_username)

    hw_id = None
    async with pool.acquire() as conn:
        hw_row = await conn.fetchrow(
            "SELECT hardware_id FROM users WHERE username = $1 AND role = 'COACH'", coach_username
        )
        if hw_row:
            hw_id = hw_row["hardware_id"]

    totals = {"coaching_revenue": 0, "session_income": 0}
    async with aiohttp.ClientSession() as session:
        totals["coaching_revenue"] = await _sync_coaching_revenue(pool, session, access_token, realm_id, coach_username, hw_id)
        totals["session_income"] = await _sync_session_income(pool, session, access_token, realm_id, coach_username, hw_id)

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE qb_coach_connection SET last_sync_at = $1, error_message = NULL, updated_at = NOW() WHERE coach_username = $2",
            datetime.now(timezone.utc), coach_username,
        )

    total_synced = sum(totals.values())
    logger.info("Coach QB sync complete for %s — %d records", coach_username, total_synced)
    return {"status": "sync_complete", "totals": totals, "total_synced": total_synced}


@router.get("/sync/history")
async def coach_qb_sync_history(request: Request, user: Dict = Depends(require_coach), limit: int = 50):
    """Sync log for this coach."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    coach_username = _get_coach_username(user)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, sync_type, source_table, source_id, qb_entity_type,
                      qb_entity_id, amount_cents, status, error_message, created_at
               FROM qb_coach_sync_log WHERE coach_username = $1
               ORDER BY created_at DESC LIMIT $2""",
            coach_username, limit,
        )

    return [
        {
            "id": str(r["id"]),
            "sync_type": r["sync_type"],
            "source_table": r["source_table"],
            "source_id": str(r["source_id"]) if r["source_id"] else None,
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
async def coach_qb_get_mapping(request: Request, user: Dict = Depends(require_coach)):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    coach_username = _get_coach_username(user)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM qb_coach_account_mapping WHERE coach_username = $1 ORDER BY internal_category",
            coach_username,
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
async def coach_qb_set_mapping(req: CoachAccountMappingRequest, request: Request,
                                user: Dict = Depends(require_coach)):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    coach_username = _get_coach_username(user)

    valid = ["coaching_revenue", "session_income"]
    if req.internal_category not in valid:
        raise HTTPException(400, f"internal_category must be one of: {valid}")

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO qb_coach_account_mapping (coach_username, internal_category, qb_account_id, qb_account_name)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (coach_username, internal_category) DO UPDATE SET
                 qb_account_id = EXCLUDED.qb_account_id,
                 qb_account_name = EXCLUDED.qb_account_name,
                 updated_at = NOW()""",
            coach_username, req.internal_category, req.qb_account_id, req.qb_account_name or "",
        )

    return {"status": "ok", "category": req.internal_category, "qb_account_id": req.qb_account_id}


# ═══════════════════════════════════════════════════════════════════════════
# Public OAuth callback (no auth)
# ═══════════════════════════════════════════════════════════════════════════

@oauth_router.get("/callback")
async def coach_qb_callback(code: str, realmId: str, request: Request, state: str = ""):
    """Exchange code for tokens, validate CSRF state, encrypt and store."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    if not QB_CLIENT_ID or not QB_CLIENT_SECRET:
        raise HTTPException(503, "QB credentials not configured")

    r = await _get_auth_redis()
    coach_username = None
    if r and state:
        state_data = await r.get(f"qb_oauth_state:{state}")
        if not state_data:
            raise HTTPException(400, "Invalid or expired OAuth state")
        await r.delete(f"qb_oauth_state:{state}")
        parsed = json.loads(state_data)
        if parsed.get("role") != "coach":
            raise HTTPException(400, "State mismatch: expected coach")
        coach_username = parsed.get("scope_id")
    elif not state:
        logger.warning("Coach QB callback received without state parameter")
        raise HTTPException(400, "Missing OAuth state parameter")

    if not coach_username:
        raise HTTPException(400, "Could not determine coach from OAuth state")

    auth_header = base64.b64encode(f"{QB_CLIENT_ID}:{QB_CLIENT_SECRET}".encode()).decode()

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
                logger.error("Coach QB token exchange failed: status=%d", resp.status)
                raise HTTPException(502, "QuickBooks token exchange failed")
            tokens = await resp.json()

    expiry = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))
    enc_access = _cipher.encrypt(tokens["access_token"])
    enc_refresh = _cipher.encrypt(tokens["refresh_token"])

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO qb_coach_connection
               (coach_username, realm_id, access_token, refresh_token, token_expiry, connected_by)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (coach_username) DO UPDATE SET
                 realm_id = EXCLUDED.realm_id,
                 access_token = EXCLUDED.access_token,
                 refresh_token = EXCLUDED.refresh_token,
                 token_expiry = EXCLUDED.token_expiry,
                 error_message = NULL,
                 updated_at = NOW()""",
            coach_username, realmId, enc_access, enc_refresh, expiry, coach_username,
        )

    return HTMLResponse(
        """<!DOCTYPE html><html><body style="background:#050505;color:#F5F5F5;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh">
<div style="text-align:center"><h2 style="color:#C9A962">QuickBooks Connected</h2>
<p>Your QuickBooks account is now linked. You may return to the app.</p>
<script>try{window.opener&&window.opener.postMessage({type:'qb_connected'},'*')}catch(e){}</script></div></body></html>"""
    )


# ═══════════════════════════════════════════════════════════════════════════
# Sync Logic — Coaching Revenue + Session Income
# ═══════════════════════════════════════════════════════════════════════════

async def _sync_coaching_revenue(pool, session, token, realm_id, coach_username, hw_id) -> int:
    if not hw_id:
        return 0

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, shared_amount_cents, billing_period_start, billing_period_end,
                      source_note, created_at
               FROM signup_sharing_ledger
               WHERE coach_id = $1 AND status = 'completed'
                 AND synced_to_coach_qb = FALSE
               ORDER BY created_at LIMIT $2""",
            hw_id, BATCH_SIZE,
        )

    synced = 0
    for r in rows:
        receipt_body = {
            "Line": [{
                "Amount": r["shared_amount_cents"] / 100.0,
                "DetailType": "SalesItemLineDetail",
                "SalesItemLineDetail": {"ItemRef": {"name": "Coaching Revenue"}},
                "Description": f"Coaching revenue share — {r['billing_period_start']} to {r['billing_period_end']}",
            }],
            "CustomerRef": {"name": "Sovereign Sanctuary"},
        }
        result = await _qb_api_with_retry(session, "POST", "salesreceipt", token, realm_id, receipt_body)
        async with pool.acquire() as conn:
            if result:
                qb_id = result.get("SalesReceipt", {}).get("Id", "")
                await conn.execute("UPDATE signup_sharing_ledger SET synced_to_coach_qb = TRUE WHERE id = $1", r["id"])
                await _log_sync(conn, coach_username, "coaching_revenue", "signup_sharing_ledger",
                                r["id"], "SalesReceipt", qb_id, r["shared_amount_cents"])
                synced += 1
            else:
                await _log_sync(conn, coach_username, "coaching_revenue", "signup_sharing_ledger",
                                r["id"], "SalesReceipt", "", r["shared_amount_cents"], "failed", "QB API error")
    return synced


async def _sync_session_income(pool, session, token, realm_id, coach_username, hw_id) -> int:
    if not hw_id:
        return 0

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT COUNT(*) as session_count,
                      COALESCE(SUM(EXTRACT(EPOCH FROM (session_end - session_start)) / 3600), 0)::numeric(10,2) as total_hours
               FROM sessions s
               JOIN users u ON u.id = s.user_id
               WHERE s.coach_id = $1
                 AND s.session_end IS NOT NULL
                 AND s.created_at > NOW() - INTERVAL '30 days'""",
            hw_id,
        )

    if not row or row["session_count"] == 0:
        return 0

    receipt_body = {
        "Line": [{
            "Amount": float(row["total_hours"]) * 50.0,
            "DetailType": "SalesItemLineDetail",
            "SalesItemLineDetail": {"ItemRef": {"name": "Session Income"}},
            "Description": f"Coaching sessions (last 30d): {row['session_count']} sessions, {row['total_hours']}h",
        }],
        "CustomerRef": {"name": "Sovereign Sanctuary"},
    }
    result = await _qb_api_with_retry(session, "POST", "salesreceipt", token, realm_id, receipt_body)
    if result:
        logger.info("Coach QB session income synced for %s: %s sessions", coach_username, row["session_count"])
        return 1
    return 0
