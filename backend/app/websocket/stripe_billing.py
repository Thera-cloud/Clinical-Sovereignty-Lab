"""
LITTLE NATE - Complete Stripe Billing System
Version: 2.0
Date: January 23, 2026

Full Stripe integration for subscriptions, checkout, and webhooks.
"""

import json
import datetime
import secrets
import os

FOUNDING_COUPON_ID = os.getenv("STRIPE_FOUNDING_COUPON_ID", "FOUNDING_20PCT")
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# Stripe import with fallback
try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False
    print(">>> [BILLING] Stripe not installed. Run: pip3 install stripe")


class StripeBillingSystem:
    """Complete Stripe billing integration."""
    
    # Plan configurations — aligned with config/standing_orders_seed.json
    # Coaching sessions are a separate paid service based on coach pricing (not included in plans)
    # Voice therapy is prepaid in 20-minute blocks ($50/$250/$500/$1000)
    PLANS = {
        "COACH_ONLY": {
            "name": "Coach Only",
            "tokens": 0,
            "price_monthly": 0,
            "price_yearly": 0,
            "can_access_nate": False,
            "features": ["Coach sessions only", "No AI access"]
        },
        "TRIAL": {
            "name": "Threshold (Trial)",
            "tokens": 10000,
            "price_monthly": 0,
            "price_yearly": 0,
            "duration_days": 7,
            "features": [
                "7-day free trial",
                "10,000 AI tokens",
                "Text conversations with Little Nate"
            ]
        },
        "STANDARD": {
            "name": "Inner Chamber",
            "tokens": 50000,
            "price_monthly": 49,
            "price_yearly": 490,
            "family_sanctuary": True,
            "legacy_vault_gb": 1,
            "features": ["50,000 tokens/month", "Voice biometrics & emotional tracking", "1 GB Legacy Vault"]
        },
        "TOP_TIER": {
            "name": "Sovereign Circle",
            "tokens": 200000,
            "price_monthly": 149,
            "price_yearly": 1490,
            "family_sanctuary": True,
            "me2me": True,
            "legacy_vault_gb": 50,
            "features": ["200,000 tokens/month", "Me2Me avatars", "50 GB Legacy Vault", "Family Sanctuary", "Up to 5 family members"]
        },
    }
    
    def __init__(self, data_dir, stripe_key=None, webhook_secret=None, 
                 registry_loader=None, registry_saver=None, db_pool=None):
        self.data_dir = Path(data_dir)
        self.billing_file = self.data_dir / "billing.json"
        self.transactions_file = self.data_dir / "transactions.json"
        self.webhook_secret = webhook_secret
        self.registry_loader = registry_loader
        self.registry_saver = registry_saver
        self.db_pool = db_pool  # Optional: for founding member eligibility (platform_config)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize Stripe
        self.stripe_enabled = False
        if STRIPE_AVAILABLE and stripe_key:
            stripe.api_key = stripe_key
            self.stripe_enabled = True
            print(f">>> [BILLING] Stripe initialized (key: ...{stripe_key[-8:]})")
        else:
            print(">>> [BILLING] Stripe disabled - using local billing only")
        
        # Load price IDs from environment (monthly + yearly subscriptions)
        self.price_ids = {
            "STANDARD_MONTHLY": os.getenv("STRIPE_PRICE_STANDARD"),
            "STANDARD_YEARLY": os.getenv("STRIPE_PRICE_STANDARD_YEARLY"),
            "TOP_TIER_MONTHLY": os.getenv("STRIPE_PRICE_TOP_TIER"),
            "TOP_TIER_YEARLY": os.getenv("STRIPE_PRICE_TOP_TIER_YEARLY"),
            "FAMILY_MONTHLY": os.getenv("STRIPE_PRICE_FAMILY_MEMBER"),
            "COACHING_SINGLE": os.getenv("STRIPE_PRICE_COACHING_SINGLE"),
            "COACHING_4PACK": os.getenv("STRIPE_PRICE_COACHING_4PACK"),
            "COACHING_8PACK": os.getenv("STRIPE_PRICE_COACHING_8PACK"),
        }
    
    # =========================================================================
    # DATA MANAGEMENT
    # =========================================================================
    
    def _load_billing(self) -> dict:
        if not self.billing_file.exists():
            return {"customers": {}, "subscriptions": {}, "coaching_credits": {}}
        try:
            with open(self.billing_file, 'r') as f:
                return json.load(f)
        except:
            return {"customers": {}, "subscriptions": {}, "coaching_credits": {}}
    
    def _save_billing(self, data: dict):
        with open(self.billing_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    
    def _load_transactions(self) -> list:
        if not self.transactions_file.exists():
            return []
        try:
            with open(self.transactions_file, 'r') as f:
                return json.load(f)
        except:
            return []
    
    def _save_transaction(self, transaction: dict):
        transactions = self._load_transactions()
        transactions.append(transaction)
        with open(self.transactions_file, 'w') as f:
            json.dump(transactions[-1000:], f, indent=2, default=str)  # Keep last 1000
    
    # =========================================================================
    # CUSTOMER MANAGEMENT
    # =========================================================================
    
    async def get_or_create_customer(self, user_id: str, email: str, name: str) -> Optional[str]:
        """Get existing or create new Stripe customer."""
        billing = self._load_billing()
        
        # Check if customer exists locally
        if user_id in billing.get("customers", {}):
            customer_id = billing["customers"][user_id].get("stripe_customer_id")
            if customer_id:
                return customer_id
        
        if not self.stripe_enabled:
            # Create local-only customer
            local_customer_id = f"cus_local_{secrets.token_hex(12)}"
            billing.setdefault("customers", {})[user_id] = {
                "stripe_customer_id": local_customer_id,
                "email": email,
                "name": name,
                "created_at": str(datetime.datetime.now()),
                "local_only": True
            }
            self._save_billing(billing)
            return local_customer_id
        
        try:
            # Create Stripe customer
            customer = stripe.Customer.create(
                email=email,
                name=name,
                metadata={
                    "user_id": user_id,
                    "platform": "little_nate"
                }
            )
            
            # Store locally
            billing.setdefault("customers", {})[user_id] = {
                "stripe_customer_id": customer.id,
                "email": email,
                "name": name,
                "created_at": str(datetime.datetime.now()),
                "local_only": False
            }
            self._save_billing(billing)
            
            # Update user registry
            if self.registry_loader and self.registry_saver:
                registry = self.registry_loader()
                for k, v in registry.items():
                    if v.get("profile", {}).get("hardware_id") == user_id:
                        v["profile"]["stripe_customer_id"] = customer.id
                        self.registry_saver(registry)
                        break
            
            print(f">>> [BILLING] Created Stripe customer: {customer.id}")
            return customer.id
            
        except stripe.error.StripeError as e:
            print(f">>> [BILLING] Stripe error creating customer: {e}")
            return None
    
    # =========================================================================
    # CHECKOUT & SUBSCRIPTION
    # =========================================================================
    
    async def create_checkout_session(self, user_id: str, plan: str, 
                                       billing_cycle: str, success_url: str, 
                                       cancel_url: str,
                                       promo_code: Optional[str] = None) -> Optional[str]:
        """Create Stripe checkout session for subscription."""
        
        # Get user info
        email = ""
        name = ""
        if self.registry_loader:
            registry = self.registry_loader()
            for k, v in registry.items():
                if v.get("profile", {}).get("hardware_id") == user_id:
                    email = v["profile"].get("email", "")
                    name = v["profile"].get("name", "")
                    break
        
        if not self.stripe_enabled:
            # Return mock URL for testing
            print(f">>> [BILLING] Mock checkout for {plan} ({billing_cycle})")
            return f"https://checkout.stripe.com/mock?plan={plan}&user={user_id}"
        
        # Get or create customer
        customer_id = await self.get_or_create_customer(user_id, email, name)
        if not customer_id:
            return None
        
        # Get price ID — supports both monthly and yearly billing cycles
        cycle = billing_cycle.upper() if billing_cycle else "MONTHLY"
        if cycle not in ("MONTHLY", "YEARLY"):
            cycle = "MONTHLY"
        price_key = f"{plan.upper()}_{cycle}"
        price_id = self.price_ids.get(price_key)
        
        # Fallback: if yearly price not configured, use monthly
        if not price_id and cycle == "YEARLY":
            print(f">>> [BILLING] No yearly price for {plan}, falling back to monthly")
            price_key = f"{plan.upper()}_MONTHLY"
            price_id = self.price_ids.get(price_key)
            cycle = "MONTHLY"
        
        if not price_id:
            print(f">>> [BILLING] No price ID for plan: {plan}")
            return None
        
        # Founding member eligibility (first 100 paying members get 20% off for life)
        founding_eligible = False
        if self.db_pool and plan.upper() in ("STANDARD", "TOP_TIER"):
            try:
                row = await self.db_pool.fetchrow(
                    "SELECT value FROM platform_config WHERE key = 'founding_member_count'"
                )
                if row and row.get("value"):
                    cfg = row["value"] if isinstance(row["value"], dict) else json.loads(str(row["value"]))
                    count = int(cfg.get("count", 0) or 0)
                    max_count = int(cfg.get("max", 100) or 100)
                    if count < max_count:
                        # Check user not already founding member (user_id may be hardware_id; users.id may differ)
                        existing = await self.db_pool.fetchval(
                            """SELECT 1 FROM users WHERE (id::text = $1 OR stripe_customer_id IN (
                                SELECT stripe_customer_id FROM users WHERE id::text = $1
                            )) AND is_founding_member = TRUE""",
                            user_id
                        )
                        if not existing:
                            existing_by_hwid = await self.db_pool.fetchval(
                                "SELECT is_founding_member FROM users WHERE id = $1", user_id
                            )
                            if not existing_by_hwid:
                                founding_eligible = True
            except Exception as e:
                print(f">>> [BILLING] Founding member check failed: {e}")
        
        resolved_promo = None
        if promo_code and self.db_pool and not founding_eligible:
            try:
                import re as _re
                cleaned = promo_code.strip().upper()[:40]
                if _re.match(r'^[A-Z0-9_\-]{2,40}$', cleaned):
                    # 1. Check promotional_specials
                    row = await self.db_pool.fetchrow("""
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
                    """, cleaned, plan.upper())
                    if row and row["stripe_coupon_id"]:
                        resolved_promo = {
                            "coupon_id": row["stripe_coupon_id"],
                            "code": cleaned,
                            "is_full": row["discount_type"] == "percent" and int(row["discount_value"] or 0) >= 100,
                        }
                    # 2. Check school_codes
                    if not resolved_promo:
                        school = await self.db_pool.fetchrow("""
                            SELECT id, stripe_coupon_id, discount_percent
                            FROM school_codes
                            WHERE school_code = $1 AND active = TRUE
                              AND (max_students IS NULL OR current_students < max_students)
                        """, cleaned)
                        if school and school.get("stripe_coupon_id"):
                            resolved_promo = {
                                "coupon_id": school["stripe_coupon_id"],
                                "code": cleaned,
                                "is_full": int(school.get("discount_percent") or 0) >= 100,
                            }
                    # 3. Check corporate_sponsors
                    if not resolved_promo:
                        corp = await self.db_pool.fetchrow("""
                            SELECT id, stripe_coupon_id, discount_type, discount_value, pays_full
                            FROM corporate_sponsors
                            WHERE sponsor_code = $1 AND active = TRUE
                              AND (max_employees IS NULL OR current_employees < max_employees)
                        """, cleaned)
                        if corp and corp.get("stripe_coupon_id"):
                            resolved_promo = {
                                "coupon_id": corp["stripe_coupon_id"],
                                "code": cleaned,
                                "is_full": bool(corp.get("pays_full")),
                            }
            except Exception as e:
                print(f">>> [BILLING] Promo resolution failed for {promo_code}: {e}")

        try:
            session_params = {
                "customer": customer_id,
                "payment_method_types": ["card"],
                "line_items": [{"price": price_id, "quantity": 1}],
                "mode": "subscription",
                "success_url": success_url + "?session_id={CHECKOUT_SESSION_ID}",
                "cancel_url": cancel_url,
                "metadata": {"user_id": user_id, "plan": plan, "billing_cycle": billing_cycle},
                "subscription_data": {"metadata": {"user_id": user_id, "plan": plan}},
            }
            if founding_eligible:
                session_params["discounts"] = [{"coupon": FOUNDING_COUPON_ID}]
            elif resolved_promo:
                session_params["discounts"] = [{"coupon": resolved_promo["coupon_id"]}]
                session_params["metadata"]["applied_promo_code"] = resolved_promo["code"]
                session_params["metadata"]["applied_promo_source"] = "promotional_specials"
                if resolved_promo["is_full"]:
                    session_params["payment_method_collection"] = "if_required"
            else:
                session_params["allow_promotion_codes"] = True
            
            session = stripe.checkout.Session.create(**session_params)
            
            print(f">>> [BILLING] Created checkout session: {session.id}")
            return session.url
            
        except stripe.error.StripeError as e:
            print(f">>> [BILLING] Stripe error creating checkout: {e}")
            return None
    
    async def create_portal_session(self, user_id: str, return_url: str) -> Optional[str]:
        """Create Stripe billing portal session for subscription management."""
        
        billing = self._load_billing()
        customer_id = billing.get("customers", {}).get(user_id, {}).get("stripe_customer_id")
        
        if not customer_id:
            print(f">>> [BILLING] No customer found for user: {user_id}")
            return None
        
        if not self.stripe_enabled:
            return f"https://billing.stripe.com/mock/portal?customer={customer_id}"
        
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url
            )
            
            print(f">>> [BILLING] Created portal session for customer: {customer_id}")
            return session.url
            
        except stripe.error.StripeError as e:
            print(f">>> [BILLING] Stripe error creating portal: {e}")
            return None
    
    # =========================================================================
    # COACHING SESSIONS PURCHASE
    # =========================================================================
    
    async def create_coaching_checkout(self, user_id: str, package: str,
                                        success_url: str, cancel_url: str) -> Optional[str]:
        """Create checkout for coaching session packages."""
        
        package_map = {
            "single": ("COACHING_SINGLE", 1),
            "4pack": ("COACHING_4PACK", 4),
            "8pack": ("COACHING_8PACK", 8)
        }
        
        if package not in package_map:
            return None
        
        price_key, sessions = package_map[package]
        price_id = self.price_ids.get(price_key)
        
        if not price_id or not self.stripe_enabled:
            return None
        
        # Get customer
        email, name = "", ""
        if self.registry_loader:
            registry = self.registry_loader()
            for k, v in registry.items():
                if v.get("profile", {}).get("hardware_id") == user_id:
                    email = v["profile"].get("email", "")
                    name = v["profile"].get("name", "")
                    break
        
        customer_id = await self.get_or_create_customer(user_id, email, name)
        if not customer_id:
            return None
        
        try:
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[{
                    "price": price_id,
                    "quantity": 1
                }],
                mode="payment",  # One-time payment
                success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
                cancel_url=cancel_url,
                metadata={
                    "user_id": user_id,
                    "type": "coaching_sessions",
                    "package": package,
                    "sessions": sessions
                }
            )
            
            return session.url
            
        except stripe.error.StripeError as e:
            print(f">>> [BILLING] Stripe error: {e}")
            return None
    
    # =========================================================================
    # FAMILY MEMBER BILLING
    # =========================================================================
    
    FAMILY_PRICING = {
        "SPOUSE": 0,
        "PARTNER": 0,
        "CHILD_FIRST_FREE": 0,
        "DEPENDENT": 7500,      # $75/mo (in cents) — first paid member
        "DEPENDENT_2": 6000,    # $60/mo — second paid member
        "DEPENDENT_3": 4500,    # $45/mo — third paid member
        "DEPENDENT_4_PLUS": 3000,  # $30/mo — fourth+ paid members
    }
    
    def _get_family_member_price(self, role: str, family_id: str) -> int:
        """Calculate price in cents for a new family member based on role and existing members."""
        role_upper = (role or "DEPENDENT").upper()
        
        if role_upper in ("SPOUSE", "PARTNER"):
            return 0
        
        if not self.registry_loader:
            return self.FAMILY_PRICING["DEPENDENT"]
        
        registry = self.registry_loader()
        existing_paid = 0
        has_free_child = False
        
        for k, v in registry.items():
            if k.startswith("_"):
                continue
            p = v.get("profile", {})
            if p.get("family_id") != family_id:
                continue
            if p.get("family_role", "").upper() == "HEAD":
                continue
            member_role = p.get("family_role", "").upper()
            if member_role in ("SPOUSE", "PARTNER"):
                continue
            billing_price = p.get("family_billing_price_cents", -1)
            if billing_price == 0:
                has_free_child = True
            elif billing_price > 0:
                existing_paid += 1
        
        # First non-spouse member gets one free slot
        if not has_free_child and role_upper in ("CHILD", "DEPENDENT", "CHILD_UNDER_12"):
            return 0
        
        ordinal = existing_paid + 1
        if ordinal == 1:
            return self.FAMILY_PRICING["DEPENDENT"]
        elif ordinal == 2:
            return self.FAMILY_PRICING["DEPENDENT_2"]
        elif ordinal == 3:
            return self.FAMILY_PRICING["DEPENDENT_3"]
        else:
            return self.FAMILY_PRICING["DEPENDENT_4_PLUS"]
    
    async def add_family_member_billing(self, head_user_id: str, member_user_id: str,
                                         member_name: str, member_role: str,
                                         family_id: str) -> dict:
        """
        Create billing record for a new family member.
        Creates Stripe subscription item if Stripe is configured.
        Records the billing event locally regardless.
        """
        price_cents = self._get_family_member_price(member_role, family_id)
        price_display = f"${price_cents / 100:.0f}/mo" if price_cents > 0 else "Free"
        
        billing = self._load_billing()
        billing.setdefault("family_members", {})
        
        stripe_item_id = None
        
        if price_cents > 0 and self.stripe_enabled:
            head_sub = billing.get("subscriptions", {}).get(head_user_id, {})
            stripe_sub_id = head_sub.get("stripe_subscription_id")
            family_price_id = self.price_ids.get("FAMILY_MONTHLY")
            
            if stripe_sub_id and family_price_id and not stripe_sub_id.startswith("sub_local"):
                try:
                    si = stripe.SubscriptionItem.create(
                        subscription=stripe_sub_id,
                        price=family_price_id,
                        quantity=1,
                        metadata={
                            "type": "family_member",
                            "member_id": member_user_id,
                            "member_name": member_name,
                            "role": member_role,
                            "family_id": family_id,
                        }
                    )
                    stripe_item_id = si.id
                    print(f">>> [BILLING] Created Stripe subscription item {si.id} for family member {member_name}")
                except Exception as e:
                    print(f">>> [BILLING] Stripe family item creation failed (non-blocking): {e}")
        
        member_record = {
            "head_user_id": head_user_id,
            "member_user_id": member_user_id,
            "member_name": member_name,
            "role": member_role,
            "family_id": family_id,
            "price_cents": price_cents,
            "price_display": price_display,
            "stripe_subscription_item_id": stripe_item_id,
            "status": "active",
            "created_at": str(datetime.datetime.now()),
        }
        billing["family_members"][member_user_id] = member_record
        self._save_billing(billing)
        
        # Update the member's profile with billing info
        if self.registry_loader and self.registry_saver:
            registry = self.registry_loader()
            for k, v in registry.items():
                if v.get("profile", {}).get("hardware_id") == member_user_id:
                    v["profile"]["family_billing_price_cents"] = price_cents
                    v["profile"]["family_billing_status"] = "active"
                    v["profile"]["family_billing_stripe_item"] = stripe_item_id
                    self.registry_saver(registry)
                    break
        
        self._save_transaction({
            "type": "family_member_added",
            "head_user_id": head_user_id,
            "member_user_id": member_user_id,
            "member_name": member_name,
            "role": member_role,
            "family_id": family_id,
            "price_cents": price_cents,
            "stripe_item_id": stripe_item_id,
            "timestamp": str(datetime.datetime.now()),
        })
        
        print(f">>> [BILLING] Family member added: {member_name} ({member_role}) -> {price_display}")
        
        return {
            "success": True,
            "price_cents": price_cents,
            "price_display": price_display,
            "stripe_item_id": stripe_item_id,
        }
    
    async def remove_family_member_billing(self, member_user_id: str) -> dict:
        """Remove billing for a family member. Deletes Stripe subscription item if exists."""
        billing = self._load_billing()
        member_record = billing.get("family_members", {}).get(member_user_id)
        
        if not member_record:
            return {"success": True, "message": "No billing record found"}
        
        stripe_item_id = member_record.get("stripe_subscription_item_id")
        if stripe_item_id and self.stripe_enabled:
            try:
                stripe.SubscriptionItem.delete(stripe_item_id)
                print(f">>> [BILLING] Deleted Stripe subscription item {stripe_item_id}")
            except Exception as e:
                print(f">>> [BILLING] Stripe family item deletion failed: {e}")
        
        member_record["status"] = "removed"
        member_record["removed_at"] = str(datetime.datetime.now())
        billing["family_members"][member_user_id] = member_record
        self._save_billing(billing)
        
        # Clear billing info from profile
        if self.registry_loader and self.registry_saver:
            registry = self.registry_loader()
            for k, v in registry.items():
                if v.get("profile", {}).get("hardware_id") == member_user_id:
                    v["profile"].pop("family_billing_price_cents", None)
                    v["profile"].pop("family_billing_status", None)
                    v["profile"].pop("family_billing_stripe_item", None)
                    self.registry_saver(registry)
                    break
        
        self._save_transaction({
            "type": "family_member_removed",
            "member_user_id": member_user_id,
            "member_name": member_record.get("member_name", ""),
            "family_id": member_record.get("family_id", ""),
            "was_price_cents": member_record.get("price_cents", 0),
            "timestamp": str(datetime.datetime.now()),
        })
        
        print(f">>> [BILLING] Family member removed: {member_record.get('member_name', member_user_id)}")
        return {"success": True}
    
    def get_family_billing_summary(self, family_id: str) -> dict:
        """Get billing summary for a family."""
        if not self.registry_loader:
            return {"members": [], "total_monthly_cents": 0}
        
        registry = self.registry_loader()
        members = []
        total = 0
        head_plan = "TRIAL"
        
        for k, v in registry.items():
            if k.startswith("_"):
                continue
            p = v.get("profile", {})
            if p.get("family_id") != family_id:
                continue
            role = p.get("family_role", "MEMBER").upper()
            price = p.get("family_billing_price_cents", 0)
            if role == "HEAD":
                head_plan = p.get("subscription_plan", "TRIAL").upper()
                continue
            members.append({
                "user_id": p.get("hardware_id", ""),
                "name": p.get("name", ""),
                "role": role,
                "price_cents": price,
                "price_display": f"${price / 100:.0f}/mo" if price > 0 else "Free",
            })
            total += price
        
        base_price = self.PLANS.get(head_plan, {}).get("price_monthly", 0) * 100
        
        return {
            "head_plan": head_plan,
            "base_price_cents": base_price,
            "members": members,
            "member_count": len(members),
            "family_addon_cents": total,
            "total_monthly_cents": base_price + total,
            "total_display": f"${(base_price + total) / 100:.0f}/mo",
        }
    
    # =========================================================================
    # SUBSCRIPTION MANAGEMENT
    # =========================================================================
    
    def get_subscription(self, user_id: str) -> Optional[dict]:
        """Get user's subscription details."""
        billing = self._load_billing()
        return billing.get("subscriptions", {}).get(user_id)
    
    def get_usage_stats(self, user_id: str) -> dict:
        """Get token usage statistics for user."""
        if self.registry_loader:
            registry = self.registry_loader()
            for k, v in registry.items():
                if v.get("profile", {}).get("hardware_id") == user_id:
                    profile = v["profile"]
                    return {
                        "token_balance": profile.get("token_balance", 0),
                        "tokens_used_today": profile.get("token_usage_today", 0),
                        "tokens_used_month": profile.get("token_usage_month", 0),
                        "subscription_plan": profile.get("subscription_plan", "TRIAL"),
                        "subscription_status": profile.get("subscription_status", "TRIAL_ACTIVE"),
                        "trial_end_date": profile.get("trial_end_date", ""),
                        "coaching_credits": self._get_coaching_credits(user_id)
                    }
        
        return {
            "token_balance": 0,
            "tokens_used_today": 0,
            "tokens_used_month": 0,
            "subscription_plan": "NONE",
            "subscription_status": "INACTIVE",
            "coaching_credits": 0
        }
    
    def _get_coaching_credits(self, user_id: str) -> int:
        """Get remaining coaching session credits."""
        billing = self._load_billing()
        return billing.get("coaching_credits", {}).get(user_id, 0)
    
    def add_coaching_credits(self, user_id: str, credits: int):
        """Add coaching session credits to user."""
        billing = self._load_billing()
        billing.setdefault("coaching_credits", {})[user_id] = \
            billing.get("coaching_credits", {}).get(user_id, 0) + credits
        self._save_billing(billing)
        print(f">>> [BILLING] Added {credits} coaching credits to {user_id}")
    
    def use_coaching_credit(self, user_id: str) -> bool:
        """Use one coaching session credit. Returns True if successful."""
        billing = self._load_billing()
        credits = billing.get("coaching_credits", {}).get(user_id, 0)
        
        if credits <= 0:
            return False
        
        billing["coaching_credits"][user_id] = credits - 1
        self._save_billing(billing)
        return True
    
    def cancel_subscription(self, user_id: str, reason: str = "") -> bool:
        """Cancel user's subscription."""
        billing = self._load_billing()
        sub = billing.get("subscriptions", {}).get(user_id)
        
        if not sub:
            return False
        
        stripe_sub_id = sub.get("stripe_subscription_id")
        
        if self.stripe_enabled and stripe_sub_id and not stripe_sub_id.startswith("sub_local"):
            try:
                # Cancel at period end (user keeps access until end of billing period)
                stripe.Subscription.modify(
                    stripe_sub_id,
                    cancel_at_period_end=True
                )
                print(f">>> [BILLING] Subscription {stripe_sub_id} will cancel at period end")
            except stripe.error.StripeError as e:
                print(f">>> [BILLING] Stripe error cancelling: {e}")
                return False
        
        # Update local record
        sub["status"] = "cancelling"
        sub["cancel_reason"] = reason
        sub["cancelled_at"] = str(datetime.datetime.now())
        billing["subscriptions"][user_id] = sub
        self._save_billing(billing)
        
        # Update user profile
        if self.registry_loader and self.registry_saver:
            registry = self.registry_loader()
            for k, v in registry.items():
                if v.get("profile", {}).get("hardware_id") == user_id:
                    v["profile"]["subscription_status"] = "CANCELLING"
                    self.registry_saver(registry)
                    break
        
        # Log transaction
        self._save_transaction({
            "type": "subscription_cancelled",
            "user_id": user_id,
            "reason": reason,
            "timestamp": str(datetime.datetime.now())
        })
        
        return True
    
    # =========================================================================
    # WEBHOOK HANDLING
    # =========================================================================
    
    async def handle_webhook(self, payload: bytes, sig_header: str) -> Tuple[bool, str]:
        """Handle Stripe webhook events."""
        
        if not self.stripe_enabled:
            return False, "Stripe not enabled"
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
        except ValueError:
            return False, "Invalid payload"
        except stripe.error.SignatureVerificationError:
            return False, "Invalid signature"
        
        event_type = event["type"]
        data = event["data"]["object"]
        
        print(f">>> [BILLING] Webhook received: {event_type}")
        
        # Handle different event types
        handlers = {
            "checkout.session.completed": self._handle_checkout_completed,
            "customer.subscription.created": self._handle_subscription_created,
            "customer.subscription.updated": self._handle_subscription_updated,
            "customer.subscription.deleted": self._handle_subscription_deleted,
            "invoice.paid": self._handle_invoice_paid,
            "invoice.payment_failed": self._handle_payment_failed,
        }
        
        handler = handlers.get(event_type)
        if handler:
            await handler(data)
            return True, f"Handled {event_type}"
        
        return True, f"Ignored {event_type}"
    
    async def _handle_checkout_completed(self, session: dict):
        """Handle successful checkout."""
        user_id = session.get("metadata", {}).get("user_id")
        checkout_type = session.get("metadata", {}).get("type")
        
        if checkout_type == "coaching_sessions":
            # Add coaching credits
            sessions = int(session.get("metadata", {}).get("sessions", 0))
            if sessions > 0:
                self.add_coaching_credits(user_id, sessions)
        
        print(f">>> [BILLING] Checkout completed for {user_id}")
    
    async def _handle_subscription_created(self, subscription: dict):
        """Handle new subscription."""
        user_id = subscription.get("metadata", {}).get("user_id")
        plan = subscription.get("metadata", {}).get("plan", "STANDARD")
        
        if not user_id:
            # Try to find user by customer ID
            customer_id = subscription.get("customer")
            billing = self._load_billing()
            for uid, cust in billing.get("customers", {}).items():
                if cust.get("stripe_customer_id") == customer_id:
                    user_id = uid
                    break
        
        if not user_id:
            print(f">>> [BILLING] Could not find user for subscription")
            return
        
        # Get plan details
        plan_config = self.PLANS.get(plan, self.PLANS["STANDARD"])
        
        # Store subscription
        billing = self._load_billing()
        billing.setdefault("subscriptions", {})[user_id] = {
            "stripe_subscription_id": subscription["id"],
            "stripe_customer_id": subscription["customer"],
            "plan": plan,
            "status": subscription["status"],
            "current_period_start": subscription["current_period_start"],
            "current_period_end": subscription["current_period_end"],
            "created_at": str(datetime.datetime.now())
        }
        self._save_billing(billing)
        
        # Update user profile
        if self.registry_loader and self.registry_saver:
            registry = self.registry_loader()
            for k, v in registry.items():
                if v.get("profile", {}).get("hardware_id") == user_id:
                    v["profile"]["subscription_plan"] = plan
                    v["profile"]["subscription_status"] = "ACTIVE"
                    v["profile"]["token_balance"] = plan_config["tokens"]
                    
                    self.registry_saver(registry)
                    break
        
        print(f">>> [BILLING] Subscription created: {user_id} -> {plan}")
    
    async def _handle_subscription_updated(self, subscription: dict):
        """Handle subscription update (upgrade/downgrade)."""
        user_id = subscription.get("metadata", {}).get("user_id")
        
        if not user_id:
            customer_id = subscription.get("customer")
            billing = self._load_billing()
            for uid, cust in billing.get("customers", {}).items():
                if cust.get("stripe_customer_id") == customer_id:
                    user_id = uid
                    break
        
        if not user_id:
            return
        
        # Update local subscription record
        billing = self._load_billing()
        if user_id in billing.get("subscriptions", {}):
            billing["subscriptions"][user_id].update({
                "status": subscription["status"],
                "current_period_start": subscription["current_period_start"],
                "current_period_end": subscription["current_period_end"],
                "updated_at": str(datetime.datetime.now())
            })
            self._save_billing(billing)
        
        # Update user profile status
        if self.registry_loader and self.registry_saver:
            registry = self.registry_loader()
            for k, v in registry.items():
                if v.get("profile", {}).get("hardware_id") == user_id:
                    status_map = {
                        "active": "ACTIVE",
                        "past_due": "PAST_DUE",
                        "canceled": "CANCELLED",
                        "unpaid": "UNPAID"
                    }
                    v["profile"]["subscription_status"] = status_map.get(
                        subscription["status"], "ACTIVE"
                    )
                    self.registry_saver(registry)
                    break
        
        print(f">>> [BILLING] Subscription updated: {user_id}")
    
    async def _handle_subscription_deleted(self, subscription: dict):
        """Handle subscription cancellation/deletion."""
        user_id = subscription.get("metadata", {}).get("user_id")
        
        if not user_id:
            customer_id = subscription.get("customer")
            billing = self._load_billing()
            for uid, cust in billing.get("customers", {}).items():
                if cust.get("stripe_customer_id") == customer_id:
                    user_id = uid
                    break
        
        if not user_id:
            return
        
        # Update local subscription
        billing = self._load_billing()
        if user_id in billing.get("subscriptions", {}):
            billing["subscriptions"][user_id]["status"] = "cancelled"
            billing["subscriptions"][user_id]["ended_at"] = str(datetime.datetime.now())
            self._save_billing(billing)
        
        # Update user profile - revert to trial
        if self.registry_loader and self.registry_saver:
            registry = self.registry_loader()
            for k, v in registry.items():
                if v.get("profile", {}).get("hardware_id") == user_id:
                    v["profile"]["subscription_plan"] = "TRIAL"
                    v["profile"]["subscription_status"] = "CANCELLED"
                    v["profile"]["token_balance"] = 1000  # Minimal tokens
                    self.registry_saver(registry)
                    break
        
        print(f">>> [BILLING] Subscription deleted: {user_id}")
    
    async def _handle_invoice_paid(self, invoice: dict):
        """Handle successful payment - refresh tokens."""
        customer_id = invoice.get("customer")
        
        billing = self._load_billing()
        user_id = None
        for uid, cust in billing.get("customers", {}).items():
            if cust.get("stripe_customer_id") == customer_id:
                user_id = uid
                break
        
        if not user_id:
            return
        
        # Get subscription plan
        sub = billing.get("subscriptions", {}).get(user_id, {})
        plan = sub.get("plan", "STANDARD")
        plan_config = self.PLANS.get(plan, self.PLANS["STANDARD"])
        
        # Refresh tokens
        if self.registry_loader and self.registry_saver:
            registry = self.registry_loader()
            for k, v in registry.items():
                if v.get("profile", {}).get("hardware_id") == user_id:
                    v["profile"]["token_balance"] = plan_config["tokens"]
                    v["profile"]["token_usage_month"] = 0
                    v["profile"]["last_token_reset"] = str(datetime.datetime.now().date())
                    
                    self.registry_saver(registry)
                    break
        
        # Log transaction
        self._save_transaction({
            "type": "invoice_paid",
            "user_id": user_id,
            "amount": invoice.get("amount_paid", 0) / 100,  # Convert cents to dollars
            "invoice_id": invoice.get("id"),
            "timestamp": str(datetime.datetime.now())
        })
        
        print(f">>> [BILLING] Invoice paid for {user_id}, tokens refreshed")
    
    async def _handle_payment_failed(self, invoice: dict):
        """Handle failed payment."""
        customer_id = invoice.get("customer")
        
        billing = self._load_billing()
        user_id = None
        for uid, cust in billing.get("customers", {}).items():
            if cust.get("stripe_customer_id") == customer_id:
                user_id = uid
                break
        
        if not user_id:
            return
        
        # Update user status
        if self.registry_loader and self.registry_saver:
            registry = self.registry_loader()
            for k, v in registry.items():
                if v.get("profile", {}).get("hardware_id") == user_id:
                    v["profile"]["subscription_status"] = "PAST_DUE"
                    self.registry_saver(registry)
                    break
        
        # Log transaction
        self._save_transaction({
            "type": "payment_failed",
            "user_id": user_id,
            "amount": invoice.get("amount_due", 0) / 100,
            "invoice_id": invoice.get("id"),
            "timestamp": str(datetime.datetime.now())
        })
        
        print(f">>> [BILLING] Payment failed for {user_id}")
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    def get_plan_info(self, plan: str) -> dict:
        """Get plan configuration."""
        return self.PLANS.get(plan.upper(), self.PLANS["STANDARD"])
    
    def get_all_plans(self) -> dict:
        """Get all available plans."""
        return self.PLANS
    
    async def sync_subscription_status(self, user_id: str) -> bool:
        """Sync subscription status from Stripe."""
        if not self.stripe_enabled:
            return False
        
        billing = self._load_billing()
        sub = billing.get("subscriptions", {}).get(user_id)
        
        if not sub or not sub.get("stripe_subscription_id"):
            return False
        
        try:
            stripe_sub = stripe.Subscription.retrieve(sub["stripe_subscription_id"])
            
            # Update local record
            sub["status"] = stripe_sub.status
            sub["current_period_start"] = stripe_sub.current_period_start
            sub["current_period_end"] = stripe_sub.current_period_end
            sub["synced_at"] = str(datetime.datetime.now())
            billing["subscriptions"][user_id] = sub
            self._save_billing(billing)
            
            return True
            
        except stripe.error.StripeError as e:
            print(f">>> [BILLING] Stripe sync error: {e}")
            return False
