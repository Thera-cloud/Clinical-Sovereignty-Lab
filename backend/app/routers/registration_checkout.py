"""
Stripe checkout endpoints for registration and coach upgrades.
"""
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Dict, List, Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

try:
    from app.services.api_server import get_current_user
except ImportError:
    get_current_user = None

logger = logging.getLogger(__name__)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

PRICES = {
    "STANDARD": os.getenv("STRIPE_PRICE_STANDARD"),
    "TOP_TIER": os.getenv("STRIPE_PRICE_TOP_TIER"),
    "INNER_CHAMBER_ANNUAL": os.getenv("STRIPE_PRICE_INNER_CHAMBER_ANNUAL"),
    "SOVEREIGN_CIRCLE_ANNUAL": os.getenv("STRIPE_PRICE_SOVEREIGN_CIRCLE_ANNUAL"),
    "DOJO_THERAPIST": os.getenv("STRIPE_PRICE_DOJO_THERAPIST"),
    "DOJO_PROJECT_PM": os.getenv("STRIPE_PRICE_DOJO_PROJECT_PM"),
    "DOJO_BUSINESS": os.getenv("STRIPE_PRICE_DOJO_BUSINESS"),
    "DOJO_CNC": os.getenv("STRIPE_PRICE_DOJO_CNC"),
    "DOJO_MCAT": os.getenv("STRIPE_PRICE_DOJO_MCAT"),
    "DOJO_TEACHER": os.getenv("STRIPE_PRICE_DOJO_TEACHER"),
    "DOJO_JUDGE": os.getenv("STRIPE_PRICE_DOJO_JUDGE"),
    "DOJO_COACH_NATE": os.getenv("STRIPE_PRICE_DOJO_COACH_NATE"),
}

DOJO_PRICES_CENTS = {
    "therapist": 17500, "project_pm": 25000, "business": 32500,
    "cnc": 15000, "mcat": 50000, "teacher": 22500, "judge": 210000,
    "coach_nate": 9000,
}

SUCCESS_URL = os.getenv(
    "REGISTRATION_SUCCESS_URL",
    "https://app.sovereignsanctuary.net/?registration=success&session_id={CHECKOUT_SESSION_ID}",
)
CANCEL_URL = os.getenv(
    "REGISTRATION_CANCEL_URL",
    "https://app.sovereignsanctuary.net/?registration=cancel",
)

# Rate limiting: 5 req/min per IP
_rate_limits: Dict[str, List[float]] = {}
_RATE_WINDOW = 60
_RATE_MAX = 5


def _rate_check(ip: str) -> bool:
    now = time.time()
    window = _rate_limits.setdefault(ip, [])
    _rate_limits[ip] = [t for t in window if now - t < _RATE_WINDOW]
    if len(_rate_limits[ip]) >= _RATE_MAX:
        return True
    _rate_limits[ip].append(now)
    return False


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    result = f"{salt}:{hashed.hex()}"
    check_salt, check_hash = result.split(":")
    rehash = hashlib.pbkdf2_hmac("sha256", password.encode(), check_salt.encode(), 100000)
    if not hmac.compare_digest(rehash.hex(), check_hash):
        salt = secrets.token_hex(16)
        hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
        result = f"{salt}:{hashed.hex()}"
    return result


public_router = APIRouter(
    prefix="/api/registration",
    tags=["registration-public"],
)


class PrepareRequest(BaseModel):
    role: str
    username: str
    password: str
    email: Optional[str] = ""
    name: str
    dob: Optional[str] = None
    consent_version: str = "v13.0_2026"
    consent_agreed: bool = True
    tier: Optional[str] = None
    billing_cycle: str = "monthly"
    selected_dojos: Optional[List[str]] = None
    discount_code: Optional[str] = None
    profile_fields: Optional[dict] = None
    # Coach upgrade fields
    flow: Optional[str] = None
    auth_token: Optional[str] = None


@public_router.post("/checkout/prepare")
async def prepare_checkout(body: PrepareRequest, request: Request):
    """Create a pending signup and Stripe Checkout session."""
    client_ip = request.client.host if request.client else "unknown"
    if _rate_check(client_ip):
        raise HTTPException(429, "Too many registration attempts. Please try again shortly.")

    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Service temporarily unavailable")

    email = (body.email or "").strip().lower()
    username = body.username.strip()
    role = body.role.upper()

    if role not in ("CLIENT", "COACH"):
        raise HTTPException(400, "Invalid role")
    if not username or len(username) < 3:
        raise HTTPException(400, "Username must be at least 3 characters")
    if not body.password or len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    async with db_pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM users WHERE LOWER(username) = LOWER($1)", username
        )
        if exists:
            raise HTTPException(409, "Username is already taken")

        pending = await conn.fetchval(
            "SELECT id FROM pending_signups WHERE LOWER(username) = LOWER($1) "
            "AND status = 'pending' AND expires_at > NOW()",
            username,
        )

    password_hash = _hash_password(body.password)

    profile_fields = body.profile_fields or {}
    profile_fields["name"] = body.name
    profile_fields["email"] = email
    profile_fields["dob"] = body.dob
    profile_fields["consent_version"] = body.consent_version

    # Build Stripe line_items
    line_items = []
    pricing_snapshot = {}

    if role == "CLIENT":
        tier = (body.tier or "STANDARD").upper()
        if body.billing_cycle == "annual":
            price_key = "INNER_CHAMBER_ANNUAL" if tier == "STANDARD" else "SOVEREIGN_CIRCLE_ANNUAL"
        else:
            price_key = tier
        price_id = PRICES.get(price_key)
        if not price_id:
            raise HTTPException(400, f"No Stripe price configured for {price_key}")
        line_items.append({"price": price_id, "quantity": 1})
        pricing_snapshot = {
            "tier": tier,
            "billing_cycle": body.billing_cycle,
            "price_key": price_key,
        }
    else:
        dojos = body.selected_dojos or []
        if not dojos:
            raise HTTPException(400, "At least one DOJO must be selected")
        for dojo in dojos:
            dojo_key = f"DOJO_{dojo.upper()}"
            price_id = PRICES.get(dojo_key)
            if not price_id:
                raise HTTPException(400, f"No Stripe price configured for DOJO {dojo}")
            line_items.append({"price": price_id, "quantity": 1})
        pricing_snapshot = {
            "selected_dojos": dojos,
            "dojo_prices": {d: DOJO_PRICES_CENTS.get(d, 0) for d in dojos},
        }

    # Discount handling
    discounts = []
    if body.discount_code:
        try:
            async with db_pool.acquire() as conn:
                disc = await conn.fetchrow(
                    "SELECT discount_type, discount_value, stripe_coupon_id "
                    "FROM promotional_specials WHERE code = $1 AND active = true "
                    "AND (expires_at IS NULL OR expires_at > NOW())",
                    body.discount_code.strip().upper(),
                )
                if disc and disc["stripe_coupon_id"]:
                    discounts = [{"coupon": disc["stripe_coupon_id"]}]
                    pricing_snapshot["discount_code"] = body.discount_code
                    pricing_snapshot["discount_type"] = disc["discount_type"]
                    pricing_snapshot["discount_value"] = float(disc["discount_value"] or 0)
        except Exception as e:
            logger.warning("Discount lookup failed for %s: %s", body.discount_code, e)

    # Create pending_signup row first so we have the ID for Stripe metadata
    try:
        async with db_pool.acquire() as conn:
            if pending:
                await conn.execute(
                    """
                    UPDATE pending_signups
                    SET password_hash = $2, email = $3, payload = $4::jsonb,
                        tier = $5, selected_dojos = $6::jsonb,
                        discount_code = $7, pricing_snapshot = $8::jsonb,
                        expires_at = NOW() + INTERVAL '2 hours',
                        created_at = NOW()
                    WHERE id = $1
                    """,
                    pending,
                    password_hash,
                    email,
                    json.dumps(profile_fields),
                    body.tier,
                    json.dumps(body.selected_dojos or []),
                    body.discount_code,
                    json.dumps(pricing_snapshot),
                )
                signup_id = str(pending)
            else:
                row = await conn.fetchrow(
                    """
                    INSERT INTO pending_signups
                        (role, username, password_hash, email, payload, tier,
                         selected_dojos, discount_code, pricing_snapshot)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7::jsonb, $8, $9::jsonb)
                    RETURNING id
                    """,
                    role,
                    username,
                    password_hash,
                    email,
                    json.dumps(profile_fields),
                    body.tier,
                    json.dumps(body.selected_dojos or []),
                    body.discount_code,
                    json.dumps(pricing_snapshot),
                )
                signup_id = str(row["id"])
    except Exception as e:
        logger.error("pending_signups INSERT failed: %s", e)
        raise HTTPException(500, "Registration setup failed")

    # Create Stripe Checkout Session with signup_id already in metadata
    try:
        session_params = {
            "mode": "subscription",
            "payment_method_types": ["card"],
            "line_items": line_items,
            "success_url": SUCCESS_URL,
            "cancel_url": CANCEL_URL,
            "metadata": {
                "type": "pending_signup",
                "pending_signup_id": signup_id,
            },
        }
        if discounts:
            session_params["discounts"] = discounts

        checkout_session = stripe.checkout.Session.create(**session_params)
    except stripe.error.StripeError as e:
        logger.error("Stripe Checkout creation failed: %s", e)
        raise HTTPException(502, "Payment service unavailable")

    # Link the Stripe session ID back to the pending row
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE pending_signups SET stripe_checkout_session_id = $1 WHERE id = $2::uuid",
                checkout_session.id,
                signup_id,
            )
    except Exception as e:
        logger.warning("Failed to link Stripe session to pending_signup: %s", e)

    return {
        "checkout_url": checkout_session.url,
        "pricing_snapshot": pricing_snapshot,
        "session_id": checkout_session.id,
    }


# ---- Authenticated endpoint for client -> coach upgrade ---- # QUANTUM-CRYSTAL-ARCH
upgrade_router = APIRouter(prefix="/api/registration", tags=["registration"])


class UpgradeRequest(BaseModel):
    selected_dojos: List[str]
    coaching_fee: Optional[float] = None
    zoom_link: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


@upgrade_router.post("/checkout/coach-upgrade")
async def coach_upgrade_checkout(
    body: UpgradeRequest,
    request: Request,
    user: dict = Depends(get_current_user) if get_current_user else None,
):
    if not user:
        raise HTTPException(401, "Authentication required")

    username = user.get("username", "")
    hw_id = user.get("hardware_id", "")
    if not username:
        raise HTTPException(400, "Username not found in session")

    if not body.selected_dojos:
        raise HTTPException(400, "At least one DOJO must be selected")

    for d in body.selected_dojos:
        key = f"DOJO_{d.upper()}"
        if key not in PRICES and d.upper() not in [k.replace("DOJO_", "") for k in PRICES if k.startswith("DOJO_")]:
            raise HTTPException(400, f"Unknown DOJO: {d}")

    line_items = []
    monthly_total_cents = 0
    for dojo in body.selected_dojos:
        price_key = f"DOJO_{dojo.upper()}"
        stripe_price = PRICES.get(price_key)
        cents = DOJO_PRICES_CENTS.get(dojo, 0)
        monthly_total_cents += cents
        if stripe_price:
            line_items.append({"price": stripe_price, "quantity": 1})
        else:
            label = dojo.replace("_", " ").title()
            line_items.append({
                "price_data": {
                    "currency": "usd",
                    "unit_amount": cents,
                    "recurring": {"interval": "month"},
                    "product_data": {"name": f"DOJO: {label}"},
                },
                "quantity": 1,
            })

    success_url = os.getenv(
        "UPGRADE_SUCCESS_URL",
        "https://app.sovereignsanctuary.net/?upgrade=success",
    )
    cancel_url = os.getenv(
        "UPGRADE_CANCEL_URL",
        "https://app.sovereignsanctuary.net/?upgrade=cancel",
    )

    try:
        checkout_session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=line_items,
            success_url=success_url,
            cancel_url=cancel_url,
            expires_at=int(time.time()) + 7200,
            metadata={
                "type": "coach_upgrade",
                "username": username,
                "hardware_id": hw_id,
                "selected_dojos": json.dumps(body.selected_dojos),
                "coaching_fee": str(body.coaching_fee or 0),
                "zoom_link": body.zoom_link or "",
                "email": body.email or "",
                "phone": body.phone or "",
            },
        )
    except stripe.error.StripeError as e:
        logger.error("Coach upgrade Stripe session failed: %s", e)
        raise HTTPException(502, "Payment provider error")

    return {
        "checkout_url": checkout_session.url,
        "session_id": checkout_session.id,
        "monthly_total_cents": monthly_total_cents,
    }
