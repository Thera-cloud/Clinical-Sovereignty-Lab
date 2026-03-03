"""
Billing & Subscription API Routes
Handles Stripe integration, subscription management, and payment processing.

Endpoints include: plans, subscription management (subscribe, upgrade, downgrade),
coaching sessions and packs, payment methods, invoices, and token usage.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any

from app.auth import get_current_user_id
from datetime import datetime, timedelta
import os
import json
import secrets
from pathlib import Path

try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False

router = APIRouter(
    prefix="/api/billing",
    tags=["billing"],
    dependencies=[Depends(get_current_user_id)],
)

# Configuration
from app.config import settings as _settings
DATA_DIR = Path(_settings.DATA_DIR)

if STRIPE_AVAILABLE:
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

# Plan Details — aligned with Locked Pricing Model v3
# coach_sessions = max bookable per billing period (client pays coach; platform takes 30%, min $30)
# ai_minutes = -1 means unlimited
PLAN_DETAILS = {
    "COACH_ONLY": {"name": "Coach Only", "tokens": 0, "ai_minutes": 0, "coach_sessions": -1, "price_monthly": 0, "price_yearly": 0, "can_access_nate": False},
    "TRIAL": {
        "name": "Threshold (Trial)", "tokens": 50000, "ai_minutes": 300, "coach_sessions": 0,
        "price_monthly": 0, "price_yearly": 0, "trial_days": 14,
        "trial_week1": {"ai_minutes": 300, "tokens": 50000},
        "trial_week2": {"ai_minutes_per_day": 30, "tokens": 50000, "coherence_prompt": True},
    },
    "STANDARD": {
        "name": "Inner Chamber", "tokens": 50000, "ai_minutes": 300, "coach_sessions": 4,
        "price_monthly": 49, "price_yearly": 490, "founding_price_monthly": 39,
        "family_sanctuary": True, "legacy_vault_gb": 1,
        "nevedal_types": 2, "nevedal_per_month": 2, "foresight_per_month": 4,
        "custom_folders": 10, "vault_search": True, "annotations": True, "dream_journal": True, "vault_export": True,
    },
    "TOP_TIER": {
        "name": "Sovereign Circle", "tokens": 200000, "ai_minutes": -1, "coach_sessions": 8,
        "price_monthly": 149, "price_yearly": 1490, "founding_price_monthly": 119,
        "family_sanctuary": True, "me2me": True, "legacy_vault_gb": 50,
        "nevedal_types": 5, "nevedal_per_month": 8, "foresight_per_month": -1,
        "archivist_chapters_per_month": 10, "me2me_avatar_hours": 10, "pattern_engine": True,
        "realtime_voice": True, "custom_folders": -1,
        "vault_search": True, "annotations": True, "dream_journal": True, "vault_export": True,
        "proactive_vault_suggest": True, "timeline_view": True, "side_by_side": True,
        "legacy_letters": True, "voice_over_image": True,
    },
}

# Family add-on pricing (Locked v3 adjusted)
FAMILY_PRICING = {
    "spouse": {"price_monthly": 0, "description": "Always free"},
    "first_child_under_12": {"price_monthly": 0, "description": "First child under 12 is free"},
    "paid_tiers": [
        {"ordinal": 1, "price_monthly": 75, "description": "1st paid add-on"},
        {"ordinal": 2, "price_monthly": 60, "description": "2nd paid add-on"},
        {"ordinal": 3, "price_monthly": 45, "description": "3rd paid add-on"},
        {"ordinal": "4+", "price_monthly": 30, "description": "4th+ paid add-on"},
    ],
    "note": "Children 13+ and additional members enter the paid tier queue by join order",
}

# Overage pricing (Locked v3)
OVERAGE_PRICING = {
    "ai_minutes_ic": {"per_unit": 0.15, "unit": "minute", "description": "Inner Chamber AI minute overage"},
    "ai_minutes_sc": {"per_unit": 0.10, "unit": "minute", "description": "Sovereign Circle AI minute overage"},
    "nevedal_report": {"per_unit": 5.00, "unit": "report", "description": "Additional Nevedal report"},
    "foresight_report": {"per_unit": 3.00, "unit": "report", "description": "Additional Foresight report (IC only)"},
    "archivist_chapter": {"per_unit": 1.50, "unit": "chapter", "description": "Additional Archivist chapter beyond 10/mo"},
    "me2me_avatar_hour": {"per_unit": 2.00, "unit": "hour", "description": "Additional Me2Me avatar hour beyond 10/mo"},
    "vault_storage_gb": {"per_unit": 0.50, "unit": "GB/month", "description": "Vault storage beyond included"},
}

# Models
class SubscriptionRequest(BaseModel):
    user_id: str
    plan: str
    billing_cycle: str = "monthly"

class UpgradeDowngradeRequest(BaseModel):
    user_id: str
    new_plan: str
    proration: bool = True

class UsageRequest(BaseModel):
    user_id: str
    tokens: int

class PaymentMethodAttachRequest(BaseModel):
    user_id: str
    payment_method_id: str  # from Stripe.js on the client

class BookCoachingSessionRequest(BaseModel):
    user_id: str
    coach_id: str
    scheduled_at: str  # ISO-8601 datetime
    use_pack_id: Optional[str] = None

class CancelCoachingSessionRequest(BaseModel):
    user_id: str
    reason: Optional[str] = None

# Helper functions
def load_json(filepath: Path, default=None):
    if default is None: default = {}
    if not filepath.exists(): return default
    try:
        with open(filepath, 'r') as f: return json.load(f)
    except: return default

def save_json(filepath: Path, data):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w') as f: json.dump(data, f, indent=2, default=str)

@router.get("/plans")
async def get_plans():
    return {"plans": PLAN_DETAILS, "family_pricing": FAMILY_PRICING, "overages": OVERAGE_PRICING}

@router.get("/subscription/{user_id}")
async def get_subscription(user_id: str):
    billing = load_json(DATA_DIR / "billing.json")
    sub = billing.get("subscriptions", {}).get(user_id)
    if not sub:
        return {"plan": "TRIAL", "status": "TRIAL_ACTIVE", "details": PLAN_DETAILS["TRIAL"]}
    return {"subscription": sub, "details": PLAN_DETAILS.get(sub.get("plan", "STANDARD"))}

@router.post("/subscribe")
async def create_subscription(req: SubscriptionRequest):
    if req.plan not in PLAN_DETAILS:
        raise HTTPException(400, "Invalid plan")
    
    plan = PLAN_DETAILS[req.plan]
    billing = load_json(DATA_DIR / "billing.json")
    
    sub = {
        "user_id": req.user_id,
        "plan": req.plan,
        "status": "active",
        "tokens_included": plan["tokens"],
        "start_date": str(datetime.now().date()),
        "end_date": str((datetime.now() + timedelta(days=30)).date()),
        "created_at": str(datetime.now())
    }
    
    billing.setdefault("subscriptions", {})[req.user_id] = sub
    save_json(DATA_DIR / "billing.json", billing)
    
    # Update user registry
    registry = load_json(DATA_DIR / "user_registry.json")
    for k, v in registry.items():
        if v.get("profile", {}).get("hardware_id") == req.user_id:
            v["profile"]["subscription_plan"] = req.plan
            v["profile"]["subscription_status"] = "ACTIVE"
            v["profile"]["token_balance"] = plan["tokens"]
            save_json(DATA_DIR / "user_registry.json", registry)
            break
    
    return {"subscription": sub}

@router.get("/usage/{user_id}")
async def get_usage(user_id: str):
    registry = load_json(DATA_DIR / "user_registry.json")
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("hardware_id") == user_id:
            return {
                "token_balance": p.get("token_balance", 0),
                "tokens_used_today": p.get("token_usage_today", 0),
                "tokens_used_month": p.get("token_usage_month", 0),
                "plan": p.get("subscription_plan", "TRIAL")
            }
    raise HTTPException(404, "User not found")

@router.post("/use-tokens")
async def use_tokens(req: UsageRequest):
    registry = load_json(DATA_DIR / "user_registry.json")
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("hardware_id") == req.user_id:
            balance = p.get("token_balance", 0)
            if balance < req.tokens:
                raise HTTPException(402, "Insufficient tokens")
            p["token_balance"] = balance - req.tokens
            p["token_usage_today"] = p.get("token_usage_today", 0) + req.tokens
            p["token_usage_month"] = p.get("token_usage_month", 0) + req.tokens
            save_json(DATA_DIR / "user_registry.json", registry)
            return {"remaining": p["token_balance"]}
    raise HTTPException(404, "User not found")

@router.get("/transactions/{user_id}")
async def get_transactions(user_id: str, limit: int = 20):
    billing = load_json(DATA_DIR / "billing.json")
    txns = [t for t in billing.get("transactions", []) if t.get("user_id") == user_id]
    return {"transactions": txns[-limit:]}


# =========================================================================
# Upgrade / Downgrade
# =========================================================================

TIER_ORDER = ["COACH_ONLY", "TRIAL", "STANDARD", "TOP_TIER"]


def _find_user_profile(user_id: str):
    """Return (registry dict, key, profile dict) or raise 404."""
    registry = load_json(DATA_DIR / "user_registry.json")
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("hardware_id") == user_id:
            return registry, k, p
    raise HTTPException(404, "User not found")


def _get_stripe_customer(user_id: str) -> Optional[str]:
    """Retrieve Stripe customer ID from billing data or registry."""
    billing = load_json(DATA_DIR / "billing.json")
    sub = billing.get("subscriptions", {}).get(user_id, {})
    cust_id = sub.get("stripe_customer_id")
    if cust_id:
        return cust_id
    # Fallback: check registry
    registry = load_json(DATA_DIR / "user_registry.json")
    for _k, v in registry.items():
        p = v.get("profile", {})
        if p.get("hardware_id") == user_id:
            return p.get("stripe_customer_id")
    return None


@router.post("/subscription/upgrade")
async def upgrade_subscription(req: UpgradeDowngradeRequest):
    """Change plan upward."""
    if req.new_plan not in PLAN_DETAILS:
        raise HTTPException(400, f"Invalid plan: {req.new_plan}")

    registry, rk, profile = _find_user_profile(req.user_id)
    current_plan = (profile.get("subscription_plan") or "TRIAL").upper()
    new_idx = TIER_ORDER.index(req.new_plan) if req.new_plan in TIER_ORDER else -1
    cur_idx = TIER_ORDER.index(current_plan) if current_plan in TIER_ORDER else -1

    if new_idx <= cur_idx:
        raise HTTPException(400, "New plan must be higher tier. Use /subscription/downgrade instead.")

    new_details = PLAN_DETAILS[req.new_plan]

    # If Stripe is available and user has a Stripe subscription, update via Stripe
    stripe_customer = _get_stripe_customer(req.user_id)
    stripe_updated = False
    if STRIPE_AVAILABLE and stripe_customer and stripe.api_key:
        try:
            subs = stripe.Subscription.list(customer=stripe_customer, status="active", limit=1)
            if subs.data:
                sub = subs.data[0]
                new_price_key = f"STRIPE_PRICE_{req.new_plan}"
                new_price = os.getenv(new_price_key, "")
                if new_price:
                    stripe.Subscription.modify(
                        sub.id,
                        items=[{"id": sub["items"]["data"][0].id, "price": new_price}],
                        proration_behavior="create_prorations" if req.proration else "none",
                    )
                    stripe_updated = True
        except Exception as e:
            print(f"   ⚠️  Stripe upgrade failed for {req.user_id}: {e}")

    # Update local billing state
    profile["subscription_plan"] = req.new_plan
    profile["subscription_status"] = "ACTIVE"
    profile["token_balance"] = new_details["tokens"]
    save_json(DATA_DIR / "user_registry.json", registry)

    billing = load_json(DATA_DIR / "billing.json")
    billing.setdefault("subscriptions", {})[req.user_id] = {
        "user_id": req.user_id,
        "plan": req.new_plan,
        "status": "active",
        "tokens_included": new_details["tokens"],
        "previous_plan": current_plan,
        "changed_at": str(datetime.now()),
        "stripe_updated": stripe_updated,
    }
    billing.setdefault("transactions", []).append({
        "user_id": req.user_id,
        "type": "upgrade",
        "from_plan": current_plan,
        "to_plan": req.new_plan,
        "timestamp": str(datetime.now()),
    })
    save_json(DATA_DIR / "billing.json", billing)

    return {
        "status": "upgraded",
        "plan": req.new_plan,
        "stripe_updated": stripe_updated,
        "details": new_details,
    }


@router.post("/subscription/downgrade")
async def downgrade_subscription(req: UpgradeDowngradeRequest):
    """Change plan downward with proration."""
    if req.new_plan not in PLAN_DETAILS:
        raise HTTPException(400, f"Invalid plan: {req.new_plan}")

    registry, rk, profile = _find_user_profile(req.user_id)
    current_plan = (profile.get("subscription_plan") or "TRIAL").upper()
    new_idx = TIER_ORDER.index(req.new_plan) if req.new_plan in TIER_ORDER else -1
    cur_idx = TIER_ORDER.index(current_plan) if current_plan in TIER_ORDER else -1

    if new_idx >= cur_idx:
        raise HTTPException(400, "New plan must be lower tier. Use /subscription/upgrade instead.")

    new_details = PLAN_DETAILS[req.new_plan]

    # Stripe downgrade — takes effect at period end
    stripe_customer = _get_stripe_customer(req.user_id)
    stripe_updated = False
    if STRIPE_AVAILABLE and stripe_customer and stripe.api_key:
        try:
            subs = stripe.Subscription.list(customer=stripe_customer, status="active", limit=1)
            if subs.data:
                sub = subs.data[0]
                new_price_key = f"STRIPE_PRICE_{req.new_plan}"
                new_price = os.getenv(new_price_key, "")
                if new_price:
                    stripe.Subscription.modify(
                        sub.id,
                        items=[{"id": sub["items"]["data"][0].id, "price": new_price}],
                        proration_behavior="create_prorations" if req.proration else "none",
                    )
                    stripe_updated = True
        except Exception as e:
            print(f"   ⚠️  Stripe downgrade failed for {req.user_id}: {e}")

    # Update local state
    profile["subscription_plan"] = req.new_plan
    profile["subscription_status"] = "ACTIVE" if req.new_plan not in ("TRIAL", "COACH_ONLY") else req.new_plan
    profile["token_balance"] = min(profile.get("token_balance", 0), new_details["tokens"])
    save_json(DATA_DIR / "user_registry.json", registry)

    billing = load_json(DATA_DIR / "billing.json")
    billing.setdefault("subscriptions", {})[req.user_id] = {
        "user_id": req.user_id,
        "plan": req.new_plan,
        "status": "active",
        "tokens_included": new_details["tokens"],
        "previous_plan": current_plan,
        "changed_at": str(datetime.now()),
        "stripe_updated": stripe_updated,
    }
    billing.setdefault("transactions", []).append({
        "user_id": req.user_id,
        "type": "downgrade",
        "from_plan": current_plan,
        "to_plan": req.new_plan,
        "timestamp": str(datetime.now()),
    })
    save_json(DATA_DIR / "billing.json", billing)

    return {
        "status": "downgraded",
        "plan": req.new_plan,
        "stripe_updated": stripe_updated,
        "details": new_details,
    }


# =========================================================================
# Invoices
# =========================================================================

@router.get("/invoices/{user_id}")
async def get_invoices(user_id: str, limit: int = 20):
    """Return invoice list. Checks Stripe first, falls back to local txn log."""
    # Try Stripe
    if STRIPE_AVAILABLE and stripe.api_key:
        stripe_customer = _get_stripe_customer(user_id)
        if stripe_customer:
            try:
                invoices = stripe.Invoice.list(customer=stripe_customer, limit=limit)
                return {
                    "source": "stripe",
                    "invoices": [
                        {
                            "id": inv.id,
                            "amount_due": inv.amount_due / 100,
                            "amount_paid": inv.amount_paid / 100,
                            "currency": inv.currency,
                            "status": inv.status,
                            "created": datetime.fromtimestamp(inv.created).isoformat(),
                            "pdf_url": inv.invoice_pdf,
                            "hosted_url": inv.hosted_invoice_url,
                            "period_start": datetime.fromtimestamp(inv.period_start).isoformat() if inv.period_start else None,
                            "period_end": datetime.fromtimestamp(inv.period_end).isoformat() if inv.period_end else None,
                        }
                        for inv in invoices.auto_paging_iter()
                    ][:limit],
                }
            except Exception as e:
                print(f"   ⚠️  Stripe invoice fetch failed for {user_id}: {e}")

    # Fallback: local transactions
    billing = load_json(DATA_DIR / "billing.json")
    txns = [t for t in billing.get("transactions", []) if t.get("user_id") == user_id]
    return {"source": "local", "invoices": txns[-limit:]}


# =========================================================================
# Payment Methods
# =========================================================================

@router.get("/payment-methods/{user_id}")
async def list_payment_methods(user_id: str):
    """List saved payment methods from Stripe."""
    stripe_customer = _get_stripe_customer(user_id)

    if STRIPE_AVAILABLE and stripe_customer and stripe.api_key:
        try:
            default_pm = (
                stripe.Customer.retrieve(stripe_customer)
                .invoice_settings.get("default_payment_method")
            )
            cards = stripe.PaymentMethod.list(customer=stripe_customer, type="card")
            result = [
                {
                    "id": pm.id,
                    "type": "card",
                    "brand": pm.card.brand,
                    "last4": pm.card.last4,
                    "exp_month": pm.card.exp_month,
                    "exp_year": pm.card.exp_year,
                    "is_default": pm.id == default_pm,
                }
                for pm in cards.data
            ]
            try:
                banks = stripe.PaymentMethod.list(customer=stripe_customer, type="us_bank_account")
                for pm in banks.data:
                    bank = pm.us_bank_account
                    result.append({
                        "id": pm.id,
                        "type": "us_bank_account",
                        "bank_name": bank.bank_name if bank else "Bank",
                        "last4": bank.last4 if bank else "????",
                        "account_type": bank.account_type if bank else None,
                        "is_default": pm.id == default_pm,
                    })
            except Exception:
                pass
            return {"payment_methods": result}
        except Exception as e:
            print(f"   ⚠️  Stripe payment methods fetch failed: {e}")
            raise HTTPException(502, f"Failed to retrieve payment methods: {e}")

    return {"payment_methods": [], "note": "Stripe not configured or no customer linked"}


@router.post("/payment-methods")
async def attach_payment_method(req: PaymentMethodAttachRequest):
    """Attach a new payment method to the user's Stripe customer and set as default."""
    stripe_customer = _get_stripe_customer(req.user_id)
    if not stripe_customer:
        raise HTTPException(404, "No Stripe customer found for this user")

    if not STRIPE_AVAILABLE or not stripe.api_key:
        raise HTTPException(503, "Stripe is not configured")

    try:
        # Attach method to customer
        stripe.PaymentMethod.attach(
            req.payment_method_id,
            customer=stripe_customer,
        )
        # Set as default
        stripe.Customer.modify(
            stripe_customer,
            invoice_settings={"default_payment_method": req.payment_method_id},
        )
        return {"status": "attached", "payment_method_id": req.payment_method_id}
    except Exception as e:
        raise HTTPException(400, f"Failed to attach payment method: {e}")


@router.delete("/payment-methods/{pm_id}")
async def detach_payment_method(pm_id: str, user_id: str):
    """Detach a payment method from the Stripe customer."""
    if not STRIPE_AVAILABLE or not stripe.api_key:
        raise HTTPException(503, "Stripe is not configured")

    try:
        stripe.PaymentMethod.detach(pm_id)
        return {"status": "detached", "payment_method_id": pm_id}
    except Exception as e:
        raise HTTPException(400, f"Failed to detach payment method: {e}")


# =========================================================================
# Coaching Sessions & Packs
# =========================================================================

# Locked Pricing Model v3 — Coach economics (70/30 split, commission only)
# Single: $175 → coach $122.50, platform $52.50
# 4-pack: $600 ($150/session) → coach $105/session, platform $45/session
# 8-pack: $1,120 ($140/session) → coach $98/session, platform $42/session
COACH_PAYOUT = {
    "platform_fee_pct": 0.30,
    "coach_pct": 0.70,
    "min_platform_fee_cents": 3000,  # $30 minimum (Coach Only tier)
    "single": {"price": 175, "coach_per_session": 122.50, "platform_per_session": 52.50},
    "pack_4": {"price": 600, "coach_per_session": 105.00, "platform_per_session": 45.00},
    "pack_8": {"price": 1120, "coach_per_session": 98.00, "platform_per_session": 42.00},
}

COACHING_PACKS = {
    "single": {"sessions": 1, "price": 175, "label": "Single Session", "coach_per_session": 122.50, "platform_per_session": 52.50},
    "pack_4": {"sessions": 4, "price": 600, "label": "4-Session Pack", "coach_per_session": 105.00, "platform_per_session": 45.00},
    "pack_8": {"sessions": 8, "price": 1120, "label": "8-Session Pack", "coach_per_session": 98.00, "platform_per_session": 42.00},
}


@router.get("/coaching/packs")
async def get_coaching_pack_options():
    """Return available coaching packs, prices, and 70/30 coach payout split."""
    return {"packs": COACHING_PACKS, "coach_payout": COACH_PAYOUT}


@router.get("/coaching/packs/{user_id}")
async def get_user_coaching_packs(user_id: str):
    """List a user's purchased coaching packs and remaining credits."""
    billing = load_json(DATA_DIR / "billing.json")
    packs = billing.get("coaching_packs", {}).get(user_id, [])
    total_remaining = sum(p.get("remaining", 0) for p in packs if p.get("status") == "active")
    return {
        "packs": packs,
        "total_remaining_credits": total_remaining,
    }


@router.get("/coaching/sessions/{user_id}")
async def get_coaching_sessions(user_id: str, limit: int = 20):
    """List coaching sessions (past and upcoming) for a user."""
    billing = load_json(DATA_DIR / "billing.json")
    sessions = billing.get("coaching_sessions", {}).get(user_id, [])
    # Sort by scheduled_at descending
    sessions.sort(key=lambda s: s.get("scheduled_at", ""), reverse=True)
    return {"sessions": sessions[:limit]}


@router.post("/coaching/book")
async def book_coaching_session_rest(req: BookCoachingSessionRequest):
    """Book a coaching session — deducts from pack or marks as pay-per-session."""
    billing = load_json(DATA_DIR / "billing.json")

    # Deduct from pack if specified
    pack_used = None
    if req.use_pack_id:
        user_packs = billing.get("coaching_packs", {}).get(req.user_id, [])
        for pack in user_packs:
            if pack.get("id") == req.use_pack_id and pack.get("remaining", 0) > 0:
                pack["remaining"] -= 1
                if pack["remaining"] == 0:
                    pack["status"] = "exhausted"
                pack_used = req.use_pack_id
                break
        if not pack_used:
            raise HTTPException(400, "Pack not found or no remaining credits")

    session_id = f"cs_{secrets.token_hex(8)}"
    session_record = {
        "session_id": session_id,
        "user_id": req.user_id,
        "coach_id": req.coach_id,
        "scheduled_at": req.scheduled_at,
        "status": "booked",
        "pack_id": pack_used,
        "booked_at": str(datetime.now()),
    }

    billing.setdefault("coaching_sessions", {}).setdefault(req.user_id, []).append(session_record)
    save_json(DATA_DIR / "billing.json", billing)

    return {"status": "booked", "session": session_record}


@router.post("/coaching/cancel/{session_id}")
async def cancel_coaching_session(session_id: str, req: CancelCoachingSessionRequest):
    """Cancel a booked coaching session. 24-hour cancellation policy applies."""
    billing = load_json(DATA_DIR / "billing.json")
    sessions = billing.get("coaching_sessions", {}).get(req.user_id, [])

    target = None
    for s in sessions:
        if s.get("session_id") == session_id:
            target = s
            break

    if not target:
        raise HTTPException(404, "Coaching session not found")

    if target.get("status") != "booked":
        raise HTTPException(400, f"Cannot cancel session with status: {target['status']}")

    # 24-hour cancellation policy
    scheduled = datetime.fromisoformat(target["scheduled_at"])
    if (scheduled - datetime.now()) < timedelta(hours=24):
        raise HTTPException(
            400,
            "Sessions must be cancelled at least 24 hours before the scheduled time. "
            "Late cancellations are non-refundable."
        )

    target["status"] = "cancelled"
    target["cancelled_at"] = str(datetime.now())
    target["cancel_reason"] = req.reason or ""

    # Refund pack credit if was deducted
    if target.get("pack_id"):
        user_packs = billing.get("coaching_packs", {}).get(req.user_id, [])
        for pack in user_packs:
            if pack.get("id") == target["pack_id"]:
                pack["remaining"] = pack.get("remaining", 0) + 1
                if pack.get("status") == "exhausted":
                    pack["status"] = "active"
                break

    save_json(DATA_DIR / "billing.json", billing)
    return {"status": "cancelled", "session_id": session_id, "credit_refunded": bool(target.get("pack_id"))}


# =============================================================================
# FAMILY MEMBERS — Used by Flutter billing_screens.dart
# =============================================================================


# =============================================================================
# SCHOOL CODE VERIFICATION & APPLICATION
# =============================================================================

class ApplySchoolCodeRequest(BaseModel):
    user_id: str
    school_code: str


@router.get("/verify-school-code/{code}")
async def verify_school_code(code: str, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, school_name, school_code, discount_percent,
                   max_students, current_students, active
            FROM school_codes
            WHERE school_code = $1
        """, code.strip().upper())

    if not row:
        raise HTTPException(404, "School code not found")
    if not row["active"]:
        raise HTTPException(400, "School code is no longer active")
    if row["max_students"] and row["current_students"] >= row["max_students"]:
        raise HTTPException(400, "School enrollment limit reached")

    return {
        "valid": True,
        "school_name": row["school_name"],
        "discount_percent": row["discount_percent"],
        "spots_remaining": (row["max_students"] - row["current_students"]) if row["max_students"] else None,
    }


@router.post("/apply-school-code")
async def apply_school_code(req: ApplySchoolCodeRequest, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        school = await conn.fetchrow("""
            SELECT id, school_name, discount_percent, max_students, current_students, active
            FROM school_codes WHERE school_code = $1
        """, req.school_code.strip().upper())

        if not school:
            raise HTTPException(404, "School code not found")
        if not school["active"]:
            raise HTTPException(400, "School code is no longer active")
        if school["max_students"] and school["current_students"] >= school["max_students"]:
            raise HTTPException(400, "School enrollment limit reached")

        await conn.execute("""
            UPDATE users SET school_code_id = $1, student_verified = TRUE
            WHERE hardware_id = $2
        """, school["id"], req.user_id)

        await conn.execute("""
            UPDATE school_codes SET current_students = current_students + 1
            WHERE id = $1
        """, school["id"])

    return {
        "applied": True,
        "school_name": school["school_name"],
        "discount_percent": school["discount_percent"],
    }


# =============================================================================
# CORPORATE SPONSOR CODE VERIFICATION & APPLICATION
# =============================================================================

class ApplyCorporateCodeRequest(BaseModel):
    user_id: str
    sponsor_code: str


@router.get("/verify-corporate-code/{code}")
async def verify_corporate_code(code: str, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, company_name, discount_type, discount_value,
                   pays_full, max_employees, current_employees, active
            FROM corporate_sponsors WHERE sponsor_code = $1
        """, code.strip().upper())

    if not row:
        raise HTTPException(404, "Corporate sponsor code not found")
    if not row["active"]:
        raise HTTPException(400, "Sponsor code is no longer active")
    if row["max_employees"] and row["current_employees"] >= row["max_employees"]:
        raise HTTPException(400, "Corporate enrollment limit reached")

    discount_desc = (
        "Fully sponsored" if row["pays_full"]
        else f"{row['discount_value']}% off" if row["discount_type"] == "percent"
        else f"${row['discount_value'] / 100:.2f} off"
    )

    return {
        "valid": True,
        "company_name": row["company_name"],
        "discount_description": discount_desc,
        "pays_full": row["pays_full"],
    }


@router.post("/apply-corporate-code")
async def apply_corporate_code(req: ApplyCorporateCodeRequest, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        sponsor = await conn.fetchrow("""
            SELECT id, company_name, discount_type, discount_value, pays_full,
                   max_employees, current_employees, active
            FROM corporate_sponsors WHERE sponsor_code = $1
        """, req.sponsor_code.strip().upper())

        if not sponsor:
            raise HTTPException(404, "Corporate sponsor code not found")
        if not sponsor["active"]:
            raise HTTPException(400, "Sponsor code is no longer active")
        if sponsor["max_employees"] and sponsor["current_employees"] >= sponsor["max_employees"]:
            raise HTTPException(400, "Corporate enrollment limit reached")

        enrollment = await conn.fetchrow("""
            INSERT INTO corporate_enrollments (sponsor_id, user_id, verified)
            VALUES ($1, (SELECT id FROM users WHERE hardware_id = $2 LIMIT 1), TRUE)
            RETURNING id
        """, sponsor["id"], req.user_id)

        if enrollment:
            await conn.execute("""
                UPDATE users SET corporate_enrollment_id = $1
                WHERE hardware_id = $2
            """, enrollment["id"], req.user_id)

            await conn.execute("""
                UPDATE corporate_sponsors SET current_employees = current_employees + 1
                WHERE id = $1
            """, sponsor["id"])

    return {
        "applied": True,
        "company_name": sponsor["company_name"],
        "pays_full": sponsor["pays_full"],
        "discount_type": sponsor["discount_type"],
        "discount_value": sponsor["discount_value"],
    }


# =============================================================================
# ACH DIRECT DEBIT (BANK ACCOUNT BILLING)
# =============================================================================

class ACHSetupRequest(BaseModel):
    user_id: str


class SetDefaultPaymentMethodRequest(BaseModel):
    user_id: str
    payment_method_id: str


@router.post("/ach/setup")
async def setup_ach_bank_account(req: ACHSetupRequest, request: Request):
    """Create a Stripe SetupIntent for ACH Direct Debit via Financial Connections."""
    if not STRIPE_AVAILABLE:
        raise HTTPException(503, "Stripe not available")

    pool = getattr(request.app.state, "db_pool", None)
    customer_id = None
    if pool:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT stripe_customer_id FROM users WHERE hardware_id = $1", req.user_id
            )
            if row:
                customer_id = row["stripe_customer_id"]

    if not customer_id:
        registry_path = os.path.join(os.getenv("DATA_DIR", "/app/data"), "user_registry.json")
        try:
            with open(registry_path) as f:
                registry = json.load(f)
            for _, v in registry.items():
                p = v.get("profile", {})
                if p.get("hardware_id") == req.user_id:
                    customer_id = p.get("stripe_customer_id")
                    break
        except Exception:
            pass

    if not customer_id:
        raise HTTPException(400, "No Stripe customer found for this user")

    try:
        setup_intent = stripe.SetupIntent.create(
            customer=customer_id,
            payment_method_types=["us_bank_account"],
            payment_method_options={
                "us_bank_account": {
                    "financial_connections": {
                        "permissions": ["payment_method"],
                    },
                },
            },
        )
        return {
            "client_secret": setup_intent.client_secret,
            "setup_intent_id": setup_intent.id,
        }
    except stripe.error.StripeError as e:
        raise HTTPException(400, str(e))


@router.post("/payment-method/default")
async def set_default_payment_method(req: SetDefaultPaymentMethodRequest, request: Request):
    """Set any payment method (card or bank account) as the default for invoices."""
    if not STRIPE_AVAILABLE:
        raise HTTPException(503, "Stripe not available")

    pool = getattr(request.app.state, "db_pool", None)
    customer_id = None
    if pool:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT stripe_customer_id FROM users WHERE hardware_id = $1", req.user_id
            )
            if row:
                customer_id = row["stripe_customer_id"]

    if not customer_id:
        raise HTTPException(400, "No Stripe customer found")

    try:
        stripe.Customer.modify(
            customer_id,
            invoice_settings={"default_payment_method": req.payment_method_id},
        )
        return {"default_payment_method": req.payment_method_id, "updated": True}
    except stripe.error.StripeError as e:
        raise HTTPException(400, str(e))


# =============================================================================
# SUPERBILL GENERATION (HSA/FSA/INSURANCE)
# =============================================================================

@router.get("/superbill/{user_id}")
async def generate_superbill(user_id: str, month: Optional[str] = None, request: Request = None):
    """
    Generate a superbill summary for HSA/FSA/insurance reimbursement.
    Returns structured data (PDF rendering happens on the client).
    """
    target_month = month or datetime.now().strftime("%Y-%m")

    pool = getattr(request.app.state, "db_pool", None) if request else None

    services = []
    total_cents = 0

    if pool:
        async with pool.acquire() as conn:
            user = await conn.fetchrow("""
                SELECT id, name, email FROM users WHERE hardware_id = $1
            """, user_id)

            if not user:
                raise HTTPException(404, "User not found")

            year_month = target_month.split("-")
            start_date = datetime(int(year_month[0]), int(year_month[1]), 1)
            if int(year_month[1]) == 12:
                end_date = datetime(int(year_month[0]) + 1, 1, 1)
            else:
                end_date = datetime(int(year_month[0]), int(year_month[1]) + 1, 1)

            billing_events = await conn.fetch("""
                SELECT event_type, amount_cents, description, created_at
                FROM sanctuary_billing_events
                WHERE member_id = $1
                  AND created_at >= $2 AND created_at < $3
                ORDER BY created_at
            """, user["id"], start_date, end_date)

            cpt_mapping = {
                "base_fee": {"code": "90847", "description": "Family therapy session"},
                "coaching": {"code": "90837", "description": "Individual psychotherapy, 60 min"},
                "assisted_response": {"code": "90847", "description": "Family therapy — guided response"},
                "group_coaching": {"code": "90849", "description": "Multi-family group psychotherapy"},
            }

            for evt in billing_events:
                cpt = cpt_mapping.get(evt["event_type"], {"code": "90837", "description": evt["event_type"]})
                services.append({
                    "date": evt["created_at"].strftime("%Y-%m-%d"),
                    "cpt_code": cpt["code"],
                    "description": cpt["description"],
                    "amount_cents": evt["amount_cents"],
                })
                total_cents += evt["amount_cents"]

            client_name = user["name"]
            client_email = user["email"]
    else:
        client_name = user_id
        client_email = ""

    return {
        "superbill": {
            "provider": {
                "name": "Sovereign Sanctuary LLC",
                "npi": "",
                "tax_id": "",
                "address": "",
            },
            "client": {
                "name": client_name,
                "email": client_email,
                "user_id": user_id,
            },
            "billing_period": target_month,
            "services": services,
            "total_cents": total_cents,
            "total_formatted": f"${total_cents / 100:.2f}",
            "generated_at": datetime.now().isoformat(),
            "disclaimer": (
                "This superbill is provided for informational purposes. "
                "Submit to your HSA/FSA administrator or insurance provider for reimbursement. "
                "Sovereign Sanctuary does not guarantee reimbursement."
            ),
        },
    }


# =============================================================================
# PROMOTIONAL SPECIALS — PUBLIC ENDPOINT
# =============================================================================

@router.get("/specials/active")
async def get_active_specials(request: Request):
    """Return currently active promotional specials."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        return {"specials": []}

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name, discount_type, discount_value, applicable_tiers,
                   starts_at, ends_at, promo_code, max_redemptions, current_redemptions
            FROM promotional_specials
            WHERE active = TRUE AND starts_at <= NOW() AND ends_at > NOW()
            ORDER BY ends_at ASC
        """)

    return {
        "specials": [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "discount_type": r["discount_type"],
                "discount_value": r["discount_value"],
                "applicable_tiers": r["applicable_tiers"] or [],
                "starts_at": r["starts_at"].isoformat(),
                "ends_at": r["ends_at"].isoformat(),
                "promo_code": r["promo_code"],
                "spots_left": (r["max_redemptions"] - r["current_redemptions"]) if r["max_redemptions"] else None,
            }
            for r in rows
        ],
    }


@router.get("/verify-promo/{code}")
async def verify_promo_code(code: str, request: Request):
    """Verify a promotional code and return discount details."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, name, discount_type, discount_value, applicable_tiers,
                   ends_at, max_redemptions, current_redemptions
            FROM promotional_specials
            WHERE promo_code = $1 AND active = TRUE
              AND starts_at <= NOW() AND ends_at > NOW()
        """, code.strip().upper())

    if not row:
        raise HTTPException(404, "Promo code not found or expired")
    if row["max_redemptions"] and row["current_redemptions"] >= row["max_redemptions"]:
        raise HTTPException(400, "Promo code has reached its redemption limit")

    return {
        "valid": True,
        "name": row["name"],
        "discount_type": row["discount_type"],
        "discount_value": row["discount_value"],
        "applicable_tiers": row["applicable_tiers"] or [],
        "expires": row["ends_at"].isoformat(),
    }


# =============================================================================
# COST SCHEDULE — Public-facing fee schedule for transparency
# =============================================================================

@router.get("/cost-schedule")
async def get_cost_schedule():
    """Return the full Master Cost Schedule for display in the app."""
    return {
        "tiers": {
            "COACH_ONLY": {"name": "Coach Only", "monthly": 0, "yearly": 0},
            "TRIAL": {"name": "Threshold (Trial)", "monthly": 0, "yearly": 0, "duration_days": 14},
            "STANDARD": {"name": "Inner Chamber", "monthly": 49, "yearly": 490},
            "TOP_TIER": {"name": "Sovereign Circle", "monthly": 149, "yearly": 1490},
        },
        "sanctuary_charges": {
            "base_fee": {"amount": 20.00, "description": "Per session"},
            "assisted_response": {"amount": 3.00, "description": "AI-crafted group message"},
            "coaching_first_free": {"amount": 0, "description": "First coaching per member is free"},
            "coaching_additional": {"amount": 5.00, "description": "Additional coaching sessions"},
            "group_coaching": {"amount": 20.00, "description": "Group coaching by Little Nate"},
        },
        "family_addons": FAMILY_PRICING,
        "coaching_packs": [
            {"sessions": 1, "price": 175, "per_session": 175},
            {"sessions": 4, "price": 600, "per_session": 150},
            {"sessions": 8, "price": 1120, "per_session": 140},
        ],
        "overages": OVERAGE_PRICING,
        "payment_fees": {
            "card": {"rate_percent": 2.9, "fixed_cents": 30, "description": "Credit/Debit Card"},
            "ach": {"rate_percent": 0.8, "cap_cents": 500, "description": "ACH Direct Debit (Bank Account)"},
        },
        "ach_savings_examples": [
            {"scenario": "Inner Chamber ($49/mo)", "card_fee": 1.72, "ach_fee": 0.39, "savings_monthly": 1.33, "savings_yearly": 15.96},
            {"scenario": "Sovereign Circle ($149/mo)", "card_fee": 4.62, "ach_fee": 1.19, "savings_monthly": 3.43, "savings_yearly": 41.16},
            {"scenario": "Sovereign Circle Yearly ($1,490)", "card_fee": 43.51, "ach_fee": 5.00, "savings_total": 38.51},
            {"scenario": "Family w/ 3 dependents ($229/mo)", "card_fee": 6.94, "ach_fee": 1.83, "savings_monthly": 5.11, "savings_yearly": 61.32},
        ],
    }


# =============================================================================
# FAMILY MEMBERS — Used by Flutter billing_screens.dart
# =============================================================================


@router.get("/family/members")
async def get_family_members(family_id: str):
    """
    Return all members in a family by family_id.
    Used by billing_screens.dart to display the family plan.
    """
    if not family_id:
        raise HTTPException(400, "family_id is required")

    registry = load_json(DATA_DIR / "user_registry.json")
    members = []

    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("family_id") == family_id:
            members.append({
                "id": p.get("hardware_id", k),
                "name": p.get("name", ""),
                "email": p.get("email", ""),
                "role": p.get("role", "CLIENT"),
                "subscription_plan": p.get("subscription_plan", ""),
                "subscription_status": p.get("subscription_status", ""),
                "joined_date": p.get("joined_date", ""),
            })

    return {"family_id": family_id, "members": members, "count": len(members)}
