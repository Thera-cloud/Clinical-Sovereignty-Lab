"""
HIVE DEFENSE v4.3 — Sovereign Stripe Proxy
Minimizes PII sent to Stripe by using hashed customer identifiers
and stripping unnecessary personal data.

- Customer IDs are hashed before Stripe API calls
- Only minimal required fields are sent
- All Stripe API calls go through this proxy
- Audit trail for all financial operations
"""

import hashlib
import logging
import os
from typing import Any, Dict, Optional

import stripe

_logger = logging.getLogger("sovereign_stripe_proxy")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


class SovereignStripeProxy:
    """Proxy layer between Sovereign Sanctuary and Stripe API.

    All Stripe calls should go through this proxy. The fallback_count
    tracks cases where proxy methods fail and callers might bypass to
    direct Stripe API calls.
    """

    def __init__(self, db_pool=None):
        self._db = db_pool
        self.fallback_count: int = 0
        self._total_calls: int = 0

    def _record_fallback(self, action: str, error: str) -> None:
        """Record a proxy failure that may cause callers to fall back to direct Stripe."""
        self.fallback_count += 1
        _logger.warning(
            "STRIPE PROXY FALLBACK: action=%s error=%s (fallback_count=%d/%d)",
            action, error[:80], self.fallback_count, self._total_calls,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get proxy health statistics for /v4/overview."""
        return {
            "total_calls": self._total_calls,
            "fallback_count": self.fallback_count,
            "fallback_rate": (self.fallback_count / max(self._total_calls, 1)) * 100,
        }

    @staticmethod
    def hash_customer_id(user_id: str) -> str:
        """Create a one-way hash for Stripe customer metadata."""
        salt = os.getenv("STRIPE_ID_SALT", "sovereign_sanctuary_salt")
        return hashlib.sha256(f"{salt}:{user_id}".encode()).hexdigest()[:32]

    async def create_customer(
        self, user_id: str, email: str, name: str = "",
    ) -> Dict[str, Any]:
        """
        Create a Stripe customer with minimal PII.
        Only sends email (required by Stripe) and a hashed reference.
        """
        self._total_calls += 1
        try:
            customer = stripe.Customer.create(
                email=email,
                metadata={
                    "sovereign_id": self.hash_customer_id(user_id),
                    "platform": "sovereign_sanctuary",
                },
            )

            await self._audit_log("create_customer", user_id, customer.id)
            return {"customer_id": customer.id, "success": True}

        except stripe.error.StripeError as exc:
            self._record_fallback("create_customer", str(exc))
            return {"success": False, "error": str(exc)}

    async def create_subscription(
        self, customer_id: str, price_id: str, user_id: str,
        trial_days: int = 0,
    ) -> Dict[str, Any]:
        """Create a subscription with minimal data exposure."""
        self._total_calls += 1
        try:
            params = {
                "customer": customer_id,
                "items": [{"price": price_id}],
                "metadata": {
                    "sovereign_id": self.hash_customer_id(user_id),
                },
            }
            if trial_days > 0:
                params["trial_period_days"] = trial_days

            subscription = stripe.Subscription.create(**params)

            await self._audit_log("create_subscription", user_id, subscription.id)
            return {"subscription_id": subscription.id, "status": subscription.status, "success": True}

        except stripe.error.StripeError as exc:
            self._record_fallback("create_subscription", str(exc))
            return {"success": False, "error": str(exc)}

    async def cancel_subscription(
        self, subscription_id: str, user_id: str, at_period_end: bool = True,
    ) -> Dict[str, Any]:
        """Cancel a subscription."""
        self._total_calls += 1
        try:
            if at_period_end:
                subscription = stripe.Subscription.modify(
                    subscription_id,
                    cancel_at_period_end=True,
                )
            else:
                subscription = stripe.Subscription.delete(subscription_id)

            await self._audit_log("cancel_subscription", user_id, subscription_id)
            return {"subscription_id": subscription_id, "status": "cancelling", "success": True}

        except stripe.error.StripeError as exc:
            self._record_fallback("cancel_subscription", str(exc))
            return {"success": False, "error": str(exc)}

    async def _audit_log(self, action: str, user_id: str, stripe_id: str) -> None:
        """Log all Stripe operations for audit."""
        _logger.info(
            "STRIPE AUDIT: action=%s, user=%s, stripe_id=%s",
            action, user_id[:8], stripe_id[:12],
        )
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT INTO webhook_events_v2
                   (event_id, provider, event_type, processing_result, created_at)
                   VALUES ($1, 'sovereign_stripe_proxy', $2, 'audit', NOW())
                   ON CONFLICT (event_id) DO NOTHING""",
                f"proxy_{action}_{hashlib.sha256(f'{user_id}:{stripe_id}'.encode()).hexdigest()[:16]}",
                f"proxy_{action}",
            )
        except Exception as exc:
            _logger.error("Stripe audit log error: %s", exc)
