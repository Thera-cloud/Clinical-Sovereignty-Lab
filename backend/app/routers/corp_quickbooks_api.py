"""Corp QuickBooks API — company-scoped QB Online sync for Corp_Admins.

Two routers exported:
  - router        (auth-gated, require_corp_admin)
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
    from app.services.api_server import _get_auth_redis
    from app.routers.corporate_command_api import require_corp_admin, _get_company_id
except ImportError:
    from backend.app.services.api_server import _get_auth_redis
    from backend.app.routers.corporate_command_api import require_corp_admin, _get_company_id

try:
    from app.services.skyeye_platform_base import TokenCipher
except ImportError:
    from backend.app.services.skyeye_platform_base import TokenCipher

router = APIRouter(
    prefix="/api/corp/quickbooks",
    tags=["corp-quickbooks"],
    dependencies=[Depends(require_corp_admin)],
)

oauth_router = APIRouter(
    prefix="/api/corp/quickbooks",
    tags=["corp-quickbooks-oauth"],
)

QB_CLIENT_ID = os.getenv("QB_CLIENT_ID", "")
QB_CLIENT_SECRET = os.getenv("QB_CLIENT_SECRET", "")
QB_ENVIRONMENT = os.getenv("QB_ENVIRONMENT", "sandbox")
QB_REDIRECT_URI = os.getenv(
    "QB_CORP_REDIRECT_URI",
    "https://api.sovereignsanctuary.net/api/corp/quickbooks/callback",
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


class CorpAccountMappingRequest(BaseModel):
    internal_category: str
    qb_account_id: str
    qb_account_name: Optional[str] = None


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
            logger.warning("Corp QB API %s %s → %d", method, path, resp.status)
            return None
    except Exception as e:
        logger.warning("Corp QB API %s %s error: %s", method, path, e)
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


async def _ensure_valid_token(pool, company_id: str) -> tuple:
    """Returns (access_token, realm_id) or raises."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM qb_corp_connection WHERE company_id = $1::uuid", company_id
        )
    if not row:
        raise HTTPException(400, "No QuickBooks connection for this company")

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
                    logger.error("Corp QB token refresh failed: status=%d", resp.status)
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE qb_corp_connection SET error_message = $1 WHERE company_id = $2::uuid",
                            f"Token refresh failed: {resp.status}", company_id,
                        )
                    raise HTTPException(502, "QB token refresh failed")
                tokens = await resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Corp QB token refresh exception: %s", e)
        raise HTTPException(502, "QB token refresh error")

    new_expiry = now + timedelta(seconds=tokens.get("expires_in", 3600))
    enc_access = _cipher.encrypt(tokens["access_token"])
    enc_refresh = _cipher.encrypt(tokens.get("refresh_token", refresh_token))

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE qb_corp_connection SET
                 access_token = $1, refresh_token = $2,
                 token_expiry = $3, error_message = NULL, updated_at = NOW()
               WHERE company_id = $4::uuid""",
            enc_access, enc_refresh, new_expiry, company_id,
        )
    return tokens["access_token"], row["realm_id"]


async def _log_sync(conn, company_id, sync_type, source_table, source_id,
                     qb_entity_type, qb_entity_id, amount_cents,
                     status="synced", error_message=None):
    await conn.execute(
        """INSERT INTO qb_corp_sync_log
           (company_id, sync_type, source_table, source_id, qb_entity_type,
            qb_entity_id, amount_cents, status, error_message)
           VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9)""",
        company_id, sync_type, source_table, source_id, qb_entity_type,
        qb_entity_id or "", amount_cents, status, error_message,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Auth-gated endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/health")
async def corp_qb_health():
    return {"status": "ok", "service": "corp_quickbooks"}


@router.get("/connect")
async def corp_qb_connect(request: Request, user: Dict = Depends(require_corp_admin)):
    """Generate OAuth URL with CSRF state token scoped to company."""
    if not QB_CLIENT_ID:
        raise HTTPException(503, "QB_CLIENT_ID not configured")

    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    _check_rate(user.get("username", "unknown"), "auth", MAX_AUTH_PER_HOUR)

    state_token = secrets.token_urlsafe(32)
    r = await _get_auth_redis()
    if r:
        await r.setex(
            f"qb_oauth_state:{state_token}",
            300,
            json.dumps({"role": "corp_admin", "scope_id": company_id}),
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
async def corp_qb_status(request: Request, user: Dict = Depends(require_corp_admin)):
    """Connection status for this company's QB link."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM qb_corp_connection WHERE company_id = $1::uuid", company_id
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
async def corp_qb_disconnect(request: Request, user: Dict = Depends(require_corp_admin)):
    """Revoke tokens and delete company QB connection."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    _check_rate(user.get("username", "unknown"), "auth", MAX_AUTH_PER_HOUR)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT refresh_token FROM qb_corp_connection WHERE company_id = $1::uuid",
            company_id,
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
                logger.warning("Corp QB revoke failed (non-fatal): %s", e)

        await conn.execute(
            "DELETE FROM qb_corp_connection WHERE company_id = $1::uuid", company_id
        )

    return {"status": "disconnected"}


@router.post("/sync/trigger")
async def corp_qb_sync_trigger(request: Request, user: Dict = Depends(require_corp_admin)):
    """Trigger on-demand sync for this company."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    _check_rate(user.get("username", "unknown"), "sync", MAX_SYNC_PER_HOUR)

    access_token, realm_id = await _ensure_valid_token(pool, company_id)

    totals = {"employee_subscriptions": 0, "employee_tokens": 0, "corporate_billing": 0}
    async with aiohttp.ClientSession() as session:
        totals["employee_subscriptions"] = await _sync_employee_subs(pool, session, access_token, realm_id, company_id)
        totals["employee_tokens"] = await _sync_employee_tokens(pool, session, access_token, realm_id, company_id)
        totals["corporate_billing"] = await _sync_corp_billing(pool, session, access_token, realm_id, company_id)

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE qb_corp_connection SET last_sync_at = $1, error_message = NULL, updated_at = NOW() WHERE company_id = $2::uuid",
            datetime.now(timezone.utc), company_id,
        )

    r = await _get_auth_redis()
    if r:
        usernames = []
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT username FROM users WHERE company_id = $1::uuid AND role = 'CLIENT' LIMIT 100",
                company_id,
            )
            usernames = [row["username"] for row in rows]
        for uname in usernames[:20]:
            try:
                await r.publish("nate:user_reload", json.dumps({"username": uname}))
            except Exception:
                pass

    total_synced = sum(totals.values())
    logger.info("Corp QB sync complete for company %s — %d records", company_id[:8], total_synced)
    return {"status": "sync_complete", "totals": totals, "total_synced": total_synced}


@router.get("/sync/history")
async def corp_qb_sync_history(request: Request, user: Dict = Depends(require_corp_admin), limit: int = 50):
    """Sync log for this company."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, sync_type, source_table, source_id, qb_entity_type,
                      qb_entity_id, amount_cents, status, error_message, created_at
               FROM qb_corp_sync_log WHERE company_id = $1::uuid
               ORDER BY created_at DESC LIMIT $2""",
            company_id, limit,
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
async def corp_qb_get_mapping(request: Request, user: Dict = Depends(require_corp_admin)):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM qb_corp_account_mapping WHERE company_id = $1::uuid ORDER BY internal_category",
            company_id,
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
async def corp_qb_set_mapping(req: CorpAccountMappingRequest, request: Request,
                               user: Dict = Depends(require_corp_admin)):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    valid = ["employee_subscriptions", "employee_tokens", "corporate_billing"]
    if req.internal_category not in valid:
        raise HTTPException(400, f"internal_category must be one of: {valid}")

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO qb_corp_account_mapping (company_id, internal_category, qb_account_id, qb_account_name)
               VALUES ($1::uuid, $2, $3, $4)
               ON CONFLICT (company_id, internal_category) DO UPDATE SET
                 qb_account_id = EXCLUDED.qb_account_id,
                 qb_account_name = EXCLUDED.qb_account_name,
                 updated_at = NOW()""",
            company_id, req.internal_category, req.qb_account_id, req.qb_account_name or "",
        )

    return {"status": "ok", "category": req.internal_category, "qb_account_id": req.qb_account_id}


# ═══════════════════════════════════════════════════════════════════════════
# Public OAuth callback (no auth)
# ═══════════════════════════════════════════════════════════════════════════

@oauth_router.get("/callback")
async def corp_qb_callback(code: str, realmId: str, request: Request, state: str = ""):
    """Exchange code for tokens, validate CSRF state, encrypt and store."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    if not QB_CLIENT_ID or not QB_CLIENT_SECRET:
        raise HTTPException(503, "QB credentials not configured")

    r = await _get_auth_redis()
    company_id = None
    if r and state:
        state_data = await r.get(f"qb_oauth_state:{state}")
        if not state_data:
            raise HTTPException(400, "Invalid or expired OAuth state")
        await r.delete(f"qb_oauth_state:{state}")
        parsed = json.loads(state_data)
        if parsed.get("role") != "corp_admin":
            raise HTTPException(400, "State mismatch: expected corp_admin")
        company_id = parsed.get("scope_id")
    elif not state:
        logger.warning("Corp QB callback received without state parameter")
        raise HTTPException(400, "Missing OAuth state parameter")

    if not company_id:
        raise HTTPException(400, "Could not determine company from OAuth state")

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
                logger.error("Corp QB token exchange failed: status=%d", resp.status)
                raise HTTPException(502, "QuickBooks token exchange failed")
            tokens = await resp.json()

    expiry = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))
    enc_access = _cipher.encrypt(tokens["access_token"])
    enc_refresh = _cipher.encrypt(tokens["refresh_token"])

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO qb_corp_connection
               (company_id, realm_id, access_token, refresh_token, token_expiry, connected_by)
               VALUES ($1::uuid, $2, $3, $4, $5, $6)
               ON CONFLICT (company_id) DO UPDATE SET
                 realm_id = EXCLUDED.realm_id,
                 access_token = EXCLUDED.access_token,
                 refresh_token = EXCLUDED.refresh_token,
                 token_expiry = EXCLUDED.token_expiry,
                 error_message = NULL,
                 updated_at = NOW()""",
            company_id, realmId, enc_access, enc_refresh, expiry, "corp_admin",
        )

    return HTMLResponse(
        """<!DOCTYPE html><html><body style="background:#050505;color:#F5F5F5;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh">
<div style="text-align:center"><h2 style="color:#C9A962">QuickBooks Connected</h2>
<p>Your company's QuickBooks is now linked. You may close this tab.</p>
<a href="/corporate_command.html#quickbooks" style="color:#C9A962;margin-top:16px;display:inline-block">Return to Corporate Command</a>
<script>try{window.opener&&window.opener.postMessage({type:'qb_connected'},'*')}catch(e){}</script></div></body></html>"""
    )


# ═══════════════════════════════════════════════════════════════════════════
# Sync Logic — Employee Subscriptions, Token Purchases, Corporate Billing
# ═══════════════════════════════════════════════════════════════════════════

async def _sync_employee_subs(pool, session, token, realm_id, company_id) -> int:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ph.id, ph.username, ph.amount_cents, ph.status, ph.created_at
               FROM payment_history ph
               JOIN users u ON u.username = ph.username
               WHERE u.company_id = $1::uuid AND u.role = 'CLIENT'
                 AND ph.synced_to_corp_qb = FALSE AND ph.status = 'PAID'
               ORDER BY ph.created_at LIMIT $2""",
            company_id, BATCH_SIZE,
        )

    synced = 0
    for r in rows:
        invoice_body = {
            "Line": [{
                "Amount": r["amount_cents"] / 100.0,
                "DetailType": "SalesItemLineDetail",
                "SalesItemLineDetail": {"ItemRef": {"name": "Employee Subscription"}},
                "Description": f"Subscription — {r['username']}",
            }],
            "CustomerRef": {"name": r["username"]},
        }
        result = await _qb_api_with_retry(session, "POST", "invoice", token, realm_id, invoice_body)
        async with pool.acquire() as conn:
            if result:
                qb_id = result.get("Invoice", {}).get("Id", "")
                await conn.execute("UPDATE payment_history SET synced_to_corp_qb = TRUE WHERE id = $1", r["id"])
                await _log_sync(conn, company_id, "employee_subscription", "payment_history",
                                r["id"], "Invoice", qb_id, r["amount_cents"])
                synced += 1
            else:
                await _log_sync(conn, company_id, "employee_subscription", "payment_history",
                                r["id"], "Invoice", "", r["amount_cents"], "failed", "QB API error")
    return synced


async def _sync_employee_tokens(pool, session, token, realm_id, company_id) -> int:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT tt.id, tt.username, tt.amount, tt.created_at
               FROM token_transactions tt
               JOIN users u ON u.username = tt.username
               WHERE u.company_id = $1::uuid AND u.role = 'CLIENT'
                 AND tt.synced_to_corp_qb = FALSE AND tt.action = 'purchase' AND tt.source = 'token_pack'
               ORDER BY tt.created_at LIMIT $2""",
            company_id, BATCH_SIZE,
        )

    synced = 0
    packs = {15000: 300, 50000: 700, 150000: 2000, 1000000: 12500}
    for r in rows:
        price_cents = packs.get(r["amount"], 0)
        if not price_cents:
            continue
        receipt_body = {
            "Line": [{
                "Amount": price_cents / 100.0,
                "DetailType": "SalesItemLineDetail",
                "SalesItemLineDetail": {"ItemRef": {"name": "Token Pack"}},
                "Description": f"Token Pack ({r['amount']} tokens) — {r['username']}",
            }],
            "CustomerRef": {"name": r["username"]},
        }
        result = await _qb_api_with_retry(session, "POST", "salesreceipt", token, realm_id, receipt_body)
        async with pool.acquire() as conn:
            if result:
                qb_id = result.get("SalesReceipt", {}).get("Id", "")
                await conn.execute("UPDATE token_transactions SET synced_to_corp_qb = TRUE WHERE id = $1", r["id"])
                await _log_sync(conn, company_id, "employee_token_purchase", "token_transactions",
                                r["id"], "SalesReceipt", qb_id, price_cents)
                synced += 1
            else:
                await _log_sync(conn, company_id, "employee_token_purchase", "token_transactions",
                                r["id"], "SalesReceipt", "", price_cents, "failed", "QB API error")
    return synced


async def _sync_corp_billing(pool, session, token, realm_id, company_id) -> int:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ph.id, ph.amount_cents, ph.created_at, cs.company_name
               FROM payment_history ph
               JOIN corporate_enrollments ce ON ce.user_id = (
                   SELECT id FROM users WHERE username = ph.username LIMIT 1
               )
               JOIN corporate_sponsors cs ON cs.id = ce.sponsor_id
               WHERE cs.id = $1::uuid AND cs.pays_full = TRUE
                 AND ph.synced_to_corp_qb = FALSE AND ph.status = 'PAID'
               ORDER BY ph.created_at LIMIT $2""",
            company_id, BATCH_SIZE,
        )

    synced = 0
    for r in rows:
        invoice_body = {
            "Line": [{
                "Amount": r["amount_cents"] / 100.0,
                "DetailType": "SalesItemLineDetail",
                "SalesItemLineDetail": {"ItemRef": {"name": "Corporate Billing"}},
                "Description": f"Corporate enrollment — {r['company_name']}",
            }],
            "CustomerRef": {"name": r["company_name"]},
        }
        result = await _qb_api_with_retry(session, "POST", "invoice", token, realm_id, invoice_body)
        async with pool.acquire() as conn:
            if result:
                qb_id = result.get("Invoice", {}).get("Id", "")
                await conn.execute("UPDATE payment_history SET synced_to_corp_qb = TRUE WHERE id = $1", r["id"])
                await _log_sync(conn, company_id, "corporate_billing", "payment_history",
                                r["id"], "Invoice", qb_id, r["amount_cents"])
                synced += 1
            else:
                await _log_sync(conn, company_id, "corporate_billing", "payment_history",
                                r["id"], "Invoice", "", r["amount_cents"], "failed", "QB API error")
    return synced
