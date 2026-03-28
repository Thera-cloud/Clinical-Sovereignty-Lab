"""
LITTLE NATE — Stripe E-Commerce Integration
Version: 2.0
Date: March 1, 2026

Complete Stripe integration for:
- Subscription management (tiers)
- Family member billing (tiered)
- Coaching session packs
- Token pack purchases (one-time)
- DOJO subscriptions
- Token share fee (GKM donation)
- Pricing change notification emails
- Webhook handling

Required env vars:
- STRIPE_SECRET_KEY
- STRIPE_WEBHOOK_SECRET
- STRIPE_PRICE_STANDARD, STRIPE_PRICE_TOP_TIER
- STRIPE_PRICE_FAMILY_MEMBER, STRIPE_PRICE_FAMILY_TIER_{1-4}
- STRIPE_PRICE_COACHING_SINGLE, STRIPE_PRICE_COACHING_4PACK, STRIPE_PRICE_COACHING_8PACK
- STRIPE_PRICE_TOKEN_LIGHT, STRIPE_PRICE_TOKEN_STANDARD, STRIPE_PRICE_TOKEN_POWER, STRIPE_PRICE_TOKEN_ULTIMATE
- STRIPE_PRICE_TOKEN_SHARE_FEE
- STRIPE_PRICE_DOJO_{THERAPIST,PROJECT_PM,BUSINESS,CNC,MCAT,TEACHER,JUDGE,COACH_NATE}
"""

import logging
import os
import stripe

_logger = logging.getLogger(__name__)
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
import asyncpg
import json

from app.auth import get_current_user_id

# =============================================================================
# CONFIGURATION
# =============================================================================

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_METER_EVENT_NAME = os.getenv("STRIPE_METER_EVENT_NAME", "token_usage")

# Stripe Price IDs (set these in your Stripe dashboard)
PRICES = {
    "STANDARD": os.getenv("STRIPE_PRICE_STANDARD"),        # $49/mo
    "TOP_TIER": os.getenv("STRIPE_PRICE_TOP_TIER"),        # $149/mo
    "FAMILY_MEMBER": os.getenv("STRIPE_PRICE_FAMILY_MEMBER"),  # legacy single-price
    "FAMILY_TIER_1": os.getenv("STRIPE_PRICE_FAMILY_TIER_1"),  # $75/mo
    "FAMILY_TIER_2": os.getenv("STRIPE_PRICE_FAMILY_TIER_2"),  # $60/mo
    "FAMILY_TIER_3": os.getenv("STRIPE_PRICE_FAMILY_TIER_3"),  # $45/mo
    "FAMILY_TIER_4": os.getenv("STRIPE_PRICE_FAMILY_TIER_4"),  # $30/mo
    "COACHING_SINGLE": os.getenv("STRIPE_PRICE_COACHING_SINGLE"),  # $175
    "COACHING_4PACK": os.getenv("STRIPE_PRICE_COACHING_4PACK"),    # $600
    "COACHING_8PACK": os.getenv("STRIPE_PRICE_COACHING_8PACK"),    # $1,120
    "TOKEN_LIGHT": os.getenv("STRIPE_PRICE_TOKEN_LIGHT"),          # $3 / 15k tokens
    "TOKEN_STANDARD": os.getenv("STRIPE_PRICE_TOKEN_STANDARD"),    # $7 / 50k tokens
    "TOKEN_POWER": os.getenv("STRIPE_PRICE_TOKEN_POWER"),          # $20 / 150k tokens
    "TOKEN_ULTIMATE": os.getenv("STRIPE_PRICE_TOKEN_ULTIMATE"),    # $125 / 1M tokens
    "TOKEN_SHARE_FEE": os.getenv("STRIPE_PRICE_TOKEN_SHARE_FEE"), # $5 per 10k shared
    # DOJO subscriptions (monthly)
    "DOJO_THERAPIST": os.getenv("STRIPE_PRICE_DOJO_THERAPIST"),    # $175/mo
    "DOJO_PROJECT_PM": os.getenv("STRIPE_PRICE_DOJO_PROJECT_PM"),  # $250/mo
    "DOJO_BUSINESS": os.getenv("STRIPE_PRICE_DOJO_BUSINESS"),      # $325/mo
    "DOJO_CNC": os.getenv("STRIPE_PRICE_DOJO_CNC"),                # $150/mo
    "DOJO_MCAT": os.getenv("STRIPE_PRICE_DOJO_MCAT"),              # $500/mo
    "DOJO_TEACHER": os.getenv("STRIPE_PRICE_DOJO_TEACHER"),        # $225/mo
    "DOJO_JUDGE": os.getenv("STRIPE_PRICE_DOJO_JUDGE"),            # $2,100/mo
    "DOJO_COACH_NATE": os.getenv("STRIPE_PRICE_DOJO_COACH_NATE"), # $90/mo
    # Annual subscription prices
    "INNER_CHAMBER_ANNUAL": os.getenv("STRIPE_PRICE_INNER_CHAMBER_ANNUAL"),      # $490/yr
    "SOVEREIGN_CIRCLE_ANNUAL": os.getenv("STRIPE_PRICE_SOVEREIGN_CIRCLE_ANNUAL"),  # $749/6mo
}

# Canonical pricing reference — source of truth for all product prices.
# Any change here MUST trigger a pricing change email via notify_pricing_change().
PRICING_CATALOG = {
    "Inner Chamber (Standard)":    {"amount_cents": 4900,    "interval": "month", "key": "STANDARD"},
    "Sovereign Circle (Top Tier)": {"amount_cents": 14900,   "interval": "month", "key": "TOP_TIER"},
    "Family Member Tier 1":        {"amount_cents": 7500,    "interval": "month", "key": "FAMILY_TIER_1"},
    "Family Member Tier 2":        {"amount_cents": 6000,    "interval": "month", "key": "FAMILY_TIER_2"},
    "Family Member Tier 3":        {"amount_cents": 4500,    "interval": "month", "key": "FAMILY_TIER_3"},
    "Family Member Tier 4+":       {"amount_cents": 3000,    "interval": "month", "key": "FAMILY_TIER_4"},
    "Live Coaching Session":       {"amount_cents": 17500,   "interval": "one-time", "key": "COACHING_SINGLE"},
    "Coaching Pack - 4 sessions":  {"amount_cents": 60000,   "interval": "one-time", "key": "COACHING_4PACK"},
    "Coaching Pack - 8 sessions":  {"amount_cents": 112000,  "interval": "one-time", "key": "COACHING_8PACK"},
    "Token Pack Light (15k)":      {"amount_cents": 300,     "interval": "one-time", "key": "TOKEN_LIGHT"},
    "Token Pack Standard (50k)":   {"amount_cents": 700,     "interval": "one-time", "key": "TOKEN_STANDARD"},
    "Token Pack Power (150k)":     {"amount_cents": 2000,    "interval": "one-time", "key": "TOKEN_POWER"},
    "Token Pack Ultimate (1M)":    {"amount_cents": 12500,   "interval": "one-time", "key": "TOKEN_ULTIMATE"},
    "Token Share Fee (GKM)":       {"amount_cents": 500,     "interval": "per-10k", "key": "TOKEN_SHARE_FEE"},
    "DOJO Therapist":              {"amount_cents": 17500,   "interval": "month", "key": "DOJO_THERAPIST"},
    "DOJO Project PM":             {"amount_cents": 25000,   "interval": "month", "key": "DOJO_PROJECT_PM"},
    "DOJO Business":               {"amount_cents": 32500,   "interval": "month", "key": "DOJO_BUSINESS"},
    "DOJO CNC":                    {"amount_cents": 15000,   "interval": "month", "key": "DOJO_CNC"},
    "DOJO MCAT":                   {"amount_cents": 50000,   "interval": "month", "key": "DOJO_MCAT"},
    "DOJO Teacher":                {"amount_cents": 22500,   "interval": "month", "key": "DOJO_TEACHER"},
    "DOJO Judge (Nate Bar)":       {"amount_cents": 210000,  "interval": "month", "key": "DOJO_JUDGE"},
    "Coach Nate":                  {"amount_cents": 9000,    "interval": "month", "key": "DOJO_COACH_NATE"},
}

TOKEN_PACKS = {
    "light":    {"tokens": 15000,    "price_cents": 300,   "label": "Light Pack"},
    "standard": {"tokens": 50000,    "price_cents": 700,   "label": "Standard Pack"},
    "power":    {"tokens": 150000,   "price_cents": 2000,  "label": "Power Pack"},
    "ultimate": {"tokens": 1000000,  "price_cents": 12500, "label": "Ultimate Pack"},
}

# =============================================================================
# CORPORATE TIERS (Hybrid: flat platform fee + employee subsidy)
# =============================================================================
CORPORATE_TIERS = {
    "starter": {
        "label": "Starter",
        "platform_fee_cents": 29900,
        "max_seats": 25,
        "features": ["dashboard", "analytics", "employee_management"],
    },
    "growth": {
        "label": "Growth",
        "platform_fee_cents": 79900,
        "max_seats": 100,
        "features": ["dashboard", "analytics", "employee_management", "custom_branding", "api_access"],
    },
    "enterprise": {
        "label": "Enterprise",
        "platform_fee_cents": 199900,
        "max_seats": 500,
        "features": ["dashboard", "analytics", "employee_management", "custom_branding", "api_access", "sso", "dedicated_support", "custom_reports"],
    },
}

EMPLOYEE_SUBSCRIPTION_PRICES = {
    "STANDARD": 4900,
    "TOP_TIER": 14900,
}


def calculate_subsidized_rate(employee_tier: str, subsidy_pct: int) -> dict:
    """Calculate the subsidized employee subscription rate.

    Args:
        employee_tier: STANDARD or TOP_TIER
        subsidy_pct: 25-100, percentage the company pays
    Returns:
        dict with company_pays_cents, employee_pays_cents, total_cents
    """
    subsidy_pct = max(25, min(100, subsidy_pct))
    total = EMPLOYEE_SUBSCRIPTION_PRICES.get(employee_tier, 4900)
    company_pays = int(total * subsidy_pct / 100)
    employee_pays = total - company_pays
    return {
        "total_cents": total,
        "subsidy_percentage": subsidy_pct,
        "company_pays_cents": company_pays,
        "employee_pays_cents": employee_pays,
        "employee_tier": employee_tier,
    }


# Founding member coupon (configurable via env)
FOUNDING_COUPON_ID = os.getenv("STRIPE_FOUNDING_COUPON_ID", "FOUNDING_20PCT")

# Validate required price IDs are set (warn if missing)
for key in ["STANDARD", "TOP_TIER"]:
    if not PRICES.get(key):
        _logger.warning(
            f"STRIPE_PRICE_{key} not set — subscription checkout will fail for {key} tier"
        )

# =============================================================================
# USAGE-BASED METERING (Stripe Billing Meters)
# =============================================================================

import time as _time

async def report_token_usage(
    stripe_customer_id: str,
    tokens: int,
    source: str = "ai_chat",
) -> bool:
    """Report token usage to Stripe Meter for usage-based billing.

    Args:
        stripe_customer_id: Stripe customer ID (cus_...)
        tokens: Number of tokens consumed
        source: Consumption source tag (ai_chat, sanctuary_ai, etc.)

    Returns:
        True if the event was reported, False otherwise.
    """
    if not stripe.api_key or not stripe_customer_id or tokens <= 0:
        return False

    try:
        stripe.billing.MeterEvent.create(
            event_name=STRIPE_METER_EVENT_NAME,
            payload={
                "stripe_customer_id": stripe_customer_id,
                "tokens": str(tokens),
            },
            timestamp=int(_time.time()),
        )
        _logger.debug(
            "Reported %d tokens to Stripe meter for %s (source=%s)",
            tokens, stripe_customer_id, source,
        )
        return True
    except Exception as e:
        _logger.warning("Stripe meter event failed for %s: %s", stripe_customer_id, e)
        return False


async def report_token_usage_by_username(
    db_pool,
    username: str,
    tokens: int,
    source: str = "ai_chat",
) -> bool:
    """Resolve username to Stripe customer ID and report usage."""
    if not db_pool or not username or tokens <= 0:
        return False

    try:
        async with db_pool.acquire() as conn:
            cid = await conn.fetchval(
                "SELECT profile_data->>'stripe_customer_id' FROM users WHERE username = $1",
                username,
            )
        if cid:
            return await report_token_usage(cid, tokens, source)
    except Exception as e:
        _logger.warning("Meter usage lookup failed for %s: %s", username, e)
    return False


# =============================================================================
# PRICING CHANGE NOTIFICATION
# =============================================================================

PRICING_NOTIFY_EMAIL = "support@sovereignsanctuary.net"

async def notify_pricing_change(
    changed_items: list,
    changed_by: str = "system",
    notification_system=None,
):
    """Email support@sovereignsanctuary.net when any product pricing changes.

    Args:
        changed_items: list of dicts with keys: product, old_cents, new_cents, interval
        changed_by: who triggered the change (username or "system")
        notification_system: NotificationSystem instance for sending email
    """
    if not changed_items:
        return

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    rows = ""
    for item in changed_items:
        old_price = f"${item['old_cents'] / 100:.2f}"
        new_price = f"${item['new_cents'] / 100:.2f}"
        direction = "↑" if item["new_cents"] > item["old_cents"] else "↓"
        rows += (
            f"<tr>"
            f"<td style='padding:8px;border:1px solid #333'>{item['product']}</td>"
            f"<td style='padding:8px;border:1px solid #333'>{old_price}</td>"
            f"<td style='padding:8px;border:1px solid #333;font-weight:bold'>{new_price} {direction}</td>"
            f"<td style='padding:8px;border:1px solid #333'>{item.get('interval', 'month')}</td>"
            f"</tr>"
        )

    html = f"""
    <div style="font-family:DM Sans,sans-serif;background:#0A0A0A;color:#E8D5A3;padding:24px;border-radius:8px;">
        <h2 style="color:#C9A962;margin-top:0;">Sovereign Sanctuary — Pricing Change Alert</h2>
        <p><strong>Changed by:</strong> {changed_by}</p>
        <p><strong>Timestamp:</strong> {now.strftime('%B %d, %Y at %H:%M UTC')}</p>
        <table style="border-collapse:collapse;width:100%;margin:16px 0;color:#E8D5A3;">
            <tr style="background:#111;">
                <th style="padding:8px;border:1px solid #333;text-align:left">Product</th>
                <th style="padding:8px;border:1px solid #333;text-align:left">Previous</th>
                <th style="padding:8px;border:1px solid #333;text-align:left">New</th>
                <th style="padding:8px;border:1px solid #333;text-align:left">Billing</th>
            </tr>
            {rows}
        </table>
        <p style="color:#888;font-size:12px;">
            This is an automated notification from the Little Nate billing system.
            If you did not authorize this change, investigate immediately.
        </p>
    </div>
    """

    subject = f"⚠️ Pricing Change — {len(changed_items)} product(s) updated — {now.strftime('%b %d %Y')}"

    if notification_system:
        try:
            await notification_system._send_email(
                PRICING_NOTIFY_EMAIL, subject, html, "pricing_change"
            )
            _logger.info("Pricing change email sent to %s (%d items)", PRICING_NOTIFY_EMAIL, len(changed_items))
        except Exception as e:
            _logger.error("Failed to send pricing change email: %s", e)
    else:
        _logger.warning("No notification_system available — pricing change email NOT sent for %d items", len(changed_items))

    try:
        import asyncpg
        db_pool = getattr(notify_pricing_change, '_db_pool', None)
        if db_pool:
            await db_pool.execute(
                """INSERT INTO skyeye_activity (type, content, platform, created_at)
                   VALUES ('pricing_change', $1, 'system', NOW())""",
                json.dumps({
                    "changed_by": changed_by,
                    "items": changed_items,
                    "timestamp": now.isoformat(),
                }),
            )
    except Exception as e:
        _logger.warning("Failed to log pricing change to skyeye_activity: %s", e)


def detect_pricing_drift() -> list:
    """Compare PRICING_CATALOG against TOKEN_PACKS and FAMILY_TIER_PRICES.

    Returns list of mismatches for admin visibility. Called on startup.
    """
    drift = []
    for pack_id, pack in TOKEN_PACKS.items():
        catalog_key = f"TOKEN_{pack_id.upper()}"
        for name, info in PRICING_CATALOG.items():
            if info["key"] == catalog_key:
                if info["amount_cents"] != pack["price_cents"]:
                    drift.append({
                        "product": name,
                        "catalog_cents": info["amount_cents"],
                        "code_cents": pack["price_cents"],
                        "source": "TOKEN_PACKS",
                    })
    return drift


# =============================================================================
# ENUMS & MODELS
# =============================================================================

class SubscriptionTier(str, Enum):
    TRIAL = "TRIAL"
    STANDARD = "STANDARD"
    TOP_TIER = "TOP_TIER"

class FamilyRole(str, Enum):
    PRIMARY = "PRIMARY"
    SPOUSE = "SPOUSE"
    CHILD_UNDER_12 = "CHILD_UNDER_12"
    CHILD_13_PLUS = "CHILD_13_PLUS"
    ADDITIONAL = "ADDITIONAL"

# Tiered family pricing: ordinal position among PAID members -> monthly price
FAMILY_TIER_PRICES = {1: 7500, 2: 6000, 3: 4500}  # cents; 4+ = 3000
def family_tier_price_cents(ordinal: int) -> int:
    """Return price in cents for the Nth paid family slot (1-indexed)."""
    return FAMILY_TIER_PRICES.get(ordinal, 3000)

class PackType(str, Enum):
    SINGLE = "SINGLE"
    PACK_4 = "PACK_4"
    PACK_8 = "PACK_8"

@dataclass
class PackConfig:
    sessions: int
    price_cents: int
    validity_days: int


# Locked Pricing Model v3 — 70% coach / 30% platform
# Single $175 → coach $122.50, platform $52.50
# 4-pack $600 ($150/session) → coach $105/session, platform $45/session
# 8-pack $1,120 ($140/session) → coach $98/session, platform $42/session
PACK_CONFIGS = {
    PackType.SINGLE: PackConfig(sessions=1, price_cents=17500, validity_days=30),
    PackType.PACK_4: PackConfig(sessions=4, price_cents=60000, validity_days=90),
    PackType.PACK_8: PackConfig(sessions=8, price_cents=112000, validity_days=180),
}

# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class CreateCheckoutRequest(BaseModel):
    tier: SubscriptionTier
    success_url: str
    cancel_url: str
    promo_code: Optional[str] = None

class CreateCheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str

class AddFamilyMemberRequest(BaseModel):
    email: str
    name: str
    relationship: str  # "spouse", "child", "other"
    date_of_birth: Optional[str] = None  # ISO date YYYY-MM-DD (required for children)

class PurchaseCoachingPackRequest(BaseModel):
    pack_type: PackType
    success_url: str
    cancel_url: str

class BookCoachingSessionRequest(BaseModel):
    coach_id: str
    scheduled_at: datetime
    use_pack_id: Optional[str] = None  # If None, charge card

class SubscriptionResponse(BaseModel):
    tier: str
    status: str
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    family_members: List[Dict[str, Any]]
    monthly_total_cents: int

# =============================================================================
# STRIPE SERVICE
# =============================================================================

class StripeService:
    def __init__(self, db_pool: asyncpg.Pool):
        self.db = db_pool
        self._sovereign_proxy = None  # Lazy-loaded from app.state

    def _get_proxy(self):
        """Get SovereignStripeProxy if available."""
        if self._sovereign_proxy is None:
            try:
                from app.services.sovereign_stripe_proxy import SovereignStripeProxy
                self._sovereign_proxy = SovereignStripeProxy(self.db)
            except Exception:
                pass
        return self._sovereign_proxy

    async def _notify_bridge_reload(self, username: str):
        """Publish Redis messages so the bridge reloads this user from PG."""
        try:
            from app.services.api_server import _get_auth_redis
            r = await _get_auth_redis()
            if r:
                await r.publish("nate:user_reload", json.dumps({"username": username}))
        except Exception:
            pass
    
    # -------------------------------------------------------------------------
    # CUSTOMER MANAGEMENT
    # -------------------------------------------------------------------------
    
    async def get_or_create_customer(self, user_id: str, email: str, name: str) -> str:
        """Get existing Stripe customer or create new one.
        
        HIVE DEFENSE v4.3: Routes through SovereignStripeProxy for minimized PII.
        """
        # Check if user already has a customer ID
        row = await self.db.fetchrow(
            "SELECT stripe_customer_id FROM users WHERE id = $1",
            user_id
        )
        
        if row and row['stripe_customer_id']:
            return row['stripe_customer_id']
        
        # ── HIVE DEFENSE v4.3: Use SovereignStripeProxy for minimal PII ──
        proxy = self._get_proxy()
        if proxy:
            result = await proxy.create_customer(user_id, email, name)
            if result.get("success"):
                customer_id = result["customer_id"]
                await self.db.execute(
                    "UPDATE users SET stripe_customer_id = $1 WHERE id = $2",
                    customer_id, user_id
                )
                return customer_id
            # Fallback if proxy fails
            _logger.warning("SovereignStripeProxy customer creation failed, using direct API")

        # Fallback: direct Stripe call
        customer = stripe.Customer.create(
            email=email,
            name=name,
            metadata={"user_id": user_id}
        )
        
        # Store customer ID
        await self.db.execute(
            "UPDATE users SET stripe_customer_id = $1 WHERE id = $2",
            customer.id, user_id
        )
        
        return customer.id
    
    # -------------------------------------------------------------------------
    # SUBSCRIPTION CHECKOUT
    # -------------------------------------------------------------------------
    
    async def create_subscription_checkout(
        self,
        user_id: str,
        email: str,
        name: str,
        tier: SubscriptionTier,
        success_url: str,
        cancel_url: str,
        promo_code: Optional[str] = None,
        billing_cycle: str = "monthly"
    ) -> CreateCheckoutResponse:
        """Create Stripe checkout session for subscription."""
        
        if tier == SubscriptionTier.TRIAL:
            raise HTTPException(400, "Cannot checkout for trial tier")
        
        customer_id = await self.get_or_create_customer(user_id, email, name)

        annual_key_map = {
            "STANDARD": "INNER_CHAMBER_ANNUAL",
            "TOP_TIER": "SOVEREIGN_CIRCLE_ANNUAL",
        }
        if billing_cycle == "annual" and tier.value in annual_key_map:
            price_id = PRICES.get(annual_key_map[tier.value]) or PRICES.get(tier.value)
        else:
            price_id = PRICES.get(tier.value)
        
        if not price_id:
            raise HTTPException(500, f"Price not configured for {tier.value}")
        
        # Check if upgrading from existing subscription
        existing = await self.db.fetchrow(
            "SELECT stripe_subscription_id FROM subscriptions WHERE user_id = $1 AND status = 'ACTIVE'",
            user_id
        )
        
        if existing and existing['stripe_subscription_id']:
            # Use billing portal for upgrades
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=success_url
            )
            return CreateCheckoutResponse(
                checkout_url=session.url,
                session_id=session.id
            )
        
        # Check founding member eligibility (first 100 paying members get 20% off for life)
        founding_eligible = False
        try:
            row = await self.db.fetchrow(
                "SELECT value FROM platform_config WHERE key = 'founding_member_count'"
            )
            if row and row["value"]:
                cfg = row["value"] if isinstance(row["value"], dict) else json.loads(row["value"])
                count = cfg.get("count", 0) or 0
                max_count = cfg.get("max", 100) or 100
                if count < max_count:
                    # User not already a founding member
                    existing_founding = await self.db.fetchval(
                        "SELECT is_founding_member FROM users WHERE id = $1", user_id
                    )
                    if not existing_founding:
                        founding_eligible = True
        except Exception as e:
            print(f">>> [STRIPE] Founding member check failed: {e}")

        # Create new subscription checkout
        trial_days = 7 if tier == SubscriptionTier.STANDARD else None
        sub_data = {"metadata": {"user_id": user_id, "tier": tier.value}}
        if trial_days is not None:
            sub_data["trial_period_days"] = trial_days

        session_params = {
            "customer": customer_id,
            "mode": "subscription",
            "payment_method_types": ["card"],
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url + "?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": cancel_url,
            "metadata": {"user_id": user_id, "tier": tier.value},
            "subscription_data": sub_data,
        }
        promo_meta: Dict[str, str] = {}
        full_discount_checkout = False
        if founding_eligible:
            session_params["discounts"] = [{"coupon": FOUNDING_COUPON_ID}]
        elif promo_code:
            promo = await self._resolve_promo_coupon(promo_code, tier.value)
            if promo and promo.get("stripe_coupon_id"):
                session_params["discounts"] = [{"coupon": promo["stripe_coupon_id"]}]
                full_discount_checkout = bool(promo.get("is_full_discount"))
                promo_meta = {
                    "applied_promo_code": str(promo.get("code", "")).upper(),
                    "applied_promo_source": str(promo.get("source", "")),
                    "applied_promo_id": str(promo.get("id", "")),
                }
            elif promo and not promo.get("stripe_coupon_id"):
                print(f">>> [STRIPE] Promo code '{promo_code}' matched DB but has no Stripe coupon — code cannot be applied")
                session_params["allow_promotion_codes"] = True
            else:
                session_params["allow_promotion_codes"] = True
        if promo_meta:
            session_params["metadata"] = {
                **session_params["metadata"],
                **promo_meta,
            }
        if full_discount_checkout:
            # 100% discounts can produce a zero-dollar initial invoice.
            # Let Stripe skip payment collection when not required.
            session_params["payment_method_collection"] = "if_required"

        session = stripe.checkout.Session.create(**session_params)
        
        return CreateCheckoutResponse(
            checkout_url=session.url,
            session_id=session.id
        )
    
    # -------------------------------------------------------------------------
    # PROMO CODE RESOLUTION
    # -------------------------------------------------------------------------

    async def _resolve_promo_coupon(self, promo_code: str, tier: str) -> Optional[Dict[str, Any]]:
        """Look up a promo code across all discount tables and return Stripe + tracking metadata."""
        import re
        cleaned = promo_code.strip().upper()[:40]
        if not re.match(r'^[A-Z0-9_\-]{2,40}$', cleaned):
            return None
        try:
            row = await self.db.fetchrow("""
                SELECT id, stripe_coupon_id, discount_type, discount_value
                FROM promotional_specials
                WHERE promo_code = $1 AND active = TRUE
                  AND starts_at <= NOW() AND ends_at > NOW()
                  AND (max_redemptions IS NULL OR current_redemptions < max_redemptions)
                  AND (
                    applicable_tiers IS NULL
                    OR cardinality(applicable_tiers) = 0
                    OR $2 = ANY(applicable_tiers)
                  )
            """, cleaned, tier)
            if row and row["stripe_coupon_id"]:
                return {
                    "id": str(row["id"]),
                    "code": cleaned,
                    "source": "promotional_specials",
                    "stripe_coupon_id": row["stripe_coupon_id"],
                    "is_full_discount": row["discount_type"] == "percent" and int(row["discount_value"] or 0) >= 100,
                }

            row = await self.db.fetchrow("""
                SELECT stripe_coupon_id FROM school_codes
                WHERE school_code = $1 AND active = TRUE
                  AND (max_students IS NULL OR current_students < max_students)
            """, cleaned)
            if row and row.get("stripe_coupon_id"):
                return {
                    "id": "school_code",
                    "code": cleaned,
                    "source": "school_codes",
                    "stripe_coupon_id": row["stripe_coupon_id"],
                    "is_full_discount": False,
                }

            row = await self.db.fetchrow("""
                SELECT stripe_coupon_id, pays_full, discount_type, discount_value
                FROM corporate_sponsors
                WHERE sponsor_code = $1 AND active = TRUE
                  AND (max_employees IS NULL OR current_employees < max_employees)
            """, cleaned)
            if row and row.get("stripe_coupon_id"):
                is_full = bool(row.get("pays_full"))
                if not is_full and row.get("discount_type") == "percent":
                    is_full = int(row.get("discount_value") or 0) >= 100
                return {
                    "id": "corporate_sponsor",
                    "code": cleaned,
                    "source": "corporate_sponsors",
                    "stripe_coupon_id": row["stripe_coupon_id"],
                    "is_full_discount": is_full,
                }
        except Exception as e:
            _logger.warning("Promo code resolution failed for %s: %s", cleaned, e)
        return None

    # -------------------------------------------------------------------------
    # FAMILY MANAGEMENT
    # -------------------------------------------------------------------------
    
    # -------------------------------------------------------------------------
    # FAMILY PRICING HELPERS (v3 — Tiered)
    # -------------------------------------------------------------------------

    def _compute_family_role(self, relationship: str, date_of_birth: Optional[str]) -> FamilyRole:
        """Determine FamilyRole from relationship string and DOB."""
        rel = relationship.lower().strip()
        if rel == "spouse":
            return FamilyRole.SPOUSE
        if rel == "child":
            if not date_of_birth:
                return FamilyRole.CHILD_13_PLUS  # default to paid if no DOB
            from datetime import date as _date
            from dateutil.relativedelta import relativedelta
            try:
                dob = _date.fromisoformat(date_of_birth)
            except (ValueError, TypeError):
                return FamilyRole.CHILD_13_PLUS  # default to paid if invalid
            age = relativedelta(datetime.now(timezone.utc).date(), dob).years
            return FamilyRole.CHILD_UNDER_12 if age < 13 else FamilyRole.CHILD_13_PLUS
        return FamilyRole.ADDITIONAL

    async def _count_paid_family_slots(self, subscription_id: str) -> int:
        """Count how many paid family slots currently exist."""
        return await self.db.fetchval(
            """SELECT COUNT(*) FROM subscription_items 
               WHERE subscription_id = $1 AND price_cents > 0""",
            subscription_id
        ) or 0

    async def _count_free_children(self, subscription_id: str) -> int:
        """Count CHILD_UNDER_12 members with price=0 (the free slot)."""
        return await self.db.fetchval(
            """SELECT COUNT(*) FROM subscription_items
               WHERE subscription_id = $1 AND family_role = 'CHILD_UNDER_12' AND price_cents = 0""",
            subscription_id
        ) or 0

    def _stripe_price_for_tier(self, ordinal: int) -> Optional[str]:
        """Return the Stripe price ID for a given family tier ordinal."""
        key = f"FAMILY_TIER_{min(ordinal, 4)}"
        return PRICES.get(key) or PRICES.get("FAMILY_MEMBER")

    async def recalculate_family_pricing(self, subscription_id: str, stripe_subscription_id: Optional[str] = None):
        """Recalculate paid slot ordinals and prices after add/remove/age-out.
        
        Pricing rules (Locked v3 adjusted):
        - SPOUSE: always $0
        - First CHILD_UNDER_12: $0 (one free slot)
        - Additional CHILD_UNDER_12, all CHILD_13_PLUS, all ADDITIONAL:
          priced by ordinal among paid members: 1st=$75, 2nd=$60, 3rd=$45, 4th+=$30
        """
        # Get all non-primary family items, ordered by creation date
        items = await self.db.fetch(
            """SELECT id, family_role, price_cents, stripe_subscription_item_id, date_of_birth
               FROM subscription_items
               WHERE subscription_id = $1
               ORDER BY created_at ASC""",
            subscription_id
        )

        free_child_assigned = False
        paid_ordinal = 0

        for item in items:
            role = item['family_role']
            new_price = 0
            new_ordinal = 0

            if role == 'SPOUSE':
                new_price = 0
                new_ordinal = 0
            elif role == 'CHILD_UNDER_12' and not free_child_assigned:
                # First child under 12 is free
                new_price = 0
                new_ordinal = 0
                free_child_assigned = True
            else:
                # This is a paid slot
                paid_ordinal += 1
                new_price = family_tier_price_cents(paid_ordinal)
                new_ordinal = paid_ordinal

            # Update DB if price or ordinal changed
            if item['price_cents'] != new_price or item.get('paid_slot_ordinal', 0) != new_ordinal:
                await self.db.execute(
                    """UPDATE subscription_items 
                       SET price_cents = $1, paid_slot_ordinal = $2 
                       WHERE id = $3""",
                    new_price, new_ordinal, item['id']
                )

                # Update Stripe if needed and price changed
                if stripe_subscription_id and item['stripe_subscription_item_id'] and item['price_cents'] != new_price:
                    try:
                        if new_price > 0:
                            stripe_price = self._stripe_price_for_tier(new_ordinal)
                            if stripe_price:
                                stripe.SubscriptionItem.modify(
                                    item['stripe_subscription_item_id'],
                                    price=stripe_price,
                                )
                        else:
                            # Became free — remove Stripe item
                            stripe.SubscriptionItem.delete(item['stripe_subscription_item_id'])
                            await self.db.execute(
                                "UPDATE subscription_items SET stripe_subscription_item_id = NULL WHERE id = $1",
                                item['id']
                            )
                    except Exception as e:
                        print(f">>> [STRIPE] Error updating family Stripe item: {e}")

    async def add_family_member(
        self,
        primary_user_id: str,
        member_email: str,
        member_name: str,
        relationship: str,
        date_of_birth: Optional[str] = None
    ) -> Dict[str, Any]:
        """Add a family member with DOB-aware tiered pricing (Locked v3).
        
        Pricing rules:
        - Spouse: always FREE
        - First child under 12: FREE
        - Children 13+, additional children under 12, other adults:
          tiered by ordinal: $75/$60/$45/$30
        """
        
        # Verify primary user has TOP_TIER
        sub = await self.db.fetchrow(
            "SELECT id, tier, stripe_subscription_id FROM subscriptions WHERE user_id = $1 AND status = 'ACTIVE'",
            primary_user_id
        )
        
        if not sub or sub['tier'] != 'TOP_TIER':
            raise HTTPException(403, "Family linking requires Sovereign Circle membership")
        
        # Determine role from relationship + DOB
        family_role = self._compute_family_role(relationship, date_of_birth)
        
        # Validate: only one spouse allowed
        if family_role == FamilyRole.SPOUSE:
            existing_spouse = await self.db.fetchval(
                "SELECT COUNT(*) FROM subscription_items WHERE subscription_id = $1 AND family_role = 'SPOUSE'",
                sub['id']
            )
            if existing_spouse and existing_spouse > 0:
                raise HTTPException(400, "Spouse already linked")
        
        # Determine if this member is free or paid
        is_free = False
        if family_role == FamilyRole.SPOUSE:
            is_free = True
        elif family_role == FamilyRole.CHILD_UNDER_12:
            free_children = await self._count_free_children(sub['id'])
            is_free = (free_children == 0)  # first child under 12 is free
        
        # Calculate price
        if is_free:
            price_cents = 0
            paid_ordinal = 0
        else:
            paid_count = await self._count_paid_family_slots(sub['id'])
            paid_ordinal = paid_count + 1
            price_cents = family_tier_price_cents(paid_ordinal)
        
        # Compute age for storage
        age_at_enrollment = None
        dob_date = None
        if date_of_birth:
            from datetime import date as _date
            from dateutil.relativedelta import relativedelta
            try:
                dob_date = _date.fromisoformat(date_of_birth)
                age_at_enrollment = relativedelta(
                    datetime.now(timezone.utc).date(), dob_date
                ).years
            except (ValueError, TypeError):
                dob_date = None
        
        # Create or get member user
        member_user = await self.db.fetchrow(
            "SELECT id FROM users WHERE LOWER(username) = LOWER($1) OR LOWER(email) = LOWER($1)",
            member_email
        )
        
        if not member_user:
            member_id = await self.db.fetchval(
                """
                INSERT INTO users (username, email, name, role, tier, family_role, linked_by, linked_at, subscription_status)
                VALUES ($1, $1, $2, 'CLIENT', 'STANDARD', $3, $4, NOW(), 'PENDING_INVITE')
                RETURNING id
                """,
                member_email, member_name, family_role.value, primary_user_id
            )
        else:
            member_id = member_user['id']
            await self.db.execute(
                "UPDATE users SET family_role = $1, linked_by = $2, linked_at = NOW(), tier = 'STANDARD' WHERE id = $3",
                family_role.value, primary_user_id, member_id
            )
        
        # Add to Stripe subscription if there's a charge
        stripe_item_id = None
        if price_cents > 0 and sub['stripe_subscription_id']:
            stripe_price = self._stripe_price_for_tier(paid_ordinal)
            if stripe_price:
                try:
                    item = stripe.SubscriptionItem.create(
                        subscription=sub['stripe_subscription_id'],
                        price=stripe_price,
                        quantity=1,
                        metadata={
                            "user_id": str(member_id),
                            "family_role": family_role.value,
                            "paid_slot": str(paid_ordinal)
                        }
                    )
                    stripe_item_id = item.id
                except Exception as e:
                    print(f">>> [STRIPE] Error adding family Stripe item: {e}")
        
        # Record in database
        await self.db.execute(
            """
            INSERT INTO subscription_items 
                (subscription_id, user_id, stripe_subscription_item_id, family_role, 
                 price_cents, date_of_birth, paid_slot_ordinal, age_at_enrollment)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            sub['id'], member_id, stripe_item_id, family_role.value,
            price_cents, dob_date, paid_ordinal, age_at_enrollment
        )
        
        # Send invitation email
        try:
            from app.services.notifications_service import EmailService
            email_svc = EmailService()
            inviter_name_row = await self.db.fetchval(
                "SELECT name FROM users WHERE id = $1", primary_user_id
            )
            accept_url = f"https://app.sovereignsanctuary.net/family/accept?member={member_id}"
            await email_svc.send_family_invitation(
                to_email=member_email,
                inviter_name=inviter_name_row or "Your family member",
                accept_url=accept_url,
            )
        except Exception as email_err:
            print(f">>> [STRIPE] Family invitation email error: {email_err}")
        
        return {
            "member_id": str(member_id),
            "email": member_email,
            "family_role": family_role.value,
            "date_of_birth": date_of_birth,
            "age": age_at_enrollment,
            "is_free": is_free,
            "monthly_cost": price_cents / 100,
            "paid_slot": paid_ordinal if not is_free else None,
            "status": "INVITED" if not member_user else "LINKED"
        }
    
    async def remove_family_member(self, primary_user_id: str, member_id: str) -> bool:
        """Remove a family member and recalculate tiered pricing for remaining members."""
        
        # Get subscription and item
        sub = await self.db.fetchrow(
            "SELECT id, stripe_subscription_id FROM subscriptions WHERE user_id = $1 AND status = 'ACTIVE'",
            primary_user_id
        )
        
        item = await self.db.fetchrow(
            """
            SELECT si.id, si.stripe_subscription_item_id 
            FROM subscription_items si
            JOIN subscriptions s ON si.subscription_id = s.id
            WHERE s.user_id = $1 AND si.user_id = $2
            """,
            primary_user_id, member_id
        )
        
        if not item:
            raise HTTPException(404, "Family member not found")
        
        # Remove from Stripe
        if item['stripe_subscription_item_id']:
            try:
                stripe.SubscriptionItem.delete(item['stripe_subscription_item_id'])
            except Exception as e:
                print(f">>> [STRIPE] Error removing family Stripe item: {e}")
        
        # Remove from database
        await self.db.execute("DELETE FROM subscription_items WHERE id = $1", item['id'])
        
        # Update user status
        await self.db.execute(
            "UPDATE users SET family_role = NULL, linked_by = NULL, tier = 'TRIAL' WHERE id = $1",
            member_id
        )
        
        # Recalculate pricing for remaining members (ordinals shift)
        if sub:
            await self.recalculate_family_pricing(sub['id'], sub['stripe_subscription_id'])
        
        return True
    
    # -------------------------------------------------------------------------
    # COACHING SESSIONS
    # -------------------------------------------------------------------------
    
    async def purchase_coaching_pack(
        self,
        user_id: str,
        email: str,
        name: str,
        pack_type: PackType,
        success_url: str,
        cancel_url: str
    ) -> CreateCheckoutResponse:
        """Create checkout for coaching session pack."""
        
        # Verify user has TOP_TIER
        tier = await self.db.fetchval(
            "SELECT tier FROM subscriptions WHERE user_id = $1 AND status = 'ACTIVE'",
            user_id
        )
        
        if tier != 'TOP_TIER':
            raise HTTPException(403, "Coaching sessions require Sovereign Circle membership")
        
        customer_id = await self.get_or_create_customer(user_id, email, name)
        config = PACK_CONFIGS[pack_type]
        price_id = PRICES[f"COACHING_{pack_type.value}"]
        
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="payment",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
            metadata={
                "user_id": user_id,
                "pack_type": pack_type.value,
                "sessions": str(config.sessions)
            }
        )
        
        return CreateCheckoutResponse(
            checkout_url=session.url,
            session_id=session.id
        )
    
    async def purchase_token_pack(
        self,
        user_id: str,
        username: str,
        email: str,
        name: str,
        pack_id: str,
        success_url: str,
        cancel_url: str,
    ) -> CreateCheckoutResponse:
        """Create Stripe checkout for a token pack purchase."""
        pack = TOKEN_PACKS.get(pack_id)
        if not pack:
            raise HTTPException(400, f"Invalid token pack: {pack_id}")

        price_key = f"TOKEN_{pack_id.upper()}"
        price_id = PRICES.get(price_key)

        customer_id = await self.get_or_create_customer(user_id, email, name)

        if price_id:
            line_items = [{"price": price_id, "quantity": 1}]
        else:
            line_items = [{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": pack["label"]},
                    "unit_amount": pack["price_cents"],
                },
                "quantity": 1,
            }]

        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="payment",
            payment_method_types=["card"],
            line_items=line_items,
            success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
            metadata={
                "type": "token_pack",
                "user_id": user_id,
                "username": username,
                "pack_id": pack_id,
                "tokens": str(pack["tokens"]),
            },
        )

        return CreateCheckoutResponse(checkout_url=session.url, session_id=session.id)

    async def charge_token_share_fee(
        self,
        user_id: str,
        email: str,
        name: str,
        tokens_shared: int,
        sharer_username: str,
        receiver_username: str,
    ) -> str:
        """Charge the sharer for BLE/NFC token sharing ($5 per 10k tokens, rounded up)."""
        import math
        fee_cents = math.ceil(tokens_shared / 10000) * 500

        customer_id = await self.get_or_create_customer(user_id, email, name)

        customer = stripe.Customer.retrieve(customer_id)
        default_pm = None
        if customer.invoice_settings and customer.invoice_settings.default_payment_method:
            default_pm = customer.invoice_settings.default_payment_method
        if not default_pm:
            methods = stripe.PaymentMethod.list(customer=customer_id, type="card", limit=1)
            if methods.data:
                default_pm = methods.data[0].id

        if not default_pm:
            raise ValueError("No payment method on file. Please add a card before sharing tokens.")

        intent = stripe.PaymentIntent.create(
            amount=fee_cents,
            currency="usd",
            customer=customer_id,
            payment_method=default_pm,
            confirm=True,
            off_session=True,
            description=f"Token share: {tokens_shared:,} tokens to {receiver_username}",
            metadata={
                "type": "token_share",
                "sharer_username": sharer_username,
                "receiver_username": receiver_username,
                "tokens_shared": str(tokens_shared),
                "fee_cents": str(fee_cents),
            },
        )

        if intent.status not in ("succeeded", "requires_capture"):
            raise ValueError(f"Payment failed with status: {intent.status}")

        return intent.id

    async def book_coaching_session(
        self,
        user_id: str,
        coach_id: str,
        scheduled_at: datetime,
        use_pack_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Book a coaching session."""
        
        # Verify user has TOP_TIER
        tier = await self.db.fetchval(
            "SELECT tier FROM subscriptions WHERE user_id = $1 AND status = 'ACTIVE'",
            user_id
        )
        
        if tier != 'TOP_TIER':
            raise HTTPException(403, "Coaching sessions require Sovereign Circle membership")
        
        # Check coach availability
        conflict = await self.db.fetchval(
            """
            SELECT id FROM coaching_sessions 
            WHERE coach_id = $1 AND scheduled_at = $2 AND status = 'SCHEDULED'
            """,
            coach_id, scheduled_at
        )
        
        if conflict:
            raise HTTPException(409, "Time slot not available")
        
        price_cents = None
        pack_id = None
        
        if use_pack_id:
            # Verify pack ownership and availability
            pack = await self.db.fetchrow(
                """
                SELECT id, sessions_remaining, expires_at 
                FROM session_packs 
                WHERE id = $1 AND user_id = $2
                """,
                use_pack_id, user_id
            )
            
            if not pack:
                raise HTTPException(404, "Session pack not found")
            if pack['sessions_remaining'] <= 0:
                raise HTTPException(400, "No sessions remaining in pack")
            if pack['expires_at'] < datetime.now(timezone.utc):
                raise HTTPException(400, "Session pack expired")
            
            pack_id = use_pack_id
            
            # Decrement pack
            await self.db.execute(
                "UPDATE session_packs SET sessions_remaining = sessions_remaining - 1 WHERE id = $1",
                use_pack_id
            )
        else:
            # Will charge card at session time (or create payment intent now)
            price_cents = 17500
        
        # Create booking
        session_id = await self.db.fetchval(
            """
            INSERT INTO coaching_sessions (client_id, coach_id, pack_id, scheduled_at, price_cents, status)
            VALUES ($1, $2, $3, $4, $5, 'SCHEDULED')
            RETURNING id
            """,
            user_id, coach_id, pack_id, scheduled_at, price_cents
        )
        
        # Send confirmation emails to client and coach
        try:
            from app.services.notifications_service import EmailService
            email_svc = EmailService()
            client_row = await self.db.fetchrow(
                "SELECT email, name FROM users WHERE id = $1", user_id
            )
            coach_row = await self.db.fetchrow(
                "SELECT email, name FROM users WHERE id = $1", coach_id
            )
            if client_row and coach_row:
                await email_svc.send_coaching_confirmation(
                    to_email=client_row["email"],
                    date=scheduled_at.strftime("%B %d, %Y"),
                    time=scheduled_at.strftime("%I:%M %p"),
                    timezone="UTC",
                    coach_name=coach_row["name"] or "Your coach",
                    coach_initials=(coach_row["name"] or "C")[0],
                    coach_credentials="",
                    join_url=f"https://app.sovereignsanctuary.net/session/{session_id}",
                )
        except Exception as email_err:
            print(f">>> [STRIPE] Coaching confirmation email error: {email_err}")

        # Schedule Nate briefing generation
        try:
            from app.services.nate_nudge import NateNudgeService
            nudge = NateNudgeService(self.db)
            # Create a session_prep nudge for the client
            import json as _json
            await self.db.execute(
                """INSERT INTO nate_nudges
                    (user_id, nudge_type, title, content, metadata, scheduled_at)
                VALUES ($1, 'session_prep', 'Coaching Session Prep',
                        $2, $3, $4)""",
                user_id,
                f"Your session with {coach_row['name'] if coach_row else 'your coach'} "
                f"is scheduled for {scheduled_at.strftime('%B %d at %I:%M %p')}. "
                f"Take a moment to reflect on what you'd like to explore.",
                _json.dumps({"session_id": str(session_id), "coach_id": coach_id}),
                scheduled_at - timedelta(hours=2),
            )
        except Exception as nudge_err:
            print(f">>> [STRIPE] Nate briefing scheduling error: {nudge_err}")
        
        return {
            "session_id": str(session_id),
            "coach_id": coach_id,
            "scheduled_at": scheduled_at.isoformat(),
            "paid_with_pack": pack_id is not None,
            "price": price_cents / 100 if price_cents else 0
        }
    
    # -------------------------------------------------------------------------
    # SUBSCRIPTION STATUS
    # -------------------------------------------------------------------------
    
    async def get_subscription_status(self, user_id: str) -> SubscriptionResponse:
        """Get user's current subscription status."""
        
        sub = await self.db.fetchrow(
            """
            SELECT tier, status, current_period_end, cancel_at_period_end, stripe_subscription_id
            FROM subscriptions WHERE user_id = $1 AND status IN ('ACTIVE', 'PAST_DUE')
            """,
            user_id
        )
        
        if not sub:
            return SubscriptionResponse(
                tier="TRIAL",
                status="ACTIVE",
                current_period_end=None,
                cancel_at_period_end=False,
                family_members=[],
                monthly_total_cents=0
            )
        
        # Get family members
        members = await self.db.fetch(
            """
            SELECT u.id, u.name, u.email, si.family_role, si.price_cents
            FROM subscription_items si
            JOIN users u ON si.user_id = u.id
            JOIN subscriptions s ON si.subscription_id = s.id
            WHERE s.user_id = $1
            """,
            user_id
        )
        
        # Calculate total
        base_price = 14900 if sub['tier'] == 'TOP_TIER' else 4900
        family_total = sum(m['price_cents'] or 0 for m in members)
        
        return SubscriptionResponse(
            tier=sub['tier'],
            status=sub['status'],
            current_period_end=sub['current_period_end'],
            cancel_at_period_end=sub['cancel_at_period_end'],
            family_members=[
                {
                    "id": str(m['id']),
                    "name": m['name'],
                    "email": m['email'],
                    "role": m['family_role'],
                    "monthly_cost": (m['price_cents'] or 0) / 100
                }
                for m in members
            ],
            monthly_total_cents=base_price + family_total
        )
    
    async def cancel_subscription(self, user_id: str, at_period_end: bool = True) -> bool:
        """Cancel subscription.
        
        HIVE DEFENSE v4.3: Routes through SovereignStripeProxy.
        """
        
        sub = await self.db.fetchrow(
            "SELECT stripe_subscription_id FROM subscriptions WHERE user_id = $1 AND status = 'ACTIVE'",
            user_id
        )
        
        if not sub or not sub['stripe_subscription_id']:
            raise HTTPException(404, "No active subscription")
        
        # ── HIVE DEFENSE v4.3: Use SovereignStripeProxy ──
        proxy = self._get_proxy()
        if proxy:
            result = await proxy.cancel_subscription(
                sub['stripe_subscription_id'], user_id, at_period_end
            )
            if result.get("success"):
                if at_period_end:
                    await self.db.execute(
                        "UPDATE subscriptions SET cancel_at_period_end = TRUE WHERE user_id = $1",
                        user_id
                    )
                else:
                    await self.db.execute(
                        "UPDATE subscriptions SET status = 'CANCELLED', cancelled_at = NOW() WHERE user_id = $1",
                        user_id
                    )
                return True
            _logger.warning("SovereignStripeProxy cancel failed, using direct API")

        # Fallback: direct Stripe call
        if at_period_end:
            stripe.Subscription.modify(
                sub['stripe_subscription_id'],
                cancel_at_period_end=True
            )
            await self.db.execute(
                "UPDATE subscriptions SET cancel_at_period_end = TRUE WHERE user_id = $1",
                user_id
            )
        else:
            stripe.Subscription.delete(sub['stripe_subscription_id'])
            await self.db.execute(
                "UPDATE subscriptions SET status = 'CANCELLED', cancelled_at = NOW() WHERE user_id = $1",
                user_id
            )
        
        return True


# =============================================================================
# WEBHOOK HANDLER
# =============================================================================

class StripeWebhookHandler:
    def __init__(self, db_pool: asyncpg.Pool):
        self.db = db_pool
        self._fortress = None  # Lazy-loaded from app.state

    def _get_fortress(self):
        """Get WebhookFortress instance (lazy-loaded)."""
        if self._fortress is None:
            try:
                from app.services.billing.webhook_fortress import WebhookFortress
                self._fortress = WebhookFortress(self.db)
            except Exception:
                pass
        return self._fortress
    
    async def handle_webhook(self, payload: bytes, sig_header: str) -> Dict[str, str]:
        """Process Stripe webhook event with 3-cord verification via WebhookFortress."""
        
        # ── HIVE DEFENSE v4.0: Route through WebhookFortress 3-cord verification ──
        fortress = self._get_fortress()
        if fortress:
            passed, event, reason = await fortress.verify_all_three_cords(payload, sig_header)
            if not passed:
                _logger.warning("WebhookFortress rejected event: %s", reason)
                raise HTTPException(400, f"Webhook verification failed: {reason}")
            event_type = event['type']
            data = event['data']['object']
            event_id = event.get('id', '')
        else:
            # Fallback: basic verification if fortress unavailable
            try:
                event = stripe.Webhook.construct_event(
                    payload, sig_header, WEBHOOK_SECRET
                )
            except ValueError:
                raise HTTPException(400, "Invalid payload")
            except stripe.error.SignatureVerificationError:
                raise HTTPException(400, "Invalid signature")

            import time
            event_created = event.get('created', 0)
            if event_created and (time.time() - event_created) > 300:
                return {"status": "rejected", "reason": "event_too_old"}

            event_type = event['type']
            data = event['data']['object']
            event_id = event.get('id', '')

            # Idempotency check (legacy path)
            if event_id:
                try:
                    existing = await self.db.fetchval(
                        "SELECT 1 FROM webhook_events WHERE event_id = $1", event_id
                    )
                    if existing:
                        return {"status": "already_processed", "event_type": event_type}
                except Exception:
                    pass

        handlers = {
            'checkout.session.completed': self._handle_checkout_completed,
            'invoice.paid': self._handle_invoice_paid,
            'invoice.payment_failed': self._handle_payment_failed,
            'customer.subscription.updated': self._handle_subscription_updated,
            'customer.subscription.deleted': self._handle_subscription_deleted,
        }

        handler = handlers.get(event_type)
        if handler:
            try:
                await handler(data)
            except Exception as e:
                print(f">>> [STRIPE WEBHOOK] Handler error for {event_type}: {e}")
                # Return 200 to prevent Stripe from retrying infinitely
                # Error is logged for investigation
                return {"status": "handler_error", "event_type": event_type}

        # Record processed event for idempotency
        if event_id:
            try:
                await self.db.execute(
                    "INSERT INTO webhook_events (event_id, provider, event_type) VALUES ($1, 'stripe', $2) ON CONFLICT DO NOTHING",
                    event_id, event_type
                )
            except Exception:
                pass

        # Mark as successfully processed in WebhookFortress ledger
        fortress = self._get_fortress()
        if fortress and event_id:
            try:
                await fortress.mark_processed(event_id)
            except Exception:
                pass

        return {"status": "processed", "event_type": event_type}
    
    async def _handle_checkout_completed(self, session: Dict):
        """Handle successful checkout."""
        
        metadata = session.get('metadata', {})

        # --- Stripe-first registration: pending_signup flow --- # QUANTUM-CRYSTAL-ARCH
        pending_signup_id = metadata.get("pending_signup_id")
        if pending_signup_id:
            await self._handle_pending_signup(session, pending_signup_id)
            return

        # --- Client-to-Coach upgrade flow --- # QUANTUM-CRYSTAL-ARCH
        if metadata.get("type") == "coach_upgrade":
            await self._handle_coach_upgrade(session, metadata)
            return

        user_id = metadata.get('user_id')
        
        if not user_id:
            return
        
        if session['mode'] == 'subscription':
            # Subscription checkout
            tier = metadata.get('tier', 'STANDARD')
            subscription_id = session.get('subscription')
            
            # Get subscription details
            sub = stripe.Subscription.retrieve(subscription_id)
            
            await self.db.execute(
                """
                INSERT INTO subscriptions (user_id, stripe_subscription_id, stripe_customer_id, tier, status, current_period_start, current_period_end)
                VALUES ($1, $2, $3, $4, 'ACTIVE', to_timestamp($5), to_timestamp($6))
                ON CONFLICT (user_id) DO UPDATE SET
                    stripe_subscription_id = EXCLUDED.stripe_subscription_id,
                    tier = EXCLUDED.tier,
                    status = 'ACTIVE',
                    current_period_start = EXCLUDED.current_period_start,
                    current_period_end = EXCLUDED.current_period_end
                """,
                user_id, subscription_id, session['customer'], tier,
                sub['current_period_start'], sub['current_period_end']
            )
            
            # Update user tier
            await self.db.execute(
                "UPDATE users SET tier = $1, subscription_status = 'ACTIVE' WHERE id = $2",
                tier, user_id
            )

            # Promo redemption is counted only after a successful checkout completion.
            # This prevents codes being consumed on abandoned or expired sessions.
            applied_source = metadata.get("applied_promo_source", "")
            applied_code = metadata.get("applied_promo_code", "")
            if applied_source and applied_code:
                cleaned_code = applied_code.strip().upper()[:40]
                try:
                    if applied_source == "promotional_specials":
                        await self.db.execute(
                            "UPDATE promotional_specials SET current_redemptions = current_redemptions + 1 WHERE promo_code = $1",
                            cleaned_code,
                        )
                    elif applied_source == "school_codes":
                        await self.db.execute(
                            "UPDATE school_codes SET current_students = current_students + 1 WHERE school_code = $1",
                            cleaned_code,
                        )
                    elif applied_source == "corporate_sponsors":
                        await self.db.execute(
                            "UPDATE corporate_sponsors SET current_employees = current_employees + 1 WHERE sponsor_code = $1",
                            cleaned_code,
                        )
                except Exception as e:
                    print(f">>> [STRIPE] Promo redemption update failed ({applied_source}/{applied_code}): {e}")

            # Notify bridge to reload this user's cache from PG
            try:
                from app.services.api_server import _get_auth_redis
                r = await _get_auth_redis()
                if r:
                    uname = await self.db.fetchval(
                        "SELECT username FROM users WHERE id = $1", user_id
                    )
                    if uname:
                        await r.publish(
                            "nate:user_reload",
                            json.dumps({"username": uname}),
                        )
            except Exception:
                pass

            # Founding member: atomically increment counter and mark user (first 100 paying members)
            try:
                async with self.db.acquire() as conn:
                    async with conn.transaction():
                        row = await conn.fetchrow(
                            "SELECT value FROM platform_config WHERE key = 'founding_member_count' FOR UPDATE"
                        )
                        if row and row["value"]:
                            cfg = row["value"] if isinstance(row["value"], dict) else json.loads(str(row["value"]))
                            count = int(cfg.get("count", 0) or 0)
                            max_count = int(cfg.get("max", 100) or 100)
                            if count < max_count:
                                new_count = count + 1
                                await conn.execute(
                                    """UPDATE platform_config SET value = jsonb_set(
                                        COALESCE(value, '{}'::jsonb), '{count}', to_jsonb($1::int)
                                    ), updated_at = NOW() WHERE key = 'founding_member_count'""",
                                    new_count
                                )
                                await conn.execute(
                                    "UPDATE users SET is_founding_member = TRUE, founding_member_number = $1 WHERE id = $2",
                                    new_count, user_id
                                )
                                print(f">>> [STRIPE] Founding member #{new_count}: {user_id}")
            except Exception as e:
                print(f">>> [STRIPE] Founding member update failed: {e}")
        
        elif session['mode'] == 'payment':
            checkout_type = metadata.get('type', '')
            if checkout_type == 'token_pack':
                pack_id = metadata.get('pack_id', '')
                tokens = int(metadata.get('tokens', 0))
                username = metadata.get('username', '')
                if tokens > 0 and username:
                    try:
                        async with self.db.acquire() as conn:
                            async with conn.transaction():
                                before = await conn.fetchval(
                                    "SELECT COALESCE(token_balance, 0) FROM users WHERE username = $1",
                                    username,
                                ) or 0
                                after = before + tokens
                                await conn.execute("""
                                    UPDATE users
                                    SET token_balance = $1,
                                        profile_data = jsonb_set(
                                            COALESCE(profile_data, '{}'::jsonb),
                                            '{token_balance}',
                                            to_jsonb($1::int)
                                        )
                                    WHERE username = $2
                                """, after, username)
                                await conn.execute("""
                                    INSERT INTO token_transactions
                                        (username, action, amount, balance_before, balance_after,
                                         reason, source, initiated_by, target_scope)
                                    VALUES ($1, 'purchase', $2, $3, $4, $5, 'token_pack', 'stripe', 'individual')
                                """, username, tokens, before, after,
                                    f"{pack_id} pack ({tokens:,} tokens)")
                        print(f">>> [STRIPE] Token pack purchased: {username} +{tokens:,} ({pack_id})")
                        try:
                            from app.services.api_server import _get_auth_redis
                            r = await _get_auth_redis()
                            if r:
                                await r.publish(
                                    "nate:balance_sync",
                                    json.dumps({"username": username, "token_balance": after}),
                                )
                                await r.publish(
                                    "nate:user_reload",
                                    json.dumps({"username": username}),
                                )
                        except Exception:
                            pass
                    except Exception as e:
                        print(f">>> [STRIPE] Token pack credit failed: {e}")
                return

            if checkout_type == 'dojo_subscription':
                dojo_key = metadata.get('dojo_key', '')
                coach_id = metadata.get('coach_id', '')
                if dojo_key and coach_id:
                    try:
                        from datetime import datetime as _dt
                        now_str = _dt.utcnow().isoformat()
                        async with self.db.acquire() as conn:
                            row = await conn.fetchrow(
                                "SELECT profile_data FROM users WHERE hardware_id = $1",
                                coach_id,
                            )
                            if row:
                                pd = row["profile_data"]
                                if isinstance(pd, str):
                                    pd = json.loads(pd)
                                pd = pd or {}
                                dojo_subs = pd.get("dojo_subscriptions", {})
                                dojo_subs[dojo_key] = {
                                    "status": "active",
                                    "started_at": now_str,
                                    "stripe_subscription_id": session.get("subscription", ""),
                                }
                                pd["dojo_subscriptions"] = dojo_subs
                                await conn.execute(
                                    "UPDATE users SET profile_data = $1::jsonb WHERE hardware_id = $2",
                                    json.dumps(pd), coach_id,
                                )
                        print(f">>> [STRIPE] DOJO activated: {dojo_key} for coach {coach_id}")
                        try:
                            from app.services.api_server import _get_auth_redis
                            r = await _get_auth_redis()
                            if r:
                                uname = await self.db.fetchval(
                                    "SELECT username FROM users WHERE hardware_id = $1", coach_id
                                )
                                if uname:
                                    await r.publish(
                                        "nate:user_reload",
                                        json.dumps({"username": uname}),
                                    )
                        except Exception:
                            pass
                    except Exception as e:
                        print(f">>> [STRIPE] DOJO activation failed: {e}")
                return

            pack_type = metadata.get('pack_type')
            if pack_type:
                config = PACK_CONFIGS[PackType(pack_type)]
                expires_at = datetime.now(timezone.utc) + timedelta(
                    days=config.validity_days
                )
                
                await self.db.execute(
                    """
                    INSERT INTO session_packs (user_id, pack_type, sessions_total, sessions_remaining, price_cents, stripe_payment_id, expires_at)
                    VALUES ($1, $2, $3, $3, $4, $5, $6)
                    """,
                    user_id, pack_type, config.sessions, config.price_cents,
                    session['payment_intent'], expires_at
                )
    
    async def _handle_invoice_paid(self, invoice: Dict):
        """Handle successful invoice payment."""
        
        subscription_id = invoice.get('subscription')
        if not subscription_id:
            return
        
        # Record payment
        customer_id = invoice['customer']
        user_id = await self.db.fetchval(
            "SELECT id FROM users WHERE stripe_customer_id = $1",
            customer_id
        )
        
        if user_id:
            await self.db.execute(
                """
                INSERT INTO payment_history (user_id, stripe_invoice_id, amount_cents, status, event_type)
                VALUES ($1, $2, $3, 'SUCCEEDED', 'invoice.paid')
                """,
                user_id, invoice['id'], invoice['amount_paid']
            )
            
            # Update subscription period
            sub = stripe.Subscription.retrieve(subscription_id)
            await self.db.execute(
                """
                UPDATE subscriptions 
                SET current_period_start = to_timestamp($1), current_period_end = to_timestamp($2), status = 'ACTIVE'
                WHERE stripe_subscription_id = $3
                """,
                sub['current_period_start'], sub['current_period_end'], subscription_id
            )
    
    async def _handle_payment_failed(self, invoice: Dict):
        """Handle failed payment."""
        
        customer_id = invoice['customer']
        user_id = await self.db.fetchval(
            "SELECT id FROM users WHERE stripe_customer_id = $1",
            customer_id
        )
        
        if user_id:
            await self.db.execute(
                """
                INSERT INTO payment_history (user_id, stripe_invoice_id, amount_cents, status, event_type)
                VALUES ($1, $2, $3, 'FAILED', 'invoice.payment_failed')
                """,
                user_id, invoice['id'], invoice['amount_due']
            )
            
            # Update subscription status
            await self.db.execute(
                "UPDATE subscriptions SET status = 'PAST_DUE' WHERE user_id = $1",
                user_id
            )
            
            # Send payment failed email
            try:
                from app.services.notifications_service import EmailService
                email_svc = EmailService()
                user_row = await self.db.fetchrow(
                    "SELECT email, name FROM users WHERE id = $1", user_id
                )
                if user_row:
                    amount_str = f"${invoice['amount_due'] / 100:.2f}" if invoice.get('amount_due') else "$0.00"
                    await email_svc.send_payment_failed(
                        to_email=user_row["email"],
                        amount=amount_str,
                        date=datetime.now(timezone.utc).strftime("%B %d, %Y"),
                    )
            except Exception as email_err:
                print(f">>> [STRIPE] Payment failed email error: {email_err}")

            # Add to crisis/attention watchlist if repeated failures
            try:
                failure_count = await self.db.fetchval(
                    """SELECT COUNT(*) FROM payment_history
                       WHERE user_id = $1 AND status = 'FAILED'
                         AND created_at > NOW() - INTERVAL '30 days'""",
                    user_id,
                )
                if failure_count and failure_count >= 2:
                    # Check if already in crisis watchlist
                    existing = await self.db.fetchval(
                        "SELECT 1 FROM crisis_watchlist WHERE user_id = $1 AND resolved_at IS NULL",
                        user_id,
                    )
                    if not existing:
                        await self.db.execute(
                            """INSERT INTO crisis_watchlist
                                (user_id, severity, trigger_type, trigger_context)
                            VALUES ($1, 'MEDIUM', 'payment_failure',
                                    $2)""",
                            user_id,
                            f"Repeated payment failures ({failure_count} in 30 days). "
                            f"May indicate financial stress or disengagement.",
                        )
                        print(f">>> [STRIPE] User {user_id} added to crisis watchlist "
                              f"({failure_count} payment failures)")
            except Exception as watchlist_err:
                print(f">>> [STRIPE] Watchlist integration error: {watchlist_err}")
    
    async def _handle_pending_signup(self, session: Dict, pending_signup_id: str):
        """Finalize a Stripe-first registration after payment.""" # QUANTUM-CRYSTAL-ARCH
        import uuid as _uuid
        try:
            signup_uuid = _uuid.UUID(pending_signup_id)
        except (ValueError, AttributeError):
            print(f">>> [STRIPE] Invalid pending_signup_id: {pending_signup_id}")
            return
        try:
            row = await self.db.fetchrow(
                "SELECT * FROM pending_signups WHERE id = $1 AND status = 'pending'",
                signup_uuid,
            )
        except Exception as e:
            print(f">>> [STRIPE] pending_signups lookup failed: {e}")
            return

        if not row:
            expired = await self.db.fetchval(
                "SELECT status FROM pending_signups WHERE id = $1", signup_uuid
            )
            if expired == "expired":
                print(f">>> [STRIPE] WARNING: Payment for expired pending_signup "
                      f"{pending_signup_id}. Session {session.get('id')} may need refund.")
                try:
                    import sendgrid
                    from sendgrid.helpers.mail import Mail
                    sg_key = os.getenv("SENDGRID_API_KEY")
                    if sg_key:
                        msg = Mail(
                            from_email="support@sovereignsanctuary.net",
                            to_emails="support@sovereignsanctuary.net",
                            subject="[URGENT] Expired Registration Payment Needs Refund",
                            html_content=(
                                f"<p>pending_signup <code>{pending_signup_id}</code> expired "
                                f"but Stripe session <code>{session.get('id')}</code> completed.</p>"
                                f"<p>Review in Stripe dashboard and issue refund if needed.</p>"
                            ),
                        )
                        sendgrid.SendGridAPIClient(api_key=sg_key).send(msg)
                except Exception as _sg_err:
                    print(f">>> [STRIPE] Expired signup alert email failed: {_sg_err}")
            return

        payload = row["payload"] if isinstance(row["payload"], dict) else {}
        dojos = row["selected_dojos"] if isinstance(row["selected_dojos"], list) else []

        try:
            from app.services.registration_finalize import finalize_signup
            ok, reason = await finalize_signup(
                self.db,
                role=row["role"],
                username=row["username"],
                password_hash=row["password_hash"],
                email=row["email"] or "",
                profile_fields=payload,
                tier=row["tier"] or "",
                selected_dojos=dojos,
                discount_code=row["discount_code"] or "",
                stripe_customer_id=session.get("customer", ""),
                stripe_checkout_session_id=session.get("id", ""),
            )
        except Exception as e:
            print(f">>> [STRIPE] finalize_signup exception: {e}")
            ok, reason = False, f"EXCEPTION: {e}"

        if ok:
            await self.db.execute(
                "UPDATE pending_signups SET status='completed', consumed_at=NOW() WHERE id=$1",
                signup_uuid,
            )
            print(f">>> [STRIPE] Registration finalized for {row['username']}")
            await self._send_registration_receipt(row)
        else:
            await self.db.execute(
                "UPDATE pending_signups SET status='cancelled' WHERE id=$1",
                signup_uuid,
            )
            print(f">>> [STRIPE] Registration finalize FAILED for {row['username']}: "
                  f"{reason}. Session {session.get('id')} needs refund.")

    async def _send_registration_receipt(self, signup_row):
        """Send welcome email after successful Stripe-first registration."""
        email = signup_row.get("email")
        username = signup_row.get("username")
        if not email:
            return
        try:
            import sendgrid
            from sendgrid.helpers.mail import Mail
            sg_key = os.getenv("SENDGRID_API_KEY")
            if not sg_key:
                return
            payload = signup_row.get("payload", {})
            if isinstance(payload, str):
                import json as _json
                payload = _json.loads(payload)
            name = payload.get("name", username)
            tier = signup_row.get("tier", "")
            message = Mail(
                from_email="support@sovereignsanctuary.net",
                to_emails=email,
                subject="Welcome to Sovereign Sanctuary — Your account is ready",
                html_content=(
                    f"<h2>Welcome, {name}!</h2>"
                    f"<p>Your <strong>{tier}</strong> account has been created.</p>"
                    f"<p><strong>Username:</strong> {username}</p>"
                    f"<p>Sign in at "
                    f"<a href='https://app.sovereignsanctuary.net'>app.sovereignsanctuary.net</a></p>"
                    f"<p style='color:#888;font-size:12px'>This is your payment confirmation. "
                    f"Your password was not stored in this email for security.</p>"
                ),
            )
            sg = sendgrid.SendGridAPIClient(api_key=sg_key)
            sg.send(message)
            print(f">>> [STRIPE] Welcome email sent to {email}")
        except Exception as e:
            print(f">>> [STRIPE] Welcome email failed: {e}")

    async def _handle_coach_upgrade(self, session: Dict, metadata: Dict):
        """Handle client-to-coach upgrade after Stripe payment.""" # QUANTUM-CRYSTAL-ARCH
        username = metadata.get("username", "")
        hw_id = metadata.get("hardware_id", "")
        if not username:
            print(f">>> [STRIPE] Coach upgrade missing username in metadata")
            return
        try:
            import json as _json
            dojos = _json.loads(metadata.get("selected_dojos", "[]"))
            coaching_fee = float(metadata.get("coaching_fee", 0))
            zoom_link = metadata.get("zoom_link", "")
            email = metadata.get("email", "")
            phone = metadata.get("phone", "")

            upgrade_data = {
                "selected_dojos": dojos,
                "coaching_fee": coaching_fee,
                "zoom_link": zoom_link,
                "email": email,
                "phone": phone,
                "stripe_subscription_id": session.get("subscription", ""),
                "stripe_customer_id": session.get("customer", ""),
            }

            await self.db.execute(
                """UPDATE users SET profile_data = jsonb_set(
                    jsonb_set(profile_data, '{upgrade_to_coach_status}', '"PAID_PENDING"'),
                    '{coach_upgrade_data}', $1::jsonb
                ) WHERE username = $2""",
                _json.dumps(upgrade_data),
                username,
            )
            print(f">>> [STRIPE] Coach upgrade payment received for {username}, "
                  f"status=PAID_PENDING, dojos={dojos}")
        except Exception as e:
            print(f">>> [STRIPE] Coach upgrade processing failed for {username}: {e}")

    async def _handle_subscription_updated(self, subscription: Dict):
        """Handle subscription changes."""
        
        subscription_id = subscription['id']
        
        tier = subscription.get('metadata', {}).get('tier', 'STANDARD')
        new_status = 'ACTIVE' if subscription['status'] == 'active' else subscription['status'].upper()
        
        await self.db.execute(
            """
            UPDATE subscriptions SET
                tier = $1,
                status = $2,
                current_period_end = to_timestamp($3),
                cancel_at_period_end = $4
            WHERE stripe_subscription_id = $5
            """,
            tier, new_status,
            subscription['current_period_end'],
            subscription['cancel_at_period_end'],
            subscription_id
        )
        
        uname = await self.db.fetchval(
            """SELECT u.username FROM users u
               JOIN subscriptions s ON s.user_id = u.id
               WHERE s.stripe_subscription_id = $1""",
            subscription_id
        )
        if uname:
            await self.db.execute(
                "UPDATE users SET tier = $1, subscription_status = $2 WHERE username = $3",
                tier, new_status, uname
            )
            await self._notify_bridge_reload(uname)
    
    async def _handle_subscription_deleted(self, subscription: Dict):
        """Handle subscription cancellation."""
        
        subscription_id = subscription['id']
        
        user_id = await self.db.fetchval(
            "SELECT user_id FROM subscriptions WHERE stripe_subscription_id = $1",
            subscription_id
        )
        
        if user_id:
            await self.db.execute(
                "UPDATE subscriptions SET status = 'CANCELLED', cancelled_at = NOW() WHERE stripe_subscription_id = $1",
                subscription_id
            )
            
            await self.db.execute(
                "UPDATE users SET tier = 'TRIAL', subscription_status = 'CANCELLED' WHERE id = $1",
                user_id
            )
            
            await self.db.execute(
                "UPDATE users SET tier = 'TRIAL', family_role = NULL WHERE linked_by = $1",
                user_id
            )
            
            uname = await self.db.fetchval("SELECT username FROM users WHERE id = $1", user_id)
            if uname:
                await self._notify_bridge_reload(uname)
            family_members = await self.db.fetch(
                "SELECT username FROM users WHERE linked_by = $1", user_id
            )
            for fm in family_members:
                await self._notify_bridge_reload(fm["username"])


# =============================================================================
# API ROUTER
# =============================================================================

def create_billing_router(db_pool: asyncpg.Pool) -> APIRouter:
    """Create FastAPI router for billing endpoints."""
    
    router = APIRouter(prefix="/api/billing", tags=["billing"])
    service = StripeService(db_pool)
    webhook_handler = StripeWebhookHandler(db_pool)
    
    @router.post("/checkout", response_model=CreateCheckoutResponse)
    async def create_checkout(request: CreateCheckoutRequest, user_id: str = Depends(get_current_user_id)):
        user = await db_pool.fetchrow("SELECT email, name FROM users WHERE id = $1", user_id)
        return await service.create_subscription_checkout(
            user_id, user['email'], user['name'],
            request.tier, request.success_url, request.cancel_url,
            promo_code=request.promo_code
        )
    
    @router.get("/subscription", response_model=SubscriptionResponse)
    async def get_subscription(user_id: str = Depends(get_current_user_id)):
        return await service.get_subscription_status(user_id)
    
    @router.post("/subscription/cancel")
    async def cancel_subscription(user_id: str = Depends(get_current_user_id), at_period_end: bool = True):
        return await service.cancel_subscription(user_id, at_period_end)
    
    @router.post("/family/add")
    async def add_family_member(request: AddFamilyMemberRequest, user_id: str = Depends(get_current_user_id)):
        return await service.add_family_member(
            user_id, request.email, request.name, 
            request.relationship, request.date_of_birth
        )
    
    @router.delete("/family/{member_id}")
    async def remove_family_member(member_id: str, user_id: str = Depends(get_current_user_id)):
        return await service.remove_family_member(user_id, member_id)
    
    @router.post("/coaching/purchase", response_model=CreateCheckoutResponse)
    async def purchase_coaching_pack(request: PurchaseCoachingPackRequest, user_id: str = Depends(get_current_user_id)):
        user = await db_pool.fetchrow("SELECT email, name FROM users WHERE id = $1", user_id)
        return await service.purchase_coaching_pack(
            user_id, user['email'], user['name'],
            request.pack_type, request.success_url, request.cancel_url
        )
    
    @router.post("/coaching/book")
    async def book_coaching_session(request: BookCoachingSessionRequest, user_id: str = Depends(get_current_user_id)):
        return await service.book_coaching_session(
            user_id, request.coach_id, request.scheduled_at, request.use_pack_id
        )
    
    @router.post("/webhook")
    async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
        payload = await request.body()
        return await webhook_handler.handle_webhook(payload, stripe_signature)
    
    return router
