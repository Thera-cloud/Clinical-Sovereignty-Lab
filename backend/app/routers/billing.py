"""
Billing & Subscription API Routes
Handles Stripe integration, subscription management, and payment processing.

Endpoints include: plans, subscription management (subscribe, upgrade, downgrade),
coaching sessions and packs, payment methods, invoices, and token usage.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any

from app.auth import get_current_user
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
    dependencies=[Depends(get_current_user)],
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
            methods = stripe.PaymentMethod.list(
                customer=stripe_customer,
                type="card",
            )
            return {
                "payment_methods": [
                    {
                        "id": pm.id,
                        "brand": pm.card.brand,
                        "last4": pm.card.last4,
                        "exp_month": pm.card.exp_month,
                        "exp_year": pm.card.exp_year,
                        "is_default": pm.id == (
                            stripe.Customer.retrieve(stripe_customer)
                            .invoice_settings.get("default_payment_method")
                        ),
                    }
                    for pm in methods.data
                ]
            }
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
