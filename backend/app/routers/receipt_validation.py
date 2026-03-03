"""
LITTLE NATE — In-App Purchase Receipt Validation
Validates Apple StoreKit and Google Play Billing receipts server-side,
updates user subscription plans, and logs to skyeye_activity.
"""

import json as _json_mod
import logging
import httpx
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel

from app.services.api_server import get_current_user

logger = logging.getLogger("nate.receipt_validation")

router = APIRouter(prefix="/api/billing", tags=["billing"], dependencies=[Depends(get_current_user)])

APPLE_PRODUCTION_URL = "https://buy.itunes.apple.com/verifyReceipt"
APPLE_SANDBOX_URL = "https://sandbox.itunes.apple.com/verifyReceipt"

PRODUCT_TO_PLAN = {
    "sanctuary_inner_chamber_monthly": "STANDARD",
    "sanctuary_inner_chamber_annual": "STANDARD",
    "sanctuary_sovereign_circle_monthly": "TOP_TIER",
    "sanctuary_sovereign_circle_annual": "TOP_TIER",
    "sanctuary_coaching_single": "COACHING_SINGLE",
    "sanctuary_coaching_4pack": "COACHING_4PACK",
    "sanctuary_coaching_8pack": "COACHING_8PACK",
}

PLAN_TOKEN_ALLOC = {
    "STANDARD": 50_000,
    "TOP_TIER": 200_000,
}


class AppleReceiptRequest(BaseModel):
    receipt_data: str
    user_id: str
    product_id: Optional[str] = None


class GoogleReceiptRequest(BaseModel):
    purchase_token: str
    product_id: str
    user_id: str
    package_name: str = "net.sovereignsanctuary.littlenate"


@router.post("/verify-receipt/apple")
async def verify_apple_receipt(body: AppleReceiptRequest, request: Request):
    """Validate an Apple StoreKit receipt and activate the subscription."""
    import os
    shared_secret = os.getenv("APPLE_SHARED_SECRET", "")

    payload = {
        "receipt-data": body.receipt_data,
        "password": shared_secret,
        "exclude-old-transactions": True,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(APPLE_PRODUCTION_URL, json=payload)
        data = resp.json()

        if data.get("status") == 21007:
            resp = await client.post(APPLE_SANDBOX_URL, json=payload)
            data = resp.json()

    status = data.get("status", -1)
    if status != 0:
        logger.warning("Apple receipt validation failed: status=%d user=%s", status, body.user_id)
        raise HTTPException(status_code=400, detail=f"Receipt validation failed (status {status})")

    latest = data.get("latest_receipt_info", [])
    if not latest:
        latest = data.get("receipt", {}).get("in_app", [])

    active_product = None
    for txn in sorted(latest, key=lambda t: int(t.get("expires_date_ms", "0")), reverse=True):
        expires_ms = int(txn.get("expires_date_ms", "0"))
        if expires_ms > int(datetime.now(timezone.utc).timestamp() * 1000):
            active_product = txn.get("product_id")
            break

    if not active_product and body.product_id:
        active_product = body.product_id

    plan = PRODUCT_TO_PLAN.get(active_product)
    if not plan:
        raise HTTPException(status_code=400, detail=f"Unknown product: {active_product}")

    await _activate_plan(request, body.user_id, plan, "apple", active_product)

    return {"status": "verified", "plan": plan, "product_id": active_product}


@router.post("/verify-receipt/google")
async def verify_google_receipt(body: GoogleReceiptRequest, request: Request):
    """Validate a Google Play Billing purchase and activate the subscription."""
    import os
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    plan = PRODUCT_TO_PLAN.get(body.product_id)
    if not plan:
        raise HTTPException(status_code=400, detail=f"Unknown product: {body.product_id}")

    try:
        creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY", "/app/google-service-account.json")
        credentials = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/androidpublisher"]
        )
        service = build("androidpublisher", "v3", credentials=credentials)

        if "coaching" in body.product_id:
            result = service.purchases().products().get(
                packageName=body.package_name,
                productId=body.product_id,
                token=body.purchase_token,
            ).execute()
            if result.get("purchaseState") != 0:
                raise HTTPException(status_code=400, detail="Purchase not completed")
        else:
            result = service.purchases().subscriptions().get(
                packageName=body.package_name,
                subscriptionId=body.product_id,
                token=body.purchase_token,
            ).execute()
            expiry_ms = int(result.get("expiryTimeMillis", "0"))
            if expiry_ms < int(datetime.now(timezone.utc).timestamp() * 1000):
                raise HTTPException(status_code=400, detail="Subscription expired")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Google receipt validation error: %s", e)
        raise HTTPException(status_code=500, detail="Google verification failed")

    await _activate_plan(request, body.user_id, plan, "google", body.product_id)

    return {"status": "verified", "plan": plan, "product_id": body.product_id}


@router.post("/restore-purchases")
async def restore_purchases(request: Request, user: Dict = Depends(get_current_user)):
    """Restore purchases for the current user — queries active subscriptions."""
    user_id = user.get("user_id", user.get("username", ""))
    pool = request.app.state.db_pool

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT profile_data FROM users WHERE username = $1",
            user_id,
        )

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    profile = row.get("profile_data", {}) or {}
    if isinstance(profile, str):
        import json as _json
        try:
            profile = _json.loads(profile)
        except Exception:
            profile = {}
    return {
        "subscription_plan": profile.get("subscription_plan", "TRIAL"),
        "payment_source": profile.get("payment_source", "unknown"),
        "token_balance": profile.get("token_balance", 0),
    }


async def _activate_plan(request: Request, user_id: str, plan: str,
                         source: str, product_id: str):
    """Update the user's subscription plan in the database."""
    pool = request.app.state.db_pool
    tokens = PLAN_TOKEN_ALLOC.get(plan, 0)

    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET profile_data = profile_data
                || jsonb_build_object(
                    'subscription_plan', $2::text,
                    'payment_source', $3::text,
                    'last_payment_product', $4::text,
                    'last_payment_time', $5::text,
                    'token_balance', COALESCE((profile_data->>'token_balance')::int, 0) + $6
                )
            WHERE username = $1
        """, user_id, plan, source, product_id,
            datetime.now(timezone.utc).isoformat(), tokens)

        await conn.execute("""
            INSERT INTO skyeye_activity (action, platform, details, timestamp)
            VALUES ('iap_receipt_verified', $1, $2, NOW())
        """, source, f"user={user_id} plan={plan} product={product_id}")

        new_balance = await conn.fetchval(
            "SELECT COALESCE((profile_data->>'token_balance')::int, 0) FROM users WHERE username = $1",
            user_id,
        )

    try:
        from app.services.api_server import _get_auth_redis
        r = await _get_auth_redis()
        if r and new_balance is not None:
            await r.publish(
                "nate:balance_sync",
                _json_mod.dumps({"username": user_id, "token_balance": int(new_balance)}),
            )
    except Exception as e:
        logger.warning("Balance sync publish failed for %s: %s", user_id, e)

    logger.info("IAP activated: user=%s plan=%s source=%s product=%s", user_id, plan, source, product_id)
