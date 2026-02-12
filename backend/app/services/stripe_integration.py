"""
LITTLE NATE — Stripe E-Commerce Integration
Version: 1.0
Date: January 21, 2026

Complete Stripe integration for:
- Subscription management (tiers)
- Family member billing
- Coaching session packs
- Webhook handling

Required env vars:
- STRIPE_SECRET_KEY
- STRIPE_WEBHOOK_SECRET
- STRIPE_PRICE_STANDARD
- STRIPE_PRICE_TOP_TIER
- STRIPE_PRICE_FAMILY_MEMBER
- STRIPE_PRICE_COACHING_SINGLE
- STRIPE_PRICE_COACHING_4PACK
- STRIPE_PRICE_COACHING_8PACK
"""

import os
import stripe
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum
from fastapi import APIRouter, HTTPException, Request, Header
from pydantic import BaseModel
import asyncpg
import json

# =============================================================================
# CONFIGURATION
# =============================================================================

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Stripe Price IDs (set these in your Stripe dashboard)
PRICES = {
    "STANDARD": os.getenv("STRIPE_PRICE_STANDARD"),        # $49/mo
    "TOP_TIER": os.getenv("STRIPE_PRICE_TOP_TIER"),        # $149/mo
    "FAMILY_MEMBER": os.getenv("STRIPE_PRICE_FAMILY_MEMBER"),  # $75/mo
    "COACHING_SINGLE": os.getenv("STRIPE_PRICE_COACHING_SINGLE"),  # $175
    "COACHING_4PACK": os.getenv("STRIPE_PRICE_COACHING_4PACK"),    # $600
    "COACHING_8PACK": os.getenv("STRIPE_PRICE_COACHING_8PACK"),    # $1,120
}

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
    DEPENDENT = "DEPENDENT"
    ADDITIONAL = "ADDITIONAL"

class PackType(str, Enum):
    SINGLE = "SINGLE"
    PACK_4 = "PACK_4"
    PACK_8 = "PACK_8"

@dataclass
class PackConfig:
    sessions: int
    price_cents: int
    validity_days: int

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

class CreateCheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str

class AddFamilyMemberRequest(BaseModel):
    email: str
    name: str
    relationship: FamilyRole  # SPOUSE, DEPENDENT, or ADDITIONAL

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
    
    # -------------------------------------------------------------------------
    # CUSTOMER MANAGEMENT
    # -------------------------------------------------------------------------
    
    async def get_or_create_customer(self, user_id: str, email: str, name: str) -> str:
        """Get existing Stripe customer or create new one."""
        # Check if user already has a customer ID
        row = await self.db.fetchrow(
            "SELECT stripe_customer_id FROM users WHERE id = $1",
            user_id
        )
        
        if row and row['stripe_customer_id']:
            return row['stripe_customer_id']
        
        # Create new customer
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
        cancel_url: str
    ) -> CreateCheckoutResponse:
        """Create Stripe checkout session for subscription."""
        
        if tier == SubscriptionTier.TRIAL:
            raise HTTPException(400, "Cannot checkout for trial tier")
        
        customer_id = await self.get_or_create_customer(user_id, email, name)
        price_id = PRICES[tier.value]
        
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
        
        # Create new subscription checkout
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
            metadata={"user_id": user_id, "tier": tier.value},
            subscription_data={
                "metadata": {"user_id": user_id, "tier": tier.value}
            },
            # 7-day trial for new subscriptions
            subscription_data_trial_period_days=7 if tier == SubscriptionTier.STANDARD else None
        )
        
        return CreateCheckoutResponse(
            checkout_url=session.url,
            session_id=session.id
        )
    
    # -------------------------------------------------------------------------
    # FAMILY MANAGEMENT
    # -------------------------------------------------------------------------
    
    async def add_family_member(
        self,
        primary_user_id: str,
        member_email: str,
        member_name: str,
        relationship: FamilyRole
    ) -> Dict[str, Any]:
        """Add a family member to subscription."""
        
        # Verify primary user has TOP_TIER
        sub = await self.db.fetchrow(
            "SELECT id, tier, stripe_subscription_id FROM subscriptions WHERE user_id = $1 AND status = 'ACTIVE'",
            primary_user_id
        )
        
        if not sub or sub['tier'] != 'TOP_TIER':
            raise HTTPException(403, "Family linking requires Sovereign Circle membership")
        
        # Count existing family members
        family_count = await self.db.fetchval(
            "SELECT COUNT(*) FROM subscription_items WHERE subscription_id = $1",
            sub['id']
        )
        
        # Determine pricing
        if relationship == FamilyRole.SPOUSE:
            if family_count > 0:
                # Check if spouse already exists
                existing_spouse = await self.db.fetchval(
                    "SELECT COUNT(*) FROM subscription_items WHERE subscription_id = $1 AND family_role = 'SPOUSE'",
                    sub['id']
                )
                if existing_spouse > 0:
                    raise HTTPException(400, "Spouse already linked")
            price_cents = 0
        elif relationship == FamilyRole.DEPENDENT:
            # First dependent is free
            existing_dependents = await self.db.fetchval(
                "SELECT COUNT(*) FROM subscription_items WHERE subscription_id = $1 AND family_role = 'DEPENDENT'",
                sub['id']
            )
            price_cents = 0 if existing_dependents == 0 else 7500
            if existing_dependents > 0:
                relationship = FamilyRole.ADDITIONAL
        else:
            price_cents = 7500  # $75/mo for additional members
        
        # Create or get member user
        member_user = await self.db.fetchrow(
            "SELECT id FROM users WHERE LOWER(username) = LOWER($1) OR LOWER(email) = LOWER($1)",
            member_email
        )
        
        if not member_user:
            # Create invited user (pending)
            member_id = await self.db.fetchval(
                """
                INSERT INTO users (username, email, name, role, tier, family_role, linked_by, linked_at, subscription_status)
                VALUES ($1, $1, $2, 'CLIENT', 'STANDARD', $3, $4, NOW(), 'PENDING_INVITE')
                RETURNING id
                """,
                member_email, member_name, relationship.value, primary_user_id
            )
        else:
            member_id = member_user['id']
            # Update their family status
            await self.db.execute(
                "UPDATE users SET family_role = $1, linked_by = $2, linked_at = NOW(), tier = 'STANDARD' WHERE id = $3",
                relationship.value, primary_user_id, member_id
            )
        
        # Add to Stripe subscription if there's a charge
        stripe_item_id = None
        if price_cents > 0 and sub['stripe_subscription_id']:
            item = stripe.SubscriptionItem.create(
                subscription=sub['stripe_subscription_id'],
                price=PRICES['FAMILY_MEMBER'],
                quantity=1,
                metadata={"user_id": str(member_id), "relationship": relationship.value}
            )
            stripe_item_id = item.id
        
        # Record in database
        await self.db.execute(
            """
            INSERT INTO subscription_items (subscription_id, user_id, stripe_subscription_item_id, family_role, price_cents)
            VALUES ($1, $2, $3, $4, $5)
            """,
            sub['id'], member_id, stripe_item_id, relationship.value, price_cents
        )
        
        # TODO: Send invitation email
        
        return {
            "member_id": str(member_id),
            "email": member_email,
            "relationship": relationship.value,
            "monthly_cost": price_cents / 100,
            "status": "INVITED" if not member_user else "LINKED"
        }
    
    async def remove_family_member(self, primary_user_id: str, member_id: str) -> bool:
        """Remove a family member from subscription."""
        
        # Get subscription item
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
            stripe.SubscriptionItem.delete(item['stripe_subscription_item_id'])
        
        # Remove from database
        await self.db.execute("DELETE FROM subscription_items WHERE id = $1", item['id'])
        
        # Update user status
        await self.db.execute(
            "UPDATE users SET family_role = NULL, linked_by = NULL, tier = 'TRIAL' WHERE id = $1",
            member_id
        )
        
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
            if pack['expires_at'] < datetime.now():
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
        
        # TODO: Send confirmation emails to client and coach
        # TODO: Schedule Nate briefing generation
        
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
        """Cancel subscription."""
        
        sub = await self.db.fetchrow(
            "SELECT stripe_subscription_id FROM subscriptions WHERE user_id = $1 AND status = 'ACTIVE'",
            user_id
        )
        
        if not sub or not sub['stripe_subscription_id']:
            raise HTTPException(404, "No active subscription")
        
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
    
    async def handle_webhook(self, payload: bytes, sig_header: str) -> Dict[str, str]:
        """Process Stripe webhook event."""
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, WEBHOOK_SECRET
            )
        except ValueError:
            raise HTTPException(400, "Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise HTTPException(400, "Invalid signature")
        
        event_type = event['type']
        data = event['data']['object']
        
        handlers = {
            'checkout.session.completed': self._handle_checkout_completed,
            'invoice.paid': self._handle_invoice_paid,
            'invoice.payment_failed': self._handle_payment_failed,
            'customer.subscription.updated': self._handle_subscription_updated,
            'customer.subscription.deleted': self._handle_subscription_deleted,
        }
        
        handler = handlers.get(event_type)
        if handler:
            await handler(data)
        
        return {"status": "processed", "event_type": event_type}
    
    async def _handle_checkout_completed(self, session: Dict):
        """Handle successful checkout."""
        
        metadata = session.get('metadata', {})
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
        
        elif session['mode'] == 'payment':
            # One-time payment (coaching pack)
            pack_type = metadata.get('pack_type')
            if pack_type:
                config = PACK_CONFIGS[PackType(pack_type)]
                expires_at = datetime.now() + timedelta(days=config.validity_days)
                
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
                INSERT INTO payment_history (user_id, stripe_invoice_id, amount_cents, status)
                VALUES ($1, $2, $3, 'SUCCEEDED')
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
                INSERT INTO payment_history (user_id, stripe_invoice_id, amount_cents, status)
                VALUES ($1, $2, $3, 'FAILED')
                """,
                user_id, invoice['id'], invoice['amount_due']
            )
            
            # Update subscription status
            await self.db.execute(
                "UPDATE subscriptions SET status = 'PAST_DUE' WHERE user_id = $1",
                user_id
            )
            
            # TODO: Send payment failed email
            # TODO: Add to crisis/attention watchlist if repeated
    
    async def _handle_subscription_updated(self, subscription: Dict):
        """Handle subscription changes."""
        
        subscription_id = subscription['id']
        
        # Get tier from metadata or price
        tier = subscription.get('metadata', {}).get('tier', 'STANDARD')
        
        await self.db.execute(
            """
            UPDATE subscriptions SET
                tier = $1,
                status = $2,
                current_period_end = to_timestamp($3),
                cancel_at_period_end = $4
            WHERE stripe_subscription_id = $5
            """,
            tier,
            'ACTIVE' if subscription['status'] == 'active' else subscription['status'].upper(),
            subscription['current_period_end'],
            subscription['cancel_at_period_end'],
            subscription_id
        )
    
    async def _handle_subscription_deleted(self, subscription: Dict):
        """Handle subscription cancellation."""
        
        subscription_id = subscription['id']
        
        # Get user
        user_id = await self.db.fetchval(
            "SELECT user_id FROM subscriptions WHERE stripe_subscription_id = $1",
            subscription_id
        )
        
        if user_id:
            await self.db.execute(
                """
                UPDATE subscriptions SET status = 'CANCELLED', cancelled_at = NOW()
                WHERE stripe_subscription_id = $1
                """,
                subscription_id
            )
            
            # Downgrade user
            await self.db.execute(
                "UPDATE users SET tier = 'TRIAL', subscription_status = 'CANCELLED' WHERE id = $1",
                user_id
            )
            
            # Remove family access
            await self.db.execute(
                """
                UPDATE users SET tier = 'TRIAL', family_role = NULL 
                WHERE linked_by = $1
                """,
                user_id
            )


# =============================================================================
# API ROUTER
# =============================================================================

def create_billing_router(db_pool: asyncpg.Pool) -> APIRouter:
    """Create FastAPI router for billing endpoints."""
    
    router = APIRouter(prefix="/api/billing", tags=["billing"])
    service = StripeService(db_pool)
    webhook_handler = StripeWebhookHandler(db_pool)
    
    @router.post("/checkout", response_model=CreateCheckoutResponse)
    async def create_checkout(request: CreateCheckoutRequest, user_id: str):
        # user_id would come from JWT auth middleware
        user = await db_pool.fetchrow("SELECT email, name FROM users WHERE id = $1", user_id)
        return await service.create_subscription_checkout(
            user_id, user['email'], user['name'],
            request.tier, request.success_url, request.cancel_url
        )
    
    @router.get("/subscription", response_model=SubscriptionResponse)
    async def get_subscription(user_id: str):
        return await service.get_subscription_status(user_id)
    
    @router.post("/subscription/cancel")
    async def cancel_subscription(user_id: str, at_period_end: bool = True):
        return await service.cancel_subscription(user_id, at_period_end)
    
    @router.post("/family/add")
    async def add_family_member(request: AddFamilyMemberRequest, user_id: str):
        return await service.add_family_member(
            user_id, request.email, request.name, request.relationship
        )
    
    @router.delete("/family/{member_id}")
    async def remove_family_member(member_id: str, user_id: str):
        return await service.remove_family_member(user_id, member_id)
    
    @router.post("/coaching/purchase", response_model=CreateCheckoutResponse)
    async def purchase_coaching_pack(request: PurchaseCoachingPackRequest, user_id: str):
        user = await db_pool.fetchrow("SELECT email, name FROM users WHERE id = $1", user_id)
        return await service.purchase_coaching_pack(
            user_id, user['email'], user['name'],
            request.pack_type, request.success_url, request.cancel_url
        )
    
    @router.post("/coaching/book")
    async def book_coaching_session(request: BookCoachingSessionRequest, user_id: str):
        return await service.book_coaching_session(
            user_id, request.coach_id, request.scheduled_at, request.use_pack_id
        )
    
    @router.post("/webhook")
    async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
        payload = await request.body()
        return await webhook_handler.handle_webhook(payload, stripe_signature)
    
    return router
