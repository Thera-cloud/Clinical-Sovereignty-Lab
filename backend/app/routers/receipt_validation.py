"""
LITTLE NATE — In-App Purchase Receipt Validation
Validates Apple StoreKit and Google Play Billing receipts server-side,
updates user subscription plans, and logs to skyeye_activity.
"""

import json as _json_mod
import logging
import asyncio
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
    # Current app-store style IDs
    "net.sovereignsanctuary.inner_chamber_monthly": "STANDARD",
    "net.sovereignsanctuary.inner_chamber_annual": "STANDARD",
    "net.sovereignsanctuary.sovereign_circle_monthly": "TOP_TIER",
    "net.sovereignsanctuary.sovereign_circle_annual": "TOP_TIER",
    # Legacy IDs (kept for backward compatibility)
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

CONSUMABLE_PRODUCTS = {
    "net.sovereignsanctuary.token_light3": {"tokens": 15000, "type": "token_pack"},
    "net.sovereignsanctuary.token_standard7": {"tokens": 50000, "type": "token_pack"},
    "net.sovereignsanctuary.token_power": {"tokens": 150000, "type": "token_pack"},
    "net.sovereignsanctuary.token_ultimate": {"tokens": 1000000, "type": "token_pack"},
    "net.sovereignsanctuary.sanctuary_charge_base_fee": {"amount_cents": 2000, "type": "sanctuary_charge"},
    "net.sovereignsanctuary.sanctuary_charge_assisted_response": {"amount_cents": 300, "type": "sanctuary_charge"},
    "net.sovereignsanctuary.sanctuary_charge_group_coaching": {"amount_cents": 2000, "type": "sanctuary_charge"},
    "net.sovereignsanctuary.sanctuary_charge_individual_coaching": {"amount_cents": 500, "type": "sanctuary_charge"},
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


async def _post_apple_verify(client: httpx.AsyncClient, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Call Apple verify endpoint with retries for transient network outages."""
    attempts = 3
    for idx in range(1, attempts + 1):
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
        except (httpx.TransportError, httpx.TimeoutException) as e:
            if idx >= attempts:
                logger.error("Apple verify endpoint unavailable after %d attempts (%s): %s", attempts, url, e)
                raise HTTPException(
                    status_code=503,
                    detail="Apple receipt verification temporarily unavailable. Please retry restore purchases.",
                )
            await asyncio.sleep(0.5 * idx)
        except httpx.HTTPStatusError as e:
            logger.error("Apple verify returned HTTP %d (%s): %s", e.response.status_code, url, e)
            raise HTTPException(
                status_code=502,
                detail=f"Apple verification returned {e.response.status_code}",
            )


@router.post("/verify-receipt/apple")
async def verify_apple_receipt(body: AppleReceiptRequest, request: Request,
                               current_user: Dict = Depends(get_current_user)):
    """Validate an Apple StoreKit receipt and activate the subscription."""
    auth_uid = current_user.get("user_id", current_user.get("username", ""))
    if body.user_id and body.user_id != auth_uid:
        logger.warning("Apple receipt user_id mismatch: body=%s auth=%s", body.user_id, auth_uid)
        raise HTTPException(status_code=403, detail="user_id does not match authenticated user")
    effective_user_id = auth_uid or body.user_id

    import os
    shared_secret = os.getenv("APPLE_SHARED_SECRET", "")

    payload = {
        "receipt-data": body.receipt_data,
        "password": shared_secret,
        "exclude-old-transactions": True,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        data = await _post_apple_verify(client, APPLE_PRODUCTION_URL, payload)
        if data.get("status") == 21007:
            data = await _post_apple_verify(client, APPLE_SANDBOX_URL, payload)

    status = data.get("status", -1)
    if status != 0:
        logger.warning("Apple receipt validation failed: status=%d user=%s", status, effective_user_id)
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

    if not active_product:
        for txn in latest:
            pid = txn.get("product_id", "")
            if pid in CONSUMABLE_PRODUCTS:
                active_product = pid
                break

    consumable = CONSUMABLE_PRODUCTS.get(active_product)
    if consumable:
        await _credit_consumable(request, effective_user_id, active_product, consumable, "apple")
        return {"status": "verified", "type": consumable["type"], "product_id": active_product}

    plan = PRODUCT_TO_PLAN.get(active_product)
    if not plan:
        raise HTTPException(status_code=400, detail=f"Unknown product: {active_product}")

    await _activate_plan(request, effective_user_id, plan, "apple", active_product)

    return {"status": "verified", "plan": plan, "product_id": active_product}


@router.post("/verify-receipt/google")
async def verify_google_receipt(body: GoogleReceiptRequest, request: Request,
                                current_user: Dict = Depends(get_current_user)):
    """Validate a Google Play Billing purchase and activate the subscription."""
    auth_uid = current_user.get("user_id", current_user.get("username", ""))
    if body.user_id and body.user_id != auth_uid:
        logger.warning("Google receipt user_id mismatch: body=%s auth=%s", body.user_id, auth_uid)
        raise HTTPException(status_code=403, detail="user_id does not match authenticated user")
    effective_user_id = auth_uid or body.user_id

    import os
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    consumable = CONSUMABLE_PRODUCTS.get(body.product_id)
    plan = PRODUCT_TO_PLAN.get(body.product_id)
    if not plan and not consumable:
        raise HTTPException(status_code=400, detail=f"Unknown product: {body.product_id}")

    try:
        creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY", "/app/google-service-account.json")
        credentials = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/androidpublisher"]
        )
        service = build("androidpublisher", "v3", credentials=credentials)

        is_one_time = consumable is not None or "coaching" in body.product_id
        if is_one_time:
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

    if consumable:
        await _credit_consumable(request, effective_user_id, body.product_id, consumable, "google")
        return {"status": "verified", "type": consumable["type"], "product_id": body.product_id}

    await _activate_plan(request, effective_user_id, plan, "google", body.product_id)

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


async def _credit_consumable(request: Request, user_id: str,
                             product_id: str, consumable: Dict[str, Any],
                             source: str):
    """Credit tokens or record a sanctuary charge for a consumable IAP."""
    pool = request.app.state.db_pool

    if consumable["type"] == "token_pack":
        tokens = consumable["tokens"]
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE users SET
                    token_balance = COALESCE(token_balance, 0) + $2,
                    profile_data = jsonb_set(
                        profile_data,
                        '{token_balance}',
                        to_jsonb((COALESCE((profile_data->>'token_balance')::int, 0) + $2)::int)
                    )
                WHERE username = $1
            """, user_id, tokens)

            await conn.execute("""
                INSERT INTO token_transactions (username, action, amount, balance_before, balance_after, source, created_at)
                SELECT $1, 'credit', $2,
                    COALESCE((profile_data->>'token_balance')::int, 0) - $2,
                    COALESCE((profile_data->>'token_balance')::int, 0),
                    'iap_token_pack', NOW()
                FROM users WHERE username = $1
            """, user_id, tokens)

            await conn.execute("""
                INSERT INTO skyeye_activity (type, platform, content, created_at)
                VALUES ('iap_consumable_credited', $1, $2, NOW())
            """, source, f"user={user_id} tokens={tokens} product={product_id}")

        logger.info("IAP token pack credited: user=%s tokens=%d product=%s source=%s",
                     user_id, tokens, product_id, source)

    elif consumable["type"] == "sanctuary_charge":
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO payment_history (user_id, amount_cents, payment_type, product_id, source, status, created_at)
                SELECT id, $2, 'sanctuary_charge', $3, $4, 'completed', NOW()
                FROM users WHERE username = $1
            """, user_id, consumable["amount_cents"], product_id, source)

            await conn.execute("""
                INSERT INTO skyeye_activity (type, platform, content, created_at)
                VALUES ('iap_consumable_credited', $1, $2, NOW())
            """, source, f"user={user_id} charge_cents={consumable['amount_cents']} product={product_id}")

        logger.info("IAP sanctuary charge recorded: user=%s cents=%d product=%s source=%s",
                     user_id, consumable["amount_cents"], product_id, source)


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
            INSERT INTO skyeye_activity (type, platform, content, created_at)
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
