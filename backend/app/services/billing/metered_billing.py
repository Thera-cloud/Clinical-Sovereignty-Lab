"""
SOVEREIGN SWARM — Metered Billing Service
Tracks per-session and per-usage costs, reports to Stripe,
and enforces cost caps.

Operational Specifications §4 — Metered Billing.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.billing_metered import (
    BillingTier,
    CostThresholdConfig,
    MeteredBillingLayer,
    UsageRecord,
    UsageType,
)

logger = logging.getLogger("billing.metered")


class MeteredBillingService:
    """
    Manages metered billing: records usage, reports to Stripe,
    enforces cost caps, and generates billing summaries.
    """

    def __init__(self, stripe_service=None, notifications=None, db_pool=None):
        self._stripe = stripe_service
        self._notifications = notifications
        self._db = db_pool

    async def record_usage(
        self,
        user_id: str,
        usage_type: UsageType,
        quantity: float,
        session_id: Optional[str] = None,
    ) -> UsageRecord:
        """Record a metered usage event and check cost caps."""
        # Get billing state
        billing = await self._get_billing_state(user_id)
        cost_config = await self._get_cost_config(user_id)

        # Calculate cost based on tier
        unit_cost = self._get_unit_cost(billing.billing_tier, usage_type)
        total_cost = quantity * unit_cost

        # Check if within included allocation
        within_allocation = False
        if usage_type == UsageType.AI_SESSION_MINUTE:
            if billing.included_ai_minutes < 0 or billing.used_ai_minutes < billing.included_ai_minutes:
                within_allocation = True
                billing.used_ai_minutes += quantity
                total_cost = 0.0
        elif usage_type == UsageType.COACH_SESSION:
            if billing.used_coach_sessions < billing.included_coach_sessions:
                within_allocation = True
                billing.used_coach_sessions += 1
                total_cost = 0.0

        # Create record
        record = UsageRecord(
            user_id=user_id,
            usage_type=usage_type,
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            session_id=session_id,
        )

        # Update billing state
        if not within_allocation:
            billing.overage_charges += total_cost
        billing.total_current_period += total_cost
        billing.usage_records.append(record.record_id)

        # Check cost caps
        await self._check_cost_caps(user_id, billing, cost_config, total_cost)

        # Report to Stripe
        if not within_allocation and self._stripe:
            try:
                stripe_id = await self._stripe.report_usage(
                    subscription_id=billing.stripe_subscription_id,
                    quantity=quantity,
                    usage_type=usage_type.value,
                )
                record.stripe_usage_record_id = stripe_id
                record.reported_to_stripe = True
            except Exception as e:
                logger.warning("Stripe usage reporting failed: %s", e)

        # Persist
        await self._persist_usage(record)
        await self._persist_billing_state(billing)

        return record

    async def get_billing_summary(self, user_id: str) -> Dict[str, Any]:
        """Get a billing summary for the current period."""
        billing = await self._get_billing_state(user_id)
        return {
            "user_id": user_id,
            "tier": billing.billing_tier.value,
            "period_start": billing.billing_period_start.isoformat() if billing.billing_period_start else None,
            "period_end": billing.billing_period_end.isoformat() if billing.billing_period_end else None,
            "ai_minutes": {
                "included": billing.included_ai_minutes,
                "used": billing.used_ai_minutes,
                "remaining": max(0, billing.included_ai_minutes - billing.used_ai_minutes) if billing.included_ai_minutes >= 0 else "unlimited",
            },
            "coach_sessions": {
                "included": billing.included_coach_sessions,
                "used": billing.used_coach_sessions,
                "remaining": max(0, billing.included_coach_sessions - billing.used_coach_sessions),
            },
            "overage_charges": billing.overage_charges,
            "total_current_period": billing.total_current_period,
            "cost_cap_hit": billing.session_cost_cap_hit,
        }

    def _get_unit_cost(self, tier: BillingTier, usage_type: UsageType) -> float:
        """Get the unit cost for a usage type based on tier."""
        costs = {
            (BillingTier.INNER_CHAMBER, UsageType.AI_SESSION_MINUTE): 0.15,
            (BillingTier.SOVEREIGN_CIRCLE, UsageType.AI_SESSION_MINUTE): 0.10,
            (BillingTier.INNER_CHAMBER, UsageType.VOICE_ANALYSIS_MINUTE): 0.10,
            (BillingTier.SOVEREIGN_CIRCLE, UsageType.VOICE_ANALYSIS_MINUTE): 0.08,
            (BillingTier.SOVEREIGN_CIRCLE, UsageType.ME2ME_AVATAR_HOUR): 2.00,
            (BillingTier.SOVEREIGN_CIRCLE, UsageType.ME2ME_GROWTH_QUERY): 0.50,
            (BillingTier.INNER_CHAMBER, UsageType.LEGACY_VAULT_STORAGE_GB): 0.50,
            (BillingTier.SOVEREIGN_CIRCLE, UsageType.LEGACY_VAULT_STORAGE_GB): 0.50,
            # Overage billing: reports and archivist
            (BillingTier.INNER_CHAMBER, UsageType.NEVEDAL_REPORT): 5.00,
            (BillingTier.SOVEREIGN_CIRCLE, UsageType.NEVEDAL_REPORT): 5.00,
            (BillingTier.INNER_CHAMBER, UsageType.FORESIGHT_REPORT): 3.00,
            # FORESIGHT_REPORT: SC has unlimited, no overage cost
            (BillingTier.SOVEREIGN_CIRCLE, UsageType.ARCHIVIST_CHAPTER): 1.50,
            # ARCHIVIST_CHAPTER: IC only gets via SC; SC charged beyond 10/mo included
        }
        return costs.get((tier, usage_type), 0.0)

    async def _check_cost_caps(
        self,
        user_id: str,
        billing: MeteredBillingLayer,
        config: CostThresholdConfig,
        current_charge: float,
    ) -> None:
        """Check and enforce cost caps."""
        # Per-session cap
        if current_charge > config.per_session_cap:
            billing.session_cost_cap_hit = True
            if config.hard_stop_enabled:
                logger.warning("Session cost cap hit: user=%s charge=%.2f", user_id, current_charge)

        # Monthly cap warning
        if billing.total_current_period > config.monthly_cap * config.warning_threshold_pct:
            if self._notifications and config.notification_on_warning:
                await self._notifications.send_notification(
                    user_id=user_id,
                    notification_type="billing_warning",
                    title="Billing Alert",
                    body=f"You've used {billing.total_current_period:.2f} of your {config.monthly_cap:.2f} monthly cap.",
                    channel="push",
                )

        # Monthly cap hard stop
        if billing.total_current_period > config.monthly_cap:
            if config.hard_stop_enabled and not config.overage_allowed:
                billing.session_cost_cap_hit = True

    async def _get_billing_state(self, user_id: str) -> MeteredBillingLayer:
        """Get or create billing state for a user."""
        if self._db:
            try:
                async with self._db.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT * FROM metered_billing_state WHERE user_id = $1",
                        user_id,
                    )
                    if row:
                        return MeteredBillingLayer(
                            user_id=user_id,
                            billing_tier=BillingTier.from_subscription_tier(row.get("billing_tier", "threshold")),
                            included_ai_minutes=row.get("included_ai_minutes", 0),
                            used_ai_minutes=row.get("used_ai_minutes", 0),
                            included_coach_sessions=row.get("included_coach_sessions", 0),
                            used_coach_sessions=row.get("used_coach_sessions", 0),
                            overage_charges=row.get("overage_charges", 0),
                            stripe_customer_id=row.get("stripe_customer_id"),
                            stripe_subscription_id=row.get("stripe_subscription_id"),
                        )
            except Exception as e:
                logger.warning("Billing state query failed: %s", e)
        return MeteredBillingLayer(user_id=user_id)

    async def _get_cost_config(self, user_id: str) -> CostThresholdConfig:
        """Get cost threshold config for a user."""
        if self._db:
            try:
                async with self._db.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT * FROM cost_threshold_configs WHERE user_id = $1",
                        user_id,
                    )
                    if row:
                        return CostThresholdConfig(
                            user_id=user_id,
                            per_session_cap=row.get("per_session_cap", 500),
                            monthly_cap=row.get("monthly_cap", 2000),
                            warning_threshold_pct=row.get("warning_threshold_pct", 0.8),
                            hard_stop_enabled=row.get("hard_stop_enabled", True),
                            overage_allowed=row.get("overage_allowed", False),
                        )
            except Exception:
                pass
        return CostThresholdConfig(user_id=user_id)

    async def _persist_usage(self, record: UsageRecord) -> None:
        if not self._db:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """INSERT INTO usage_records (record_id, user_id, usage_type, quantity, unit_cost, total_cost, session_id, stripe_usage_record_id, reported_to_stripe)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                    record.record_id, record.user_id, record.usage_type.value,
                    record.quantity, record.unit_cost, record.total_cost,
                    record.session_id, record.stripe_usage_record_id, record.reported_to_stripe,
                )
        except Exception as e:
            logger.error("Usage record persistence failed: %s", e)

    async def _persist_billing_state(self, billing: MeteredBillingLayer) -> None:
        if not self._db:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """INSERT INTO metered_billing_state (user_id, billing_tier, used_ai_minutes, used_coach_sessions, overage_charges, session_cost_cap_hit)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (user_id) DO UPDATE SET
                        used_ai_minutes = EXCLUDED.used_ai_minutes,
                        used_coach_sessions = EXCLUDED.used_coach_sessions,
                        overage_charges = EXCLUDED.overage_charges,
                        session_cost_cap_hit = EXCLUDED.session_cost_cap_hit""",
                    billing.user_id, billing.billing_tier.value,
                    billing.used_ai_minutes, billing.used_coach_sessions,
                    billing.overage_charges, billing.session_cost_cap_hit,
                )
        except Exception as e:
            logger.error("Billing state persistence failed: %s", e)
