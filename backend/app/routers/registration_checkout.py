"""
Stripe checkout endpoints for registration and coach upgrades.
"""
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from typing import Any, Dict, List, Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.services.trial_signup_redis_keys import trial_contact_key, trial_signup_session_key

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
    # Family-plan add-on prices (paid dependents under Sovereign Circle).
    # Cents: $75 / $60 / $45 / $30 — see family_tier_price_cents().
    "FAMILY_TIER_1": os.getenv("STRIPE_PRICE_FAMILY_TIER_1"),
    "FAMILY_TIER_2": os.getenv("STRIPE_PRICE_FAMILY_TIER_2"),
    "FAMILY_TIER_3": os.getenv("STRIPE_PRICE_FAMILY_TIER_3"),
    "FAMILY_TIER_4": os.getenv("STRIPE_PRICE_FAMILY_TIER_4"),
}

DOJO_PRICES_CENTS = {
    "therapist": 17500, "project_pm": 25000, "business": 32500,
    "cnc": 15000, "mcat": 50000, "teacher": 22500, "judge": 210000,
    "coach_nate": 9000,
}

SUCCESS_URL = os.getenv(
    "REGISTRATION_SUCCESS_URL",
    "https://app.sovereignsanctuary.net/payment-complete?session_id={CHECKOUT_SESSION_ID}",
)
CANCEL_URL = os.getenv(
    "REGISTRATION_CANCEL_URL",
    "https://app.sovereignsanctuary.net/payment-cancelled",
)

API_PUBLIC_BASE = os.getenv("API_PUBLIC_URL", "https://api.sovereignsanctuary.net").rstrip("/")
TRIAL_SETUP_CANCEL_URL = os.getenv(
    "TRIAL_SETUP_CANCEL_URL",
    "https://app.sovereignsanctuary.net/payment-cancelled",
)
TRIAL_SETUP_SUCCESS_REDIRECT = os.getenv(
    "TRIAL_SETUP_SUCCESS_REDIRECT",
    "https://app.sovereignsanctuary.net/trial-setup.html",
)
_TRIAL_SIGNUP_TTL = int(os.getenv("TRIAL_SIGNUP_REDIS_TTL", "1800"))


def _trial_redis_client(request: Request):
    wm = getattr(request.app.state, "wisdom_mesh", None)
    return getattr(wm, "_redis", None) if wm else None

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


class TrialSetupBillingRequest(BaseModel):
    name: str
    email: Optional[str] = None
    phone_digits: Optional[str] = None
    discount_code: Optional[str] = None


@public_router.post("/trial/setup-billing")
async def trial_setup_billing(body: TrialSetupBillingRequest, request: Request):
    """Stripe Checkout (mode=setup) to collect a card for trial registration; pending state in Redis."""
    client_ip = request.client.host if request.client else "unknown"
    if _rate_check(client_ip):
        raise HTTPException(429, "Too many registration attempts. Please try again shortly.")

    r = _trial_redis_client(request)
    if not r:
        raise HTTPException(503, "Service temporarily unavailable")
    if not stripe.api_key:
        raise HTTPException(503, "Billing unavailable")

    email = (body.email or "").strip().lower()
    phone_digits = re.sub(r"\D", "", body.phone_digits or "")
    if not email and len(phone_digits) < 10:
        raise HTTPException(400, "Email or phone number is required")

    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "Name is required")

    customer_id = None
    try:
        if email:
            existing = stripe.Customer.list(email=email, limit=1)
            if existing and existing.data:
                customer_id = existing.data[0].id
        if not customer_id:
            kwargs: Dict[str, Any] = {"name": name, "metadata": {"source": "trial_registration"}}
            if email:
                kwargs["email"] = email
            if len(phone_digits) >= 10:
                kwargs["phone"] = phone_digits
            cust = stripe.Customer.create(**kwargs)
            customer_id = cust.id
    except stripe.StripeError as e:
        logger.error("trial_setup_billing customer: %s", e)
        raise HTTPException(502, "Payment provider error")

    success_url = f"{API_PUBLIC_BASE}/api/registration/trial/setup-callback?session_id={{CHECKOUT_SESSION_ID}}"
    try:
        session = stripe.checkout.Session.create(
            mode="setup",
            customer=customer_id,
            payment_method_types=["card"],
            success_url=success_url,
            cancel_url=TRIAL_SETUP_CANCEL_URL,
            metadata={"type": "trial_registration_setup", "customer_id": customer_id},
        )
    except stripe.StripeError as e:
        logger.error("trial_setup_billing session: %s", e)
        raise HTTPException(502, "Payment service unavailable")

    pending: Dict[str, Any] = {
        "phase": "pending",
        "name": name,
        "email_normalized": email,
        "phone_digits": phone_digits if len(phone_digits) >= 10 else "",
    }
    discount_code = (body.discount_code or "").strip().upper()
    if discount_code:
        pending["discount_code"] = discount_code
    try:
        await r.setex(trial_signup_session_key(session.id), _TRIAL_SIGNUP_TTL, json.dumps(pending))
    except Exception as e:
        logger.warning("trial_setup_billing redis: %s", e)
        raise HTTPException(503, "Session storage failed")

    return {"checkout_url": session.url, "session_id": session.id}


@public_router.get("/trial/setup-callback")
async def trial_setup_callback(session_id: str, request: Request):
    """Stripe redirects here after setup-mode Checkout; finalize Redis and send user back to app web."""
    r = _trial_redis_client(request)
    if not stripe.api_key:
        sep = "&" if "?" in TRIAL_SETUP_SUCCESS_REDIRECT else "?"
        return RedirectResponse(
            f"{TRIAL_SETUP_SUCCESS_REDIRECT}{sep}error=no_stripe", status_code=302
        )

    try:
        sess = stripe.checkout.Session.retrieve(session_id, expand=["setup_intent"])
    except stripe.StripeError as e:
        logger.warning("trial_setup_callback retrieve: %s", e)
        sep = "&" if "?" in TRIAL_SETUP_SUCCESS_REDIRECT else "?"
        return RedirectResponse(
            f"{TRIAL_SETUP_SUCCESS_REDIRECT}{sep}error=stripe", status_code=302
        )

    if sess.status != "complete":
        sep = "&" if "?" in TRIAL_SETUP_SUCCESS_REDIRECT else "?"
        return RedirectResponse(
            f"{TRIAL_SETUP_SUCCESS_REDIRECT}{sep}error=incomplete", status_code=302
        )

    setup = sess.setup_intent
    if isinstance(setup, str):
        setup = stripe.SetupIntent.retrieve(setup)
    st = getattr(setup, "status", None) if setup else None
    if st != "succeeded":
        sep = "&" if "?" in TRIAL_SETUP_SUCCESS_REDIRECT else "?"
        return RedirectResponse(
            f"{TRIAL_SETUP_SUCCESS_REDIRECT}{sep}error=setup_failed", status_code=302
        )

    customer_id = sess.customer
    if not customer_id:
        sep = "&" if "?" in TRIAL_SETUP_SUCCESS_REDIRECT else "?"
        return RedirectResponse(
            f"{TRIAL_SETUP_SUCCESS_REDIRECT}{sep}error=no_customer", status_code=302
        )

    email_norm = ""
    phone_digits = ""
    name = ""
    discount_code_stored = ""
    if r:
        try:
            raw = await r.get(trial_signup_session_key(session_id))
            if raw:
                prev = json.loads(raw)
                email_norm = prev.get("email_normalized") or ""
                phone_digits = prev.get("phone_digits") or ""
                name = prev.get("name") or ""
                discount_code_stored = prev.get("discount_code") or ""
        except Exception as e:
            logger.warning("trial_setup_callback redis read: %s", e)

    try:
        cust = stripe.Customer.retrieve(customer_id)
        if not email_norm and getattr(cust, "email", None):
            email_norm = (cust.email or "").lower()
        if (not phone_digits or len(phone_digits) < 10) and getattr(cust, "phone", None):
            phone_digits = re.sub(r"\D", "", cust.phone or "")
    except Exception as e:
        logger.warning("trial_setup_callback customer retrieve: %s", e)

    payload: Dict[str, Any] = {
        "verified": True,
        "stripe_customer_id": customer_id,
        "email_normalized": email_norm,
        "phone_digits": phone_digits if len(phone_digits) >= 10 else "",
        "name": name,
    }
    if discount_code_stored:
        payload["discount_code"] = discount_code_stored
    if r:
        try:
            await r.setex(trial_signup_session_key(session_id), _TRIAL_SIGNUP_TTL, json.dumps(payload))
            if email_norm:
                await r.setex(trial_contact_key("email", email_norm), _TRIAL_SIGNUP_TTL, session_id)
            if phone_digits and len(phone_digits) >= 10:
                await r.setex(trial_contact_key("phone", phone_digits), _TRIAL_SIGNUP_TTL, session_id)
        except Exception as e:
            logger.warning("trial_setup_callback redis write: %s", e)

    sep = "&" if "?" in TRIAL_SETUP_SUCCESS_REDIRECT else "?"
    return RedirectResponse(
        f"{TRIAL_SETUP_SUCCESS_REDIRECT}{sep}billing_complete=1&session_id={session_id}",
        status_code=302,
    )


@public_router.get("/trial/billing-status")
async def trial_billing_status(
    request: Request,
    email: Optional[str] = None,
    phone_digits: Optional[str] = None,
):
    """Poll after Stripe setup so the app can recover session_id without deep links."""
    r = _trial_redis_client(request)
    if not r:
        return {"ready": False, "session_id": None}

    digits = re.sub(r"\D", "", phone_digits or "")
    sid = None
    if email and email.strip():
        try:
            sid = await r.get(trial_contact_key("email", email.strip().lower()))
        except Exception:
            sid = None
    if not sid and len(digits) >= 10:
        try:
            sid = await r.get(trial_contact_key("phone", digits))
        except Exception:
            sid = None

    if not sid:
        return {"ready": False, "session_id": None}

    try:
        raw = await r.get(trial_signup_session_key(sid))
        data = json.loads(raw) if raw else {}
    except Exception:
        return {"ready": False, "session_id": None}

    if data.get("verified") and data.get("stripe_customer_id"):
        return {"ready": True, "session_id": sid}
    return {"ready": False, "session_id": None}


# QUANTUM-CRYSTAL-ARCH — Public Trial Funnel Phase 3.5: TRIAL_FREE token
# exhaustion -> card-based TRIAL upgrade. Stateless Stripe collection only,
# mirroring trial_setup_billing/trial_setup_callback above — never touches
# `users`. The account mutation happens in the bridge WS handler
# `trial_free_upgrade_confirm` after this Checkout Session's SetupIntent
# succeeds (bridge-cache-db-sovereignty.mdc: mutations go through the bridge).
@public_router.post("/trial-free/upgrade-billing")
async def trial_free_upgrade_billing(
    request: Request,
    user: Optional[dict] = Depends(get_current_user) if get_current_user else None,
):
    """Stripe Checkout (mode=setup) to collect a card for a TRIAL_FREE -> TRIAL upgrade."""
    if not user:
        raise HTTPException(401, "Authentication required")

    client_ip = request.client.host if request.client else "unknown"
    if _rate_check(client_ip):
        raise HTTPException(429, "Too many requests. Please try again shortly.")

    if (user.get("registration_type") or "").upper() != "TRIAL_FREE":
        raise HTTPException(400, "Account is not eligible for this upgrade")

    r = _trial_redis_client(request)
    if not r:
        raise HTTPException(503, "Service temporarily unavailable")
    if not stripe.api_key:
        raise HTTPException(503, "Billing unavailable")

    hardware_id = user.get("hardware_id", "")
    email = (user.get("email") or "").strip().lower()
    name = (user.get("name") or "").strip() or user.get("username", "")

    customer_id = None
    try:
        if email:
            existing = stripe.Customer.list(email=email, limit=1)
            if existing and existing.data:
                customer_id = existing.data[0].id
        if not customer_id:
            kwargs: Dict[str, Any] = {
                "name": name,
                "metadata": {"source": "trial_free_upgrade", "hardware_id": hardware_id},
            }
            if email:
                kwargs["email"] = email
            cust = stripe.Customer.create(**kwargs)
            customer_id = cust.id
    except stripe.StripeError as e:
        logger.error("trial_free_upgrade_billing customer: %s", e)
        raise HTTPException(502, "Payment provider error")

    success_url = f"{API_PUBLIC_BASE}/api/registration/trial-free/upgrade-callback?session_id={{CHECKOUT_SESSION_ID}}"
    try:
        session = stripe.checkout.Session.create(
            mode="setup",
            customer=customer_id,
            payment_method_types=["card"],
            success_url=success_url,
            cancel_url=TRIAL_SETUP_CANCEL_URL,
            metadata={"type": "trial_free_upgrade_setup", "customer_id": customer_id, "hardware_id": hardware_id},
        )
    except stripe.StripeError as e:
        logger.error("trial_free_upgrade_billing session: %s", e)
        raise HTTPException(502, "Payment service unavailable")

    from app.services.trial_signup_redis_keys import trial_free_upgrade_session_key

    pending = {"phase": "pending", "hardware_id": hardware_id, "verified": False}
    try:
        await r.setex(trial_free_upgrade_session_key(session.id), _TRIAL_SIGNUP_TTL, json.dumps(pending))
    except Exception as e:
        logger.warning("trial_free_upgrade_billing redis: %s", e)
        raise HTTPException(503, "Session storage failed")

    return {"checkout_url": session.url, "session_id": session.id}


@public_router.get("/trial-free/upgrade-callback")
async def trial_free_upgrade_callback(session_id: str, request: Request):
    """Stripe redirects here after setup-mode Checkout; mirrors trial_setup_callback
    but writes into the trial_free_upgrade_session_key namespace. No `users` access —
    the bridge WS handler `trial_free_upgrade_confirm` performs the account flip."""
    from app.services.trial_signup_redis_keys import trial_free_upgrade_session_key

    r = _trial_redis_client(request)
    redirect_base = os.getenv(
        "TRIAL_FREE_UPGRADE_SUCCESS_REDIRECT",
        "https://app.sovereignsanctuary.net/trial-upgrade-complete",
    )
    sep = "&" if "?" in redirect_base else "?"

    if not stripe.api_key:
        return RedirectResponse(f"{redirect_base}{sep}session_id={session_id}&error=no_stripe", status_code=302)

    try:
        sess = stripe.checkout.Session.retrieve(session_id, expand=["setup_intent"])
    except stripe.StripeError as e:
        logger.warning("trial_free_upgrade_callback retrieve: %s", e)
        return RedirectResponse(f"{redirect_base}{sep}session_id={session_id}&error=stripe", status_code=302)

    if sess.status != "complete":
        return RedirectResponse(f"{redirect_base}{sep}session_id={session_id}&error=incomplete", status_code=302)

    setup = sess.setup_intent
    if isinstance(setup, str):
        setup = stripe.SetupIntent.retrieve(setup)
    st = getattr(setup, "status", None) if setup else None
    if st != "succeeded":
        return RedirectResponse(f"{redirect_base}{sep}session_id={session_id}&error=setup_failed", status_code=302)

    customer_id = sess.customer
    if not customer_id:
        return RedirectResponse(f"{redirect_base}{sep}session_id={session_id}&error=no_customer", status_code=302)

    hardware_id = ""
    if r:
        try:
            raw = await r.get(trial_free_upgrade_session_key(session_id))
            if raw:
                prev = json.loads(raw)
                hardware_id = prev.get("hardware_id") or ""
        except Exception as e:
            logger.warning("trial_free_upgrade_callback redis read: %s", e)

    payload = {"verified": True, "stripe_customer_id": customer_id, "hardware_id": hardware_id}
    if r:
        try:
            await r.setex(trial_free_upgrade_session_key(session_id), _TRIAL_SIGNUP_TTL, json.dumps(payload))
        except Exception as e:
            logger.warning("trial_free_upgrade_callback redis write: %s", e)

    return RedirectResponse(f"{redirect_base}{sep}session_id={session_id}", status_code=302)


class PrepareRequest(BaseModel):
    role: str
    username: str
    password: str
    email: Optional[str] = ""
    name: str
    dob: Optional[str] = None
    phone: Optional[str] = None
    consent_version: str = "v13.0_2026"
    consent_agreed: bool = True
    tier: Optional[str] = None
    billing_cycle: str = "monthly"
    selected_dojos: Optional[List[str]] = None
    discount_code: Optional[str] = None
    profile_fields: Optional[dict] = None
    # Family-plan dependent (e.g. Zack under Paula's Sovereign Circle).
    # When set, the dependent is created free under the parent and Stripe
    # checkout is skipped entirely.
    parent_username: Optional[str] = None
    invite_code: Optional[str] = None
    family_role: Optional[str] = None
    # Coach upgrade fields
    flow: Optional[str] = None
    auth_token: Optional[str] = None


async def _resolve_parent_username(
    db_pool, parent_username: Optional[str], invite_code: Optional[str]
) -> Optional[str]:
    """Map an invite_code to the HoH username if parent_username is absent."""
    pu = (parent_username or "").strip()
    if pu:
        return pu
    ic = (invite_code or "").strip()
    if not ic:
        return None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.username
            FROM family_invites fi
            JOIN users u ON u.id = fi.inviter_id
            WHERE fi.invite_code = $1
            LIMIT 1
            """,
            ic,
        )
        if row:
            return row["username"]
        row2 = await conn.fetchrow(
            """
            SELECT profile_data->>'linked_by' AS linked_by
            FROM users
            WHERE profile_data->>'invite_code' = $1
            LIMIT 1
            """,
            ic,
        )
        if row2 and row2["linked_by"]:
            return row2["linked_by"]
    return None


async def _resolve_family_role(
    db_pool,
    invite_code: Optional[str],
    family_role: Optional[str],
) -> str:
    from app.services.registration_finalize import normalize_family_member_role

    fr = (family_role or "").strip()
    if fr:
        return normalize_family_member_role(fr)
    ic = (invite_code or "").strip()
    if not ic:
        return "DEPENDENT"
    async with db_pool.acquire() as conn:
        from app.services.registration_finalize import _resolve_role_from_invite

        invited = await _resolve_role_from_invite(conn, ic)
        if invited:
            return normalize_family_member_role(invited)
    return "DEPENDENT"


@public_router.get("/dependent-price")
async def dependent_price_preview(
    request: Request,
    parent_username: Optional[str] = None,
    invite_code: Optional[str] = None,
    family_role: Optional[str] = None,
):
    """Return the monthly cost for adding a dependent under `parent_username`.

    Used by the registration form to disclose "This will be the 2nd dependent
    at $75/mo" BEFORE the user submits — so paid-dep redirects to Stripe are
    not a surprise. Free first-dependent returns monthly_cost_cents=0.

    Public, rate-limited; rejects if parent is not on an active Sovereign
    Circle plan.
    """
    client_ip = request.client.host if request.client else "unknown"
    if _rate_check(client_ip):
        raise HTTPException(429, "Too many lookups. Please try again shortly.")

    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Service temporarily unavailable")

    parent_username = await _resolve_parent_username(db_pool, parent_username, invite_code)
    if not parent_username:
        raise HTTPException(400, "parent_username or invite_code is required")

    from app.services.registration_finalize import (
        DEPENDENT_ELIGIBLE_PARENT_TIERS,
        DEPENDENT_ELIGIBLE_PARENT_STATUSES,
        _count_existing_dependents,
        _count_existing_spouses,
        compute_family_member_billing,
    )

    member_role = await _resolve_family_role(db_pool, invite_code, family_role)

    async with db_pool.acquire() as conn:
        parent = await conn.fetchrow(
            """
            SELECT id, family_id, tier, subscription_status
            FROM users
            WHERE LOWER(username) = LOWER($1) AND role = 'CLIENT'
            """,
            parent_username,
        )
        if not parent:
            return {
                "eligible": False,
                "reason": "PARENT_NOT_FOUND",
                "message": "Head-of-household account not found.",
            }
        parent_tier = (parent["tier"] or "").upper()
        parent_status = (parent["subscription_status"] or "").upper()
        if parent_tier not in DEPENDENT_ELIGIBLE_PARENT_TIERS:
            return {
                "eligible": False,
                "reason": "PARENT_NOT_SOVEREIGN_CIRCLE",
                "message": "Head of household must be on Sovereign Circle.",
            }
        if parent_status not in DEPENDENT_ELIGIBLE_PARENT_STATUSES:
            return {
                "eligible": False,
                "reason": "PARENT_SUBSCRIPTION_INACTIVE",
                "message": "Head-of-household subscription is not active.",
            }

        existing = 0
        if parent["family_id"]:
            existing = await _count_existing_dependents(conn, parent["family_id"])

        if member_role == "SPOUSE":
            spouse_count = await _count_existing_spouses(conn, parent["family_id"])
            if spouse_count > 0:
                return {
                    "eligible": False,
                    "reason": "SPOUSE_ALREADY_LINKED",
                    "message": "This family already has a spouse linked.",
                    "family_role": "SPOUSE",
                }

    billing = compute_family_member_billing(
        family_role=member_role,
        existing_dependent_count=existing,
    )

    if billing["free"]:
        if member_role == "SPOUSE":
            msg = "Spouse on Sovereign Circle is always free."
        elif existing == 0:
            msg = "First dependent on Sovereign Circle is free."
        else:
            msg = "Included on Sovereign Circle plan."
        return {
            "eligible": True,
            "free": True,
            "ordinal": existing + 1 if member_role == "DEPENDENT" else 0,
            "monthly_cost_cents": 0,
            "monthly_cost_display": "$0.00",
            "family_role": member_role,
            "message": msg,
        }

    paid_ordinal = billing["paid_ordinal"]
    cents = billing["monthly_cost_cents"]
    capped = max(1, min(paid_ordinal, 4))
    return {
        "eligible": True,
        "free": False,
        "ordinal": existing + 1,
        "paid_ordinal": paid_ordinal,
        "family_tier_price_key": billing.get("family_tier_price_key"),
        "monthly_cost_cents": cents,
        "monthly_cost_display": f"${cents / 100:.2f}",
        "family_role": member_role,
        "message": (
            f"Parent already has {existing} dependent"
            f"{'s' if existing != 1 else ''}. This will be dependent #{existing + 1} "
            f"at ${cents / 100:.2f}/mo."
        ),
    }


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
    profile_fields["phone"] = (body.phone or "").strip()
    profile_fields["consent_version"] = body.consent_version

    # ------------------------------------------------------------------
    # Dependent path: a CLIENT signing up under a parent on Sovereign Circle.
    #   - 1st dependent in the family is FREE → finalized inline.
    #   - 2nd+ dependent is PAID via STRIPE_PRICE_FAMILY_TIER_N
    #     ($75 / $60 / $45 / $30 by ordinal). We create a pending_signups
    #     row and Stripe Checkout session; the webhook calls
    #     finalize_paid_dependent_signup() on success.
    # ------------------------------------------------------------------
    parent_username = await _resolve_parent_username(
        db_pool, body.parent_username, body.invite_code
    )
    if role == "CLIENT" and parent_username:
        from app.services.registration_finalize import finalize_dependent_signup

        resolved_role = await _resolve_family_role(
            db_pool, body.invite_code, body.family_role
        )
        profile_fields["family_role"] = resolved_role

        ok, reason, info = await finalize_dependent_signup(
            db_pool,
            username=username,
            password_hash=password_hash,
            email=email,
            profile_fields=profile_fields,
            parent_username=parent_username,
            family_role=resolved_role,
            invite_code=body.invite_code,
        )

        if ok:
            return {
                "checkout_url": None,
                "dependent_created": True,
                "user_id": info.get("user_id"),
                "family_id": info.get("family_id"),
                "parent_username": info.get("parent_username"),
                "is_minor": info.get("is_minor", False),
                "paid_ordinal": info.get("paid_ordinal", 0),
                "monthly_cost_cents": info.get("monthly_cost_cents", 0),
                "message": "Dependent linked to Sovereign Circle plan — no payment required.",
            }

        # Paid-dependent path: create pending signup + Stripe Checkout.
        if reason == "DEPENDENT_REQUIRES_PAYMENT":
            tier_key = info.get("family_tier_price_key")  # e.g. STRIPE_PRICE_FAMILY_TIER_1
            paid_ordinal = info.get("paid_ordinal", 1)
            monthly_cost_cents = info.get("monthly_cost_cents", 0)
            family_id = info.get("family_id")
            parent_id = info.get("parent_id")
            is_minor = info.get("is_minor", False)

            # Resolve to a price_id via PRICES dict (FAMILY_TIER_N keys).
            price_lookup_key = (tier_key or "").replace("STRIPE_PRICE_", "")
            price_id = PRICES.get(price_lookup_key)
            if not price_id:
                logger.error(
                    "Family tier price not configured: %s (paid_ordinal=%d)",
                    tier_key, paid_ordinal,
                )
                raise HTTPException(
                    503,
                    "Family-plan billing is not configured. Please contact support.",
                )

            # Encode dependent context inside payload so the webhook can
            # finalize via finalize_paid_dependent_signup.
            dep_payload = dict(profile_fields)
            dep_payload["signup_type"] = "dependent"
            dep_payload["parent_username"] = parent_username
            dep_payload["parent_id"] = parent_id
            dep_payload["family_id"] = family_id
            dep_payload["is_minor"] = is_minor
            dep_payload["paid_ordinal"] = paid_ordinal
            dep_payload["monthly_cost_cents"] = monthly_cost_cents
            dep_payload["family_tier_price_key"] = tier_key

            dep_pricing_snapshot = {
                "tier": "DEPENDENT",
                "billing_cycle": "monthly",
                "price_key": price_lookup_key,
                "paid_ordinal": paid_ordinal,
                "monthly_cost_cents": monthly_cost_cents,
                "parent_username": parent_username,
                "family_id": family_id,
            }

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
                            json.dumps(dep_payload),
                            "DEPENDENT",
                            json.dumps([]),
                            None,
                            json.dumps(dep_pricing_snapshot),
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
                            "CLIENT",
                            username,
                            password_hash,
                            email,
                            json.dumps(dep_payload),
                            "DEPENDENT",
                            json.dumps([]),
                            None,
                            json.dumps(dep_pricing_snapshot),
                        )
                        signup_id = str(row["id"])
            except Exception as e:
                logger.error("paid-dependent pending_signups INSERT failed: %s", e)
                raise HTTPException(500, "Registration setup failed")

            try:
                checkout_session = stripe.checkout.Session.create(
                    mode="subscription",
                    payment_method_types=["card"],
                    line_items=[{"price": price_id, "quantity": 1}],
                    success_url=SUCCESS_URL,
                    cancel_url=CANCEL_URL,
                    metadata={
                        "type": "pending_dependent_signup",
                        "pending_signup_id": signup_id,
                        "parent_username": parent_username,
                        "family_id": str(family_id),
                        "paid_ordinal": str(paid_ordinal),
                        "family_tier_price_key": tier_key or "",
                    },
                )
            except stripe.StripeError as e:
                logger.error(
                    "Stripe Checkout creation failed (paid dependent): %s", e
                )
                raise HTTPException(502, "Payment service unavailable")

            try:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE pending_signups SET stripe_checkout_session_id = $1 "
                        "WHERE id = $2::uuid",
                        checkout_session.id,
                        signup_id,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to link Stripe session to dependent pending_signup: %s",
                    e,
                )

            return {
                "checkout_url": checkout_session.url,
                "session_id": checkout_session.id,
                "pricing_snapshot": dep_pricing_snapshot,
                "dependent_paid": True,
                "paid_ordinal": paid_ordinal,
                "monthly_cost_cents": monthly_cost_cents,
                "parent_username": parent_username,
                "message": (
                    f"Dependent #{paid_ordinal + 1} under Sovereign Circle — "
                    f"${monthly_cost_cents / 100:.2f}/mo. Continue to payment."
                ),
            }

        # Validation failures.
        human = {
            "USERNAME_TAKEN": ("Username is already taken", 409),
            "PARENT_NOT_FOUND": (
                "Head-of-household account not found. Check the parent's username.",
                400,
            ),
            "PARENT_NOT_SOVEREIGN_CIRCLE": (
                "Dependent membership requires the head of household to be on Sovereign Circle.",
                400,
            ),
            "PARENT_SUBSCRIPTION_INACTIVE": (
                "Head-of-household subscription is not active.",
                400,
            ),
            "PARENT_USERNAME_REQUIRED": ("Parent username is required.", 400),
            "SPOUSE_ALREADY_LINKED": (
                "Only one spouse is allowed per family.",
                409,
            ),
        }
        msg, status = human.get(reason, (f"Dependent registration failed: {reason}", 400))
        if reason.startswith("DB_ERROR"):
            logger.error("finalize_dependent_signup DB error: %s", reason)
            msg, status = "Registration setup failed", 500
        raise HTTPException(status, msg)

    # Fail-safe: if invite_code was provided but couldn't resolve to a parent,
    # do not allow a standalone HoH-tier checkout — the user intended to join a family.
    if body.invite_code and not parent_username:
        raise HTTPException(
            400,
            "Invalid or expired invite code. Please ask your family member to resend.",
        )

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
                    "FROM promotional_specials WHERE promo_code = $1 AND active = true "
                    "AND ends_at > NOW()",
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
            disc_code = (body.discount_code or pricing_snapshot.get("discount_code") or "").strip().upper()
            if disc_code:
                session_params["metadata"]["applied_promo_code"] = disc_code
                session_params["metadata"]["applied_promo_source"] = "promotional_specials"

        checkout_session = stripe.checkout.Session.create(**session_params)
    except stripe.StripeError as e:
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
        "https://app.sovereignsanctuary.net/payment-complete",
    )
    cancel_url = os.getenv(
        "UPGRADE_CANCEL_URL",
        "https://app.sovereignsanctuary.net/payment-cancelled",
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
    except stripe.StripeError as e:
        logger.error("Coach upgrade Stripe session failed: %s", e)
        raise HTTPException(502, "Payment provider error")

    return {
        "checkout_url": checkout_session.url,
        "session_id": checkout_session.id,
        "monthly_total_cents": monthly_total_cents,
    }
