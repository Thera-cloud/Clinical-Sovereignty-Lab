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
from app.services.api_server import require_admin, require_coach, get_current_user
from datetime import datetime, timedelta
import logging
import os
import json
import secrets
from pathlib import Path

from app.services.pg_data_helpers import (
    find_user_pg,
    get_subscription_pg,
    get_transactions_pg,
    update_user_field_pg,
)

logger = logging.getLogger("billing_router")

PLAN_CHANGE_COOLDOWN_HOURS = 24

_TIER_ALIAS_MAP = {
    "SOVEREIGN_CIRCLE": "TOP_TIER", "SOVEREIGN": "TOP_TIER", "TOP": "TOP_TIER",
    "INNER_CHAMBER": "STANDARD", "INNER": "STANDARD", "THRESHOLD": "TRIAL",
}
_TIER_DB_MAP = {
    "COACH_ONLY": "STANDARD", "TRIAL": "TRIAL", "STANDARD": "STANDARD",
    "TOP_TIER": "TOP_TIER", "DEPENDENT": "DEPENDENT",
    "FAMILY_MEMBER": "STANDARD", "FAMILY_DEPENDENT": "DEPENDENT",
}

def _normalize_tier(raw: str) -> str:
    upper = (raw or "").strip().upper()
    return _TIER_ALIAS_MAP.get(upper, upper)

def _tier_for_db(plan: str) -> str:
    return _TIER_DB_MAP.get(_normalize_tier(plan), "STANDARD")


def _can_access_nate(plan: str) -> bool:
    """COACH_ONLY users cannot access Nate AI; all other plans can."""
    return _normalize_tier(plan) != "COACH_ONLY"


def _verify_ownership(req_user_id: str, auth_user_id: str) -> None:
    """Raise 403 if the authenticated user is trying to act on another user's account."""
    if req_user_id != auth_user_id:
        raise HTTPException(
            403,
            "You can only modify your own account. "
            f"Authenticated as {auth_user_id[:8]}…, target is {req_user_id[:8]}…",
        )


async def _check_plan_change_cooldown(pool, user_id: str) -> None:
    """Raise 429 if the user changed plans within the cooldown window."""
    if not pool:
        return
    try:
        row = await pool.fetchrow(
            """SELECT profile_data->>'plan_changed_at' AS changed_at
               FROM users WHERE hardware_id = $1 AND deleted_at IS NULL LIMIT 1""",
            user_id,
        )
        if row and row["changed_at"]:
            try:
                last_change = datetime.fromisoformat(row["changed_at"])
                hours_since = (datetime.now() - last_change).total_seconds() / 3600
                if hours_since < PLAN_CHANGE_COOLDOWN_HOURS:
                    remaining = PLAN_CHANGE_COOLDOWN_HOURS - hours_since
                    raise HTTPException(
                        429,
                        f"Plan changes are limited to once every {PLAN_CHANGE_COOLDOWN_HOURS}h. "
                        f"Try again in {remaining:.0f}h.",
                    )
            except (ValueError, TypeError):
                pass
    except HTTPException:
        raise
    except Exception as e:
        logger.debug("_check_plan_change_cooldown: %s", e)


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

_STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")

if STRIPE_AVAILABLE:
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")


@router.get("/config")
async def billing_config():
    """Return non-secret billing configuration for frontend Stripe.js initialization."""
    return {
        "publishable_key": _STRIPE_PUBLISHABLE_KEY,
        "stripe_available": STRIPE_AVAILABLE and bool(stripe.api_key) if STRIPE_AVAILABLE else False,
    }


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
    except Exception as e:
        logger.warning("load_json(%s): %s", filepath, e)
        return default

def save_json(filepath: Path, data):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w') as f: json.dump(data, f, indent=2, default=str)

@router.get("/plans")
async def get_plans():
    return {"plans": PLAN_DETAILS, "family_pricing": FAMILY_PRICING, "overages": OVERAGE_PRICING}

@router.get("/subscription/{user_id}")
async def get_subscription(user_id: str, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool:
        try:
            sub = await get_subscription_pg(pool, user_id)
            if sub:
                plan_key = sub.get("plan", "TRIAL")
                return {"subscription": sub, "details": PLAN_DETAILS.get(plan_key, PLAN_DETAILS.get("TRIAL"))}
        except Exception as e:
            logger.warning("get_subscription: PG read failed for %s: %s", user_id, e)

    # JSON fallback
    billing = load_json(DATA_DIR / "billing.json")
    sub = billing.get("subscriptions", {}).get(user_id)
    if not sub:
        return {"plan": "TRIAL", "status": "TRIAL_ACTIVE", "details": PLAN_DETAILS["TRIAL"]}
    return {"subscription": sub, "details": PLAN_DETAILS.get(sub.get("plan", "STANDARD"))}

@router.post("/subscribe")
async def create_subscription(
    req: SubscriptionRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):

    if req.plan not in PLAN_DETAILS:
        raise HTTPException(400, "Invalid plan")

    pool = getattr(request.app.state, "db_pool", None)
    await _check_plan_change_cooldown(pool, req.user_id)

    plan = PLAN_DETAILS[req.plan]
    sub = {
        "user_id": req.user_id,
        "plan": req.plan,
        "status": "active",
        "tokens_included": plan["tokens"],
        "start_date": str(datetime.now().date()),
        "end_date": str((datetime.now() + timedelta(days=30)).date()),
        "created_at": str(datetime.now())
    }

    canonical_sub = _normalize_tier(req.plan)

    if pool:
        try:
            await update_user_field_pg(pool, req.user_id, {
                "tier": _tier_for_db(canonical_sub),
                "subscription_status": "ACTIVE",
                "token_balance": plan["tokens"],
                "subscription_plan": canonical_sub,
                "subscription_start_date": sub["start_date"],
                "subscription_end_date": sub["end_date"],
                "can_access_nate": _can_access_nate(canonical_sub),
                "plan_changed_at": str(datetime.now()),
            })
        except Exception as e:
            logger.warning("create_subscription: PG update failed for %s: %s", req.user_id, e)

    # JSON backup writes
    billing = load_json(DATA_DIR / "billing.json")
    billing.setdefault("subscriptions", {})[req.user_id] = sub
    save_json(DATA_DIR / "billing.json", billing)

    registry = load_json(DATA_DIR / "user_registry.json")
    for k, v in registry.items():
        if v.get("profile", {}).get("hardware_id") == req.user_id:
            v["profile"]["subscription_plan"] = canonical_sub
            v["profile"]["tier"] = _tier_for_db(canonical_sub)
            v["profile"]["subscription_status"] = "ACTIVE"
            v["profile"]["token_balance"] = plan["tokens"]
            v["profile"]["can_access_nate"] = _can_access_nate(canonical_sub)
            save_json(DATA_DIR / "user_registry.json", registry)
            break

    return {"subscription": sub}

@router.get("/usage/{user_id}")
async def get_usage(user_id: str, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool:
        try:
            profile = await find_user_pg(pool, user_id)
            if profile:
                pd = profile
                return {
                    "token_balance": pd.get("token_balance", 0),
                    "tokens_used_today": pd.get("token_usage_today", 0),
                    "tokens_used_month": pd.get("token_usage_month", 0),
                    "plan": pd.get("tier") or pd.get("subscription_plan", "TRIAL"),
                }
        except Exception as e:
            logger.warning("get_usage: PG read failed for %s: %s", user_id, e)

    # JSON fallback
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
async def use_tokens(
    req: UsageRequest,
    request: Request,
    auth_user_id: str = Depends(get_current_user_id),
):
    _verify_ownership(req.user_id, auth_user_id)
    pool = getattr(request.app.state, "db_pool", None)
    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT token_balance FROM users WHERE hardware_id = $1 AND deleted_at IS NULL LIMIT 1",
                    req.user_id,
                )
                if row:
                    balance = row["token_balance"] or 0
                    if balance < req.tokens:
                        raise HTTPException(402, "Insufficient tokens")
                    new_balance = balance - req.tokens
                    await conn.execute(
                        """UPDATE users SET
                               token_balance = $1::int,
                               profile_data = jsonb_set(
                                   jsonb_set(
                                       jsonb_set(
                                           COALESCE(profile_data, '{}'::jsonb),
                                           '{token_balance}', to_jsonb($1::int)
                                       ),
                                       '{token_usage_today}',
                                       to_jsonb((COALESCE((profile_data->>'token_usage_today')::int, 0) + $2::int)::int)
                                   ),
                                   '{token_usage_month}',
                                   to_jsonb((COALESCE((profile_data->>'token_usage_month')::int, 0) + $2::int)::int)
                               ),
                               updated_at = NOW()
                           WHERE hardware_id = $3""",
                        new_balance, req.tokens, req.user_id,
                    )
                    return {"remaining": new_balance}
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("use_tokens: PG update failed for %s: %s", req.user_id, e)

    # JSON fallback
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
async def get_transactions(user_id: str, request: Request, limit: int = 20):
    pool = getattr(request.app.state, "db_pool", None)
    if pool:
        try:
            async with pool.acquire() as conn:
                username_row = await conn.fetchrow(
                    "SELECT username FROM users WHERE hardware_id = $1 AND deleted_at IS NULL LIMIT 1",
                    user_id,
                )
            if username_row:
                txns = await get_transactions_pg(pool, username_row["username"], limit)
                if txns is not None:
                    return {"transactions": txns}
        except Exception as e:
            logger.warning("get_transactions: PG read failed for %s: %s", user_id, e)

    # JSON fallback
    billing = load_json(DATA_DIR / "billing.json")
    txns = [t for t in billing.get("transactions", []) if t.get("user_id") == user_id]
    return {"transactions": txns[-limit:]}


# =========================================================================
# Upgrade / Downgrade
# =========================================================================

TIER_ORDER = ["COACH_ONLY", "TRIAL", "STANDARD", "TOP_TIER"]


async def _find_user_profile(user_id: str, db_pool=None):
    """Return (registry dict, key, profile dict) or raise 404.

    Tries PostgreSQL first (via find_user_pg), falls back to JSON registry.
    When PG succeeds, registry/key are returned as None since the caller
    only needs the profile for reads — JSON writes still load fresh.
    """
    if db_pool:
        try:
            profile = await find_user_pg(db_pool, user_id)
            if profile:
                return None, None, profile
        except Exception as e:
            logger.warning("_find_user_profile: PG lookup failed for %s: %s", user_id, e)

    # JSON fallback
    registry = load_json(DATA_DIR / "user_registry.json")
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("hardware_id") == user_id:
            return registry, k, p
    raise HTTPException(404, "User not found")


async def _get_stripe_customer(user_id: str, db_pool=None) -> Optional[str]:
    """Retrieve Stripe customer ID — PG first, then billing.json, then JSON registry."""
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT profile_data->>'stripe_customer_id' as stripe_cid
                       FROM users WHERE hardware_id = $1 AND deleted_at IS NULL LIMIT 1""",
                    user_id,
                )
                if row and row["stripe_cid"]:
                    return row["stripe_cid"]
        except Exception as e:
            logger.warning("_get_stripe_customer: PG lookup failed for %s: %s", user_id, e)

    # JSON fallback: billing.json
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
async def upgrade_subscription(
    req: UpgradeDowngradeRequest,
    request: Request,
    auth_user_id: str = Depends(get_current_user_id),
):
    """Change plan upward."""
    _verify_ownership(req.user_id, auth_user_id)

    if req.new_plan not in PLAN_DETAILS:
        raise HTTPException(400, f"Invalid plan: {req.new_plan}")

    pool = getattr(request.app.state, "db_pool", None)
    await _check_plan_change_cooldown(pool, req.user_id)

    registry, rk, profile = await _find_user_profile(req.user_id, db_pool=pool)
    current_plan = _normalize_tier(profile.get("subscription_plan") or profile.get("tier") or "TRIAL")
    new_idx = TIER_ORDER.index(req.new_plan) if req.new_plan in TIER_ORDER else -1
    cur_idx = TIER_ORDER.index(current_plan) if current_plan in TIER_ORDER else -1

    if new_idx <= cur_idx:
        raise HTTPException(400, "New plan must be higher tier. Use /subscription/downgrade instead.")

    new_details = PLAN_DETAILS[req.new_plan]
    canonical_plan = _normalize_tier(req.new_plan)

    # Token balance: use max(current, plan_default) to prevent losing purchased tokens,
    # but only grant new allocation if current balance is below plan default.
    current_balance = profile.get("token_balance", 0)
    safe_balance = max(current_balance, new_details["tokens"])

    stripe_customer = await _get_stripe_customer(req.user_id, db_pool=pool)
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
            logger.warning("upgrade_subscription: Stripe failed for %s: %s", req.user_id, e)

    now_str = str(datetime.now())

    if pool:
        try:
            await update_user_field_pg(pool, req.user_id, {
                "tier": _tier_for_db(canonical_plan),
                "subscription_status": "ACTIVE",
                "token_balance": safe_balance,
                "subscription_plan": canonical_plan,
                "can_access_nate": _can_access_nate(canonical_plan),
                "plan_changed_at": now_str,
                "previous_plan": current_plan,
            })
        except Exception as e:
            logger.warning("upgrade_subscription: PG update failed for %s: %s", req.user_id, e)

    if registry is not None:
        profile["subscription_plan"] = canonical_plan
        profile["tier"] = _tier_for_db(canonical_plan)
        profile["subscription_status"] = "ACTIVE"
        profile["token_balance"] = safe_balance
        profile["can_access_nate"] = _can_access_nate(canonical_plan)
        profile["plan_changed_at"] = now_str
        save_json(DATA_DIR / "user_registry.json", registry)

    billing = load_json(DATA_DIR / "billing.json")
    billing.setdefault("subscriptions", {})[req.user_id] = {
        "user_id": req.user_id,
        "plan": req.new_plan,
        "status": "active",
        "tokens_included": new_details["tokens"],
        "previous_plan": current_plan,
        "changed_at": now_str,
        "stripe_updated": stripe_updated,
    }
    billing.setdefault("transactions", []).append({
        "user_id": req.user_id,
        "type": "upgrade",
        "from_plan": current_plan,
        "to_plan": req.new_plan,
        "timestamp": now_str,
    })
    save_json(DATA_DIR / "billing.json", billing)

    return {
        "status": "upgraded",
        "plan": req.new_plan,
        "stripe_updated": stripe_updated,
        "details": new_details,
        "token_balance": safe_balance,
    }


@router.post("/subscription/downgrade")
async def downgrade_subscription(
    req: UpgradeDowngradeRequest,
    request: Request,
    auth_user_id: str = Depends(get_current_user_id),
):
    """Change plan downward — deferred to billing cycle end (matches bridge behavior)."""
    _verify_ownership(req.user_id, auth_user_id)

    if req.new_plan not in PLAN_DETAILS:
        raise HTTPException(400, f"Invalid plan: {req.new_plan}")

    pool = getattr(request.app.state, "db_pool", None)
    await _check_plan_change_cooldown(pool, req.user_id)

    registry, rk, profile = await _find_user_profile(req.user_id, db_pool=pool)
    current_plan = _normalize_tier(profile.get("subscription_plan") or profile.get("tier") or "TRIAL")
    new_idx = TIER_ORDER.index(req.new_plan) if req.new_plan in TIER_ORDER else -1
    cur_idx = TIER_ORDER.index(current_plan) if current_plan in TIER_ORDER else -1

    if new_idx >= cur_idx:
        raise HTTPException(400, "New plan must be lower tier. Use /subscription/upgrade instead.")

    new_details = PLAN_DETAILS[req.new_plan]
    canonical_down = _normalize_tier(req.new_plan)
    now = datetime.now()
    now_str = str(now)

    # Determine billing cycle end — downgrade takes effect then
    cycle_end = now + timedelta(days=30)
    if pool:
        try:
            row = await pool.fetchrow(
                """SELECT profile_data->>'billing_cycle_end' AS bce
                   FROM users WHERE hardware_id = $1 AND deleted_at IS NULL LIMIT 1""",
                req.user_id,
            )
            if row and row["bce"]:
                try:
                    parsed_end = datetime.strptime(row["bce"], "%Y-%m-%d")
                    if parsed_end > now:
                        cycle_end = parsed_end
                except (ValueError, TypeError):
                    pass
        except Exception:
            pass

    stripe_customer = await _get_stripe_customer(req.user_id, db_pool=pool)
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
            logger.warning("downgrade_subscription: Stripe failed for %s: %s", req.user_id, e)

    # Deferred downgrade: keep current plan, set pending_plan for cycle end
    if pool:
        try:
            await update_user_field_pg(pool, req.user_id, {
                "pending_plan": canonical_down,
                "pending_plan_effective": str(cycle_end.date()),
                "plan_changed_at": now_str,
                "previous_plan": current_plan,
            })
        except Exception as e:
            logger.warning("downgrade_subscription: PG update failed for %s: %s", req.user_id, e)

    if registry is not None:
        profile["pending_plan"] = canonical_down
        profile["pending_plan_effective"] = str(cycle_end.date())
        profile["plan_changed_at"] = now_str
        save_json(DATA_DIR / "user_registry.json", registry)

    billing = load_json(DATA_DIR / "billing.json")
    billing.setdefault("subscriptions", {})[req.user_id] = {
        "user_id": req.user_id,
        "plan": current_plan,
        "pending_plan": canonical_down,
        "pending_effective": str(cycle_end.date()),
        "status": "active",
        "tokens_included": new_details["tokens"],
        "previous_plan": current_plan,
        "changed_at": now_str,
        "stripe_updated": stripe_updated,
    }
    billing.setdefault("transactions", []).append({
        "user_id": req.user_id,
        "type": "downgrade_scheduled",
        "from_plan": current_plan,
        "to_plan": req.new_plan,
        "effective_date": str(cycle_end.date()),
        "timestamp": now_str,
    })
    save_json(DATA_DIR / "billing.json", billing)

    return {
        "status": "downgrade_scheduled",
        "current_plan": current_plan,
        "pending_plan": canonical_down,
        "effective_date": str(cycle_end.date()),
        "stripe_updated": stripe_updated,
        "details": new_details,
    }


# =========================================================================
# Invoices
# =========================================================================

@router.get("/invoices/{user_id}")
async def get_invoices(user_id: str, request: Request, limit: int = 20):
    """Return invoice list. Checks Stripe first, falls back to PG transactions, then JSON."""
    pool = getattr(request.app.state, "db_pool", None)

    # Try Stripe
    if STRIPE_AVAILABLE and stripe.api_key:
        stripe_customer = await _get_stripe_customer(user_id, db_pool=pool)
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
                logger.warning("get_invoices: Stripe fetch failed for %s: %s", user_id, e)

    # PG fallback: token_transactions
    if pool:
        try:
            async with pool.acquire() as conn:
                username_row = await conn.fetchrow(
                    "SELECT username FROM users WHERE hardware_id = $1 AND deleted_at IS NULL LIMIT 1",
                    user_id,
                )
            if username_row:
                txns = await get_transactions_pg(pool, username_row["username"], limit)
                if txns:
                    return {"source": "pg", "invoices": txns}
        except Exception as e:
            logger.warning("get_invoices: PG fallback failed for %s: %s", user_id, e)

    # JSON fallback
    billing = load_json(DATA_DIR / "billing.json")
    txns = [t for t in billing.get("transactions", []) if t.get("user_id") == user_id]
    return {"source": "local", "invoices": txns[-limit:]}


# =========================================================================
# Payment Methods
# =========================================================================

@router.get("/payment-methods/{user_id}")
async def list_payment_methods(user_id: str, request: Request):
    """List saved payment methods from Stripe."""
    pool = getattr(request.app.state, "db_pool", None)
    stripe_customer = await _get_stripe_customer(user_id, db_pool=pool)

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
            except Exception as e:
                logger.warning("list_payment_methods: bank account listing failed: %s", e)
            return {"payment_methods": result}
        except Exception as e:
            logger.warning("list_payment_methods: Stripe fetch failed: %s", e)
            raise HTTPException(502, f"Failed to retrieve payment methods: {e}")

    return {"payment_methods": [], "note": "Stripe not configured or no customer linked"}


@router.post("/payment-methods")
async def attach_payment_method(req: PaymentMethodAttachRequest, request: Request):
    """Attach a new payment method to the user's Stripe customer and set as default."""
    pool = getattr(request.app.state, "db_pool", None)
    stripe_customer = await _get_stripe_customer(req.user_id, db_pool=pool)
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
async def detach_payment_method(
    pm_id: str,
    request: Request,
    auth_user_id: str = Depends(get_current_user_id),
):
    """Detach a payment method from the authenticated user's Stripe customer."""
    if not STRIPE_AVAILABLE or not stripe.api_key:
        raise HTTPException(503, "Stripe is not configured")

    try:
        pm = stripe.PaymentMethod.retrieve(pm_id)
        if pm.customer:
            pool = getattr(request.app.state, "db_pool", None)
            if pool:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT profile_data->>'stripe_customer_id' as cid FROM users WHERE username = $1",
                        auth_user_id,
                    )
                    if row and row["cid"] and row["cid"] != pm.customer:
                        raise HTTPException(403, "Payment method does not belong to your account")

        stripe.PaymentMethod.detach(pm_id)
        return {"status": "detached", "payment_method_id": pm_id}
    except HTTPException:
        raise
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

import re as _re_billing
import time as _time_billing

_CODE_PATTERN = _re_billing.compile(r'^[A-Z0-9_\-]{2,40}$')
_verify_rate_limiter: Dict[str, list] = {}
_VERIFY_WINDOW = 60
_VERIFY_MAX_ATTEMPTS = 10


def _rate_check_verify(key: str) -> bool:
    """Return True if rate limit exceeded (10 attempts per 60s per key)."""
    now = _time_billing.time()
    window = _verify_rate_limiter.setdefault(key, [])
    _verify_rate_limiter[key] = [t for t in window if now - t < _VERIFY_WINDOW]
    if len(_verify_rate_limiter[key]) >= _VERIFY_MAX_ATTEMPTS:
        return True
    _verify_rate_limiter[key].append(now)
    return False


def _sanitize_code(code: str) -> str:
    """Normalize and validate discount code format."""
    cleaned = code.strip().upper()[:40]
    if not _CODE_PATTERN.match(cleaned):
        raise HTTPException(400, "Invalid code format")
    return cleaned


class ApplySchoolCodeRequest(BaseModel):
    school_code: str


@router.get("/verify-school-code/{code}")
async def verify_school_code(code: str, request: Request,
                             caller: str = Depends(get_current_user_id)):
    if _rate_check_verify(f"school:{caller}"):
        raise HTTPException(429, "Too many verification attempts")
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    safe_code = _sanitize_code(code)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, school_name, school_code, discount_percent,
                   max_students, current_students, active
            FROM school_codes
            WHERE school_code = $1 AND active = TRUE
        """, safe_code)

    if not row:
        raise HTTPException(404, "Invalid or expired code")
    if row["max_students"] and row["current_students"] >= row["max_students"]:
        raise HTTPException(404, "Invalid or expired code")

    return {
        "valid": True,
        "school_name": row["school_name"],
        "discount_percent": row["discount_percent"],
        "spots_remaining": (row["max_students"] - row["current_students"]) if row["max_students"] else None,
    }


@router.post("/apply-school-code")
async def apply_school_code(req: ApplySchoolCodeRequest, request: Request,
                            caller: str = Depends(get_current_user_id)):
    """Apply a school code to the authenticated caller's account."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    safe_code = _sanitize_code(req.school_code)
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Atomic check-and-increment with row lock
            school = await conn.fetchrow("""
                SELECT id, school_name, discount_percent, max_students, current_students, active
                FROM school_codes WHERE school_code = $1 AND active = TRUE
                FOR UPDATE
            """, safe_code)

            if not school:
                raise HTTPException(404, "Invalid or expired code")
            if school["max_students"] and school["current_students"] >= school["max_students"]:
                raise HTTPException(400, "Enrollment limit reached")

            # Idempotency: skip if caller already enrolled
            already = await conn.fetchval("""
                SELECT school_code_id FROM users WHERE hardware_id = $1
            """, caller)
            if already == school["id"]:
                return {"applied": True, "school_name": school["school_name"],
                        "discount_percent": school["discount_percent"], "already_enrolled": True}

            await conn.execute("""
                UPDATE users SET school_code_id = $1, student_verified = TRUE
                WHERE hardware_id = $2
            """, school["id"], caller)

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
    sponsor_code: str


@router.get("/verify-corporate-code/{code}")
async def verify_corporate_code(code: str, request: Request,
                                caller: str = Depends(get_current_user_id)):
    if _rate_check_verify(f"corp:{caller}"):
        raise HTTPException(429, "Too many verification attempts")
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    safe_code = _sanitize_code(code)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, company_name, discount_type, discount_value,
                   pays_full, max_employees, current_employees, active
            FROM corporate_sponsors WHERE sponsor_code = $1 AND active = TRUE
        """, safe_code)

    if not row:
        raise HTTPException(404, "Invalid or expired code")
    if row["max_employees"] and row["current_employees"] >= row["max_employees"]:
        raise HTTPException(404, "Invalid or expired code")

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
async def apply_corporate_code(req: ApplyCorporateCodeRequest, request: Request,
                               caller: str = Depends(get_current_user_id)):
    """Apply a corporate sponsor code to the authenticated caller's account."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    safe_code = _sanitize_code(req.sponsor_code)
    async with pool.acquire() as conn:
        async with conn.transaction():
            sponsor = await conn.fetchrow("""
                SELECT id, company_name, discount_type, discount_value, pays_full,
                       max_employees, current_employees, active,
                       COALESCE(platform_tier, 'starter') as platform_tier,
                       COALESCE(subsidy_percentage, 100) as subsidy_percentage,
                       COALESCE(allowed_employee_tier, 'STANDARD') as allowed_employee_tier
                FROM corporate_sponsors WHERE sponsor_code = $1 AND active = TRUE
                FOR UPDATE
            """, safe_code)

            if not sponsor:
                raise HTTPException(404, "Invalid or expired code")
            if sponsor["max_employees"] and sponsor["current_employees"] >= sponsor["max_employees"]:
                raise HTTPException(400, "Enrollment limit reached")

            # Idempotency: check if already enrolled under this sponsor
            caller_uuid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1", caller)
            if not caller_uuid:
                raise HTTPException(404, "User not found")

            existing = await conn.fetchval("""
                SELECT id FROM corporate_enrollments
                WHERE sponsor_id = $1 AND user_id = $2
            """, sponsor["id"], caller_uuid)
            if existing:
                return {"applied": True, "company_name": sponsor["company_name"],
                        "pays_full": sponsor["pays_full"], "already_enrolled": True}

            enrollment = await conn.fetchrow("""
                INSERT INTO corporate_enrollments (sponsor_id, user_id, verified)
                VALUES ($1, $2, TRUE) RETURNING id
            """, sponsor["id"], caller_uuid)

            if enrollment:
                await conn.execute("""
                    UPDATE users SET corporate_enrollment_id = $1
                    WHERE hardware_id = $2
                """, enrollment["id"], caller)

                await conn.execute("""
                    UPDATE corporate_sponsors SET current_employees = current_employees + 1
                    WHERE id = $1
                """, sponsor["id"])

    from app.services.stripe_integration import calculate_subsidized_rate
    subsidy_info = calculate_subsidized_rate(
        sponsor["allowed_employee_tier"],
        sponsor["subsidy_percentage"],
    )

    return {
        "applied": True,
        "company_name": sponsor["company_name"],
        "pays_full": sponsor["pays_full"],
        "discount_type": sponsor["discount_type"],
        "discount_value": sponsor["discount_value"],
        "subsidy": subsidy_info,
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
async def verify_promo_code(code: str, request: Request,
                            tier: Optional[str] = None,
                            caller: str = Depends(get_current_user_id)):
    """Verify a promotional code and return discount details."""
    if _rate_check_verify(f"promo:{caller}"):
        raise HTTPException(429, "Too many verification attempts")
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    safe_code = _sanitize_code(code)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, name, discount_type, discount_value, applicable_tiers,
                   ends_at, max_redemptions, current_redemptions
            FROM promotional_specials
            WHERE promo_code = $1 AND active = TRUE
              AND starts_at <= NOW() AND ends_at > NOW()
        """, safe_code)

    if not row:
        raise HTTPException(404, "Invalid or expired code")
    if row["max_redemptions"] and row["current_redemptions"] >= row["max_redemptions"]:
        raise HTTPException(404, "Invalid or expired code")
    allowed_tiers = row["applicable_tiers"] or []
    if isinstance(allowed_tiers, str):
        try:
            allowed_tiers = json.loads(allowed_tiers)
        except Exception:
            allowed_tiers = []
    if not isinstance(allowed_tiers, list):
        allowed_tiers = []
    allowed_norm = {_normalize_tier(str(t)) for t in allowed_tiers if str(t).strip()}
    if allowed_norm:
        if not tier or not str(tier).strip():
            raise HTTPException(
                400,
                "This promo code is limited to specific subscription tiers; open billing from the app with your current plan, or contact support.",
            )
        norm_tier = _normalize_tier(str(tier))
        if norm_tier not in allowed_norm:
            raise HTTPException(400, "Promo code is not valid for this subscription tier")

    return {
        "valid": True,
        "name": row["name"],
        "discount_type": row["discount_type"],
        "discount_value": row["discount_value"],
        "applicable_tiers": allowed_tiers,
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
async def get_family_members(family_id: str, request: Request):
    """
    Return all members in a family by family_id.
    Used by billing_screens.dart to display the family plan.
    """
    if not family_id:
        raise HTTPException(400, "family_id is required")

    pool = getattr(request.app.state, "db_pool", None)
    if pool:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT hardware_id, username, name, email, role,
                              tier, subscription_status, profile_data
                       FROM users
                       WHERE (family_id::text = $1
                              OR profile_data->>'family_id' = $1)
                         AND deleted_at IS NULL
                       ORDER BY name""",
                    family_id,
                )
                members = []
                for r in rows:
                    pd = r.get("profile_data") or {}
                    if isinstance(pd, str):
                        try:
                            pd = json.loads(pd)
                        except Exception:
                            pd = {}
                    members.append({
                        "id": r.get("hardware_id") or r["username"],
                        "name": r.get("name") or "",
                        "email": r.get("email") or "",
                        "role": r.get("role") or "CLIENT",
                        "subscription_plan": r.get("tier") or pd.get("subscription_plan", ""),
                        "subscription_status": r.get("subscription_status") or "",
                        "joined_date": pd.get("joined_date", ""),
                    })
                return {"family_id": family_id, "members": members, "count": len(members)}
        except Exception as e:
            logger.warning("get_family_members: PG read failed for family %s: %s", family_id, e)

    # JSON fallback
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


class FamilyMemberCheckoutRequest(BaseModel):
    dependent_username: str
    ordinal: int
    success_url: Optional[str] = "https://app.sovereignsanctuary.net/payment-complete"
    cancel_url: Optional[str] = "https://app.sovereignsanctuary.net/payment-cancelled"


@router.post("/checkout/family-member")
async def checkout_family_member(req: FamilyMemberCheckoutRequest, request: Request,
                                 caller: str = Depends(get_current_user_id)):
    """Create Stripe checkout for a family member add-on subscription."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    from app.services.stripe_integration import StripeService, family_tier_price_cents, PRICES

    async with pool.acquire() as conn:
        hoh = await conn.fetchrow(
            "SELECT id::text as uid, username, profile_data->>'email' as email, "
            "profile_data->>'name' as name, profile_data->>'stripe_customer_id' as stripe_cid "
            "FROM users WHERE username = $1",
            caller,
        )
        if not hoh:
            raise HTTPException(404, "Head of household not found")

        dep = await conn.fetchrow(
            "SELECT id::text as uid, username, name FROM users WHERE username = $1",
            req.dependent_username,
        )
        if not dep:
            raise HTTPException(404, f"Dependent {req.dependent_username} not found")

    price_cents = family_tier_price_cents(req.ordinal)
    price_id = PRICES.get(f"FAMILY_TIER_{req.ordinal}") or PRICES.get("FAMILY_MEMBER")

    import stripe as _stripe
    _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    if not _stripe.api_key:
        raise HTTPException(503, "Stripe not configured")

    svc = StripeService(pool)
    customer_id = await svc.get_or_create_customer(
        hoh["uid"], hoh["email"] or "", hoh["name"] or caller
    )

    checkout_params = {
        "customer": customer_id,
        "mode": "subscription",
        "success_url": req.success_url,
        "cancel_url": req.cancel_url,
        "metadata": {
            "type": "family_member",
            "hoh_username": caller,
            "dependent_username": req.dependent_username,
            "ordinal": str(req.ordinal),
        },
    }

    if price_id:
        checkout_params["line_items"] = [{"price": price_id, "quantity": 1}]
    else:
        checkout_params["line_items"] = [{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"Family Member Add-On (Slot {req.ordinal})"},
                "unit_amount": price_cents,
                "recurring": {"interval": "month"},
            },
            "quantity": 1,
        }]

    session = _stripe.checkout.Session.create(**checkout_params)

    return {"checkout_url": session.url, "session_id": session.id, "price_cents": price_cents}


# ---------------------------------------------------------------------------
# Token Pack Purchases
# ---------------------------------------------------------------------------

class TokenPackPurchase(BaseModel):
    pack_id: str
    username: str
    email: Optional[str] = None
    success_url: Optional[str] = "https://app.sovereignsanctuary.net/payment-complete"
    cancel_url: Optional[str] = "https://app.sovereignsanctuary.net/payment-cancelled"


@router.get("/token-packs")
async def get_token_packs():
    """Available token packs for purchase."""
    from app.services.stripe_integration import TOKEN_PACKS
    return [
        {
            "id": pack_id,
            "label": pack["label"],
            "tokens": pack["tokens"],
            "price_cents": pack["price_cents"],
            "price_display": f"${pack['price_cents'] / 100:.2f}",
        }
        for pack_id, pack in TOKEN_PACKS.items()
    ]


# COMPAT: kept for iOS build <= 1.0.0 — old URL + field names
@router.post("/token-pack/checkout")
async def purchase_token_pack_compat(request: Request, user: dict = Depends(get_current_user)):
    """Shim for iOS binary that sends {pack} to the old URL."""
    body = await request.json()
    pack_id = body.get("pack") or body.get("pack_id", "")
    username = user.get("username", "")
    compat_req = TokenPackPurchase(
        pack_id=pack_id, username=username,
        success_url=body.get("success_url"), cancel_url=body.get("cancel_url"),
    )
    return await purchase_token_pack(compat_req, request)


@router.post("/token-packs/purchase")
async def purchase_token_pack(req: TokenPackPurchase, request: Request):
    """Create Stripe checkout session for a token pack."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    from app.services.stripe_integration import StripeService, TOKEN_PACKS
    if req.pack_id not in TOKEN_PACKS:
        raise HTTPException(400, f"Invalid pack: {req.pack_id}")

    svc = StripeService(pool)
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id::text as uid, profile_data->>'email' as email, profile_data->>'name' as name FROM users WHERE username = $1",
            req.username,
        )
        if not user:
            raise HTTPException(404, f"User {req.username} not found")

    result = await svc.purchase_token_pack(
        user_id=user["uid"],
        username=req.username,
        email=req.email or user["email"] or "",
        name=user["name"] or req.username,
        pack_id=req.pack_id,
        success_url=req.success_url,
        cancel_url=req.cancel_url,
    )
    return {"checkout_url": result.checkout_url, "session_id": result.session_id}


# ---------------------------------------------------------------------------
# Client-facing token usage (for Token Vault)
# ---------------------------------------------------------------------------

@router.get("/my-token-usage")
async def get_my_token_usage(request: Request, days: int = 30):
    """Current user's token balance, daily/monthly usage, and per-source breakdown."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    user = getattr(request.state, "user", None) or {}
    username = user.get("username", "")
    if not username:
        auth_header = request.headers.get("authorization", "")
        x_user = request.headers.get("x-user-id", "")
        if x_user:
            username = x_user

    if not username:
        raise HTTPException(401, "Cannot determine user identity")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT username, COALESCE(token_balance, 0) as token_balance,
                   COALESCE((profile_data->>'token_usage_today')::int, 0) as usage_today,
                   COALESCE((profile_data->>'token_usage_month')::int, 0) as usage_month
            FROM users WHERE username = $1
        """, username)

        if not row:
            return {"token_balance": 0, "usage_today": 0, "usage_month": 0, "by_source": []}

        from datetime import timezone, timedelta as td
        cutoff = datetime.now(timezone.utc) - td(days=days)
        by_source = await conn.fetch("""
            SELECT COALESCE(source, 'unknown') as source,
                   SUM(ABS(amount)) as total_tokens
            FROM token_transactions
            WHERE username = $1 AND created_at >= $2 AND amount < 0
            GROUP BY source ORDER BY total_tokens DESC
        """, username, cutoff)

        share_history = await conn.fetch("""
            SELECT COUNT(*) as share_count,
                   COALESCE(SUM(tokens_shared), 0) as total_shared,
                   COUNT(DISTINCT receiver_username) as unique_recipients
            FROM token_shares WHERE sharer_username = $1
        """, username)

        sh = dict(share_history[0]) if share_history else {}

        return {
            "token_balance": row["token_balance"],
            "usage_today": row["usage_today"],
            "usage_month": row["usage_month"],
            "by_source": [{"source": r["source"], "total_tokens": r["total_tokens"]} for r in by_source],
            "sharing": {
                "total_shares": sh.get("share_count", 0),
                "total_tokens_shared": sh.get("total_shared", 0),
                "unique_recipients": sh.get("unique_recipients", 0),
            },
        }


# =============================================================================
# PRICING CATALOG & CHANGE NOTIFICATION
# =============================================================================

@router.get("/pricing-catalog")
async def get_pricing_catalog(request: Request):
    """Return the full pricing catalog for admin review."""
    from app.services.stripe_integration import PRICING_CATALOG, PRICES, detect_pricing_drift
    catalog = []
    for name, info in PRICING_CATALOG.items():
        price_id = PRICES.get(info["key"], "")
        catalog.append({
            "product": name,
            "amount": f"${info['amount_cents'] / 100:.2f}",
            "amount_cents": info["amount_cents"],
            "interval": info["interval"],
            "stripe_key": info["key"],
            "stripe_price_id": price_id or "NOT SET",
            "configured": bool(price_id),
        })
    drift = detect_pricing_drift()
    return {"catalog": catalog, "total_products": len(catalog), "drift_warnings": drift}


class PricingUpdateRequest(BaseModel):
    product_key: str
    new_amount_cents: int
    reason: str = ""


@router.post("/pricing-update")
async def update_pricing(
    body: PricingUpdateRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    """Admin-only: update a product price and notify support@sovereignsanctuary.net."""
    from app.services.stripe_integration import PRICING_CATALOG, notify_pricing_change

    target = None
    target_name = None
    for name, info in PRICING_CATALOG.items():
        if info["key"] == body.product_key:
            target = info
            target_name = name
            break

    if not target:
        raise HTTPException(404, f"Product key '{body.product_key}' not found in catalog")

    if body.new_amount_cents < 0:
        raise HTTPException(400, "Price cannot be negative")

    old_cents = target["amount_cents"]
    if old_cents == body.new_amount_cents:
        return {"status": "no_change", "message": "Price is already set to this amount"}

    target["amount_cents"] = body.new_amount_cents

    changed_items = [{
        "product": target_name,
        "old_cents": old_cents,
        "new_cents": body.new_amount_cents,
        "interval": target["interval"],
        "reason": body.reason,
        "key": body.product_key,
    }]

    ns = getattr(request.app.state, "notification_system", None)
    db_pool = getattr(request.app.state, "db_pool", None)
    notify_pricing_change._db_pool = db_pool
    admin_name = admin.get("username", "unknown_admin")

    await notify_pricing_change(changed_items, changed_by=admin_name, notification_system=ns)

    return {
        "status": "updated",
        "product": target_name,
        "old_price": f"${old_cents / 100:.2f}",
        "new_price": f"${body.new_amount_cents / 100:.2f}",
        "notification_sent": ns is not None,
        "note": "Update Stripe Price in dashboard and .env on server to match",
    }


# =============================================================================
# CARD SETUP (SetupIntent for adding a card)
# =============================================================================

@router.post("/card/setup")
async def setup_card_payment_method(req: ACHSetupRequest, request: Request):
    """Create a Stripe SetupIntent for adding a card via Stripe Elements."""
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
        raise HTTPException(400, "No Stripe customer found for this user")

    try:
        setup_intent = stripe.SetupIntent.create(
            customer=customer_id,
            payment_method_types=["card"],
        )
        return {
            "client_secret": setup_intent.client_secret,
            "setup_intent_id": setup_intent.id,
        }
    except stripe.error.StripeError as e:
        raise HTTPException(400, str(e))


# =============================================================================
# STRIPE CONNECT EXPRESS (Coach Payout Onboarding)
# =============================================================================

@router.post("/connect/onboard")
async def create_connect_account(request: Request, user: dict = Depends(require_coach)):
    """Create a Stripe Connect Express account for a coach and return the onboarding URL."""
    if not STRIPE_AVAILABLE:
        raise HTTPException(503, "Stripe not available")

    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", "")
    email = user.get("email", "")
    profile = user.get("profile", user)
    existing_connect = (profile.get("stripe_connect_id") or "").strip()

    if existing_connect:
        try:
            acct = stripe.Account.retrieve(existing_connect)
            if not acct.details_submitted:
                link = stripe.AccountLink.create(
                    account=existing_connect,
                    refresh_url="https://coach.sovereignsanctuary.net/settings?connect=refresh",
                    return_url="https://coach.sovereignsanctuary.net/settings?connect=complete",
                    type="account_onboarding",
                )
                return {"url": link.url, "account_id": existing_connect, "status": "continue_onboarding"}
            return {"status": "already_connected", "account_id": existing_connect, "payouts_enabled": acct.payouts_enabled}
        except Exception:
            pass

    try:
        account = stripe.Account.create(
            type="express",
            email=email or None,
            metadata={"coach_id": hw_id, "platform": "sovereign_sanctuary"},
            capabilities={"transfers": {"requested": True}},
        )

        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE users SET profile_data = jsonb_set(
                       COALESCE(profile_data, '{}'::jsonb),
                       '{stripe_connect_id}',
                       $1::jsonb
                   ) WHERE hardware_id = $2""",
                json.dumps(account.id), hw_id,
            )

        link = stripe.AccountLink.create(
            account=account.id,
            refresh_url="https://coach.sovereignsanctuary.net/settings?connect=refresh",
            return_url="https://coach.sovereignsanctuary.net/settings?connect=complete",
            type="account_onboarding",
        )
        return {"url": link.url, "account_id": account.id, "status": "created"}
    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Stripe Connect error: {e}")


@router.get("/connect/status")
async def connect_status(request: Request, user: dict = Depends(require_coach)):
    """Check the Stripe Connect status for the current coach."""
    if not STRIPE_AVAILABLE:
        raise HTTPException(503, "Stripe not available")

    profile = user.get("profile", user)
    connect_id = (profile.get("stripe_connect_id") or "").strip()

    if not connect_id:
        return {"connected": False, "payouts_enabled": False, "details_submitted": False}

    try:
        account = stripe.Account.retrieve(connect_id)
        return {
            "connected": True,
            "account_id": connect_id,
            "payouts_enabled": account.payouts_enabled,
            "charges_enabled": account.charges_enabled,
            "details_submitted": account.details_submitted,
        }
    except stripe.error.StripeError as e:
        return {"connected": False, "error": str(e)}


@router.post("/connect/dashboard")
async def connect_dashboard_link(request: Request, user: dict = Depends(require_coach)):
    """Generate a Stripe Express Dashboard login link for the coach."""
    if not STRIPE_AVAILABLE:
        raise HTTPException(503, "Stripe not available")

    profile = user.get("profile", user)
    connect_id = (profile.get("stripe_connect_id") or "").strip()

    if not connect_id:
        raise HTTPException(400, "No Stripe Connect account linked. Complete onboarding first.")

    try:
        link = stripe.Account.create_login_link(connect_id)
        return {"url": link.url}
    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Cannot create dashboard link: {e}")


# =============================================================================
# DOJO SUBSCRIPTION CHECKOUT (Stripe Checkout for DOJO add-ons)
# =============================================================================

DOJO_PRICE_MAP = {
    "therapist": 17500, "project_pm": 25000, "business": 32500,
    "cnc": 15000, "mcat": 50000, "teacher": 22500,
    "judge": 210000, "coach_nate": 9000,
}

DOJO_LABELS = {
    "therapist": "Therapist DOJO", "project_pm": "Project PM DOJO",
    "business": "Business DOJO", "cnc": "CNC DOJO",
    "mcat": "MCAT DOJO", "teacher": "Teacher DOJO",
    "judge": "Judge DOJO", "coach_nate": "Coach Nate DOJO",
}


class PaymentMethodCheckoutRequest(BaseModel):
    user_id: str
    method_type: str = "card"


@router.post("/payment-method/add-checkout")
async def payment_method_add_checkout(body: PaymentMethodCheckoutRequest, request: Request):
    """Create a Stripe Checkout Session in setup mode for adding a card or bank account."""
    if not STRIPE_AVAILABLE:
        raise HTTPException(503, "Stripe not available")

    pool = getattr(request.app.state, "db_pool", None)
    customer_id = None
    username = ""

    if pool:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT stripe_customer_id, username, profile_data->>'email' as email "
                "FROM users WHERE hardware_id = $1",
                body.user_id,
            )
            if row:
                customer_id = row["stripe_customer_id"]
                username = row["username"] or ""
                email = row["email"] or ""

    if not customer_id:
        try:
            customer = stripe.Customer.create(
                email=email if 'email' in dir() else None,
                name=username or body.user_id,
                metadata={"user_id": body.user_id},
            )
            customer_id = customer.id
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE users SET stripe_customer_id = $1 WHERE hardware_id = $2",
                        customer_id, body.user_id,
                    )
        except stripe.error.StripeError as e:
            raise HTTPException(400, f"Failed to create Stripe customer: {e}")

    method_type = body.method_type.lower()
    if method_type == "bank":
        payment_method_types = ["us_bank_account"]
    else:
        payment_method_types = ["card"]

    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="setup",
            payment_method_types=payment_method_types,
            success_url="https://app.sovereignsanctuary.net/payment-complete",
            cancel_url="https://app.sovereignsanctuary.net/payment-cancelled",
        )
        return {"checkout_url": session.url, "session_id": session.id}
    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Stripe checkout error: {e}")


@router.post("/portal")
async def create_billing_portal(request: Request, user: dict = Depends(get_current_user)):
    if not STRIPE_AVAILABLE:
        raise HTTPException(503, "Stripe not available")
    hw_id = user.get("hardware_id") or user.get("user_id", "")
    customer_id = None
    db = getattr(request.app.state, "db_pool", None)
    if db:
        row = await db.fetchrow("SELECT stripe_customer_id FROM users WHERE hardware_id = $1", hw_id)
        if row:
            customer_id = row["stripe_customer_id"]
    if not customer_id:
        raise HTTPException(400, "No billing account found")
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url="https://app.sovereignsanctuary.net/payment-complete",
        )
        return {"portal_url": session.url}
    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Portal error: {e}")


class DojoCheckoutRequest(BaseModel):
    dojo_key: str


@router.post("/dojo/checkout")
async def dojo_checkout(body: DojoCheckoutRequest, request: Request, user: dict = Depends(require_coach)):
    """Create a Stripe Checkout session for a DOJO subscription."""
    if not STRIPE_AVAILABLE:
        raise HTTPException(503, "Stripe not available")

    dojo_key = body.dojo_key.lower()
    if dojo_key not in DOJO_PRICE_MAP:
        raise HTTPException(400, f"Invalid dojo_key: {dojo_key}")

    pool = getattr(request.app.state, "db_pool", None)
    hw_id = user.get("hardware_id", "")
    username = user.get("username", "")
    email = user.get("email", "")

    from app.services.stripe_integration import PRICES
    price_id = PRICES.get(f"DOJO_{dojo_key.upper()}")

    customer_id = None
    if pool:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT stripe_customer_id FROM users WHERE hardware_id = $1", hw_id
            )
            if row:
                customer_id = row["stripe_customer_id"]

    if not customer_id:
        try:
            customer = stripe.Customer.create(
                email=email or None,
                name=username,
                metadata={"coach_id": hw_id},
            )
            customer_id = customer.id
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE users SET stripe_customer_id = $1 WHERE hardware_id = $2",
                        customer_id, hw_id,
                    )
        except stripe.error.StripeError as e:
            raise HTTPException(400, f"Failed to create Stripe customer: {e}")

    try:
        session_params = {
            "customer": customer_id,
            "mode": "subscription",
            "metadata": {"type": "dojo_subscription", "dojo_key": dojo_key, "coach_id": hw_id},
            "success_url": "https://coach.sovereignsanctuary.net/payment-complete?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": "https://coach.sovereignsanctuary.net/payment-cancelled",
        }

        if price_id:
            session_params["line_items"] = [{"price": price_id, "quantity": 1}]
        else:
            session_params["line_items"] = [{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": DOJO_LABELS.get(dojo_key, f"{dojo_key} DOJO")},
                    "unit_amount": DOJO_PRICE_MAP[dojo_key],
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }]

        session = stripe.checkout.Session.create(**session_params)
        return {"checkout_url": session.url, "session_id": session.id}
    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Stripe checkout error: {e}")


# =============================================================================
# PUBLIC ROUTER — No auth required (pre-registration discount verification)
# =============================================================================

public_router = APIRouter(
    prefix="/api/billing",
    tags=["billing-public"],
)

_public_rate_limiter: Dict[str, list] = {}
_PUBLIC_WINDOW = 60
_PUBLIC_MAX = 10


def _rate_check_ip(ip: str) -> bool:
    now = _time_billing.time()
    window = _public_rate_limiter.setdefault(ip, [])
    _public_rate_limiter[ip] = [t for t in window if now - t < _PUBLIC_WINDOW]
    if len(_public_rate_limiter[ip]) >= _PUBLIC_MAX:
        return True
    _public_rate_limiter[ip].append(now)
    return False


@public_router.get("/verify-discount-code/{code}")
async def verify_discount_code(code: str, request: Request,
                               tier: Optional[str] = None):
    """Public endpoint to verify any discount code (promo, school, or corporate).
    Used during registration before the user has an account."""
    client_ip = request.client.host if request.client else "unknown"
    if _rate_check_ip(client_ip):
        raise HTTPException(429, "Too many verification attempts")

    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    safe_code = _sanitize_code(code)

    async with pool.acquire() as conn:
        # 1. Check promotional_specials
        promo = await conn.fetchrow("""
            SELECT id, name, discount_type, discount_value, applicable_tiers,
                   ends_at, max_redemptions, current_redemptions
            FROM promotional_specials
            WHERE promo_code = $1 AND active = TRUE
              AND starts_at <= NOW() AND ends_at > NOW()
        """, safe_code)

        if promo:
            if promo["max_redemptions"] and promo["current_redemptions"] >= promo["max_redemptions"]:
                raise HTTPException(404, "Invalid or expired code")
            allowed_tiers = promo["applicable_tiers"] or []
            if isinstance(allowed_tiers, str):
                try:
                    allowed_tiers = json.loads(allowed_tiers)
                except Exception:
                    allowed_tiers = []
            if not isinstance(allowed_tiers, list):
                allowed_tiers = []
            allowed_norm = {_normalize_tier(str(t)) for t in allowed_tiers if str(t).strip()}
            if allowed_norm and tier:
                norm_tier = _normalize_tier(str(tier))
                if norm_tier not in allowed_norm:
                    raise HTTPException(400, "Code is not valid for this subscription tier")
            return {
                "valid": True,
                "source": "promotional_specials",
                "name": promo["name"],
                "discount_type": promo["discount_type"],
                "discount_value": promo["discount_value"],
                "applicable_tiers": allowed_tiers,
            }

        # 2. Check school_codes
        school = await conn.fetchrow("""
            SELECT id, school_name, school_code, discount_percent,
                   max_students, current_students, active
            FROM school_codes
            WHERE school_code = $1 AND active = TRUE
        """, safe_code)

        if school:
            if school["max_students"] and school["current_students"] >= school["max_students"]:
                raise HTTPException(404, "Invalid or expired code")
            return {
                "valid": True,
                "source": "school_codes",
                "name": school["school_name"],
                "discount_type": "percent",
                "discount_value": school["discount_percent"],
                "applicable_tiers": [],
            }

        # 3. Check corporate_sponsors
        corp = await conn.fetchrow("""
            SELECT id, company_name, discount_type, discount_value,
                   pays_full, max_employees, current_employees, active
            FROM corporate_sponsors WHERE sponsor_code = $1 AND active = TRUE
        """, safe_code)

        if corp:
            if corp["max_employees"] and corp["current_employees"] >= corp["max_employees"]:
                raise HTTPException(404, "Invalid or expired code")
            d_type = "pays_full" if corp["pays_full"] else corp["discount_type"]
            d_value = 100 if corp["pays_full"] else corp["discount_value"]
            return {
                "valid": True,
                "source": "corporate_sponsors",
                "name": corp["company_name"],
                "discount_type": d_type,
                "discount_value": d_value,
                "applicable_tiers": [],
            }

    raise HTTPException(404, "Invalid or expired code")
