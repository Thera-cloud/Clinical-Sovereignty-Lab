"""
HIVE DEFENSE v4.0 — Webhook Fortress
Three-cord verification for all incoming Stripe webhooks.

Cord 1: Cryptographic signature verification (stripe.Webhook.construct_event)
Cord 2: Independent cross-verification (stripe.Event.retrieve)
Cord 3: Business logic validation (customer exists, price valid, amount matches, temporal sanity)
"""

import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import stripe

_logger = logging.getLogger("webhook_fortress")

# ─── Valid Price IDs (server-side enforcement) ────────────────────────────────

VALID_PRICE_IDS: Dict[str, Dict[str, Any]] = {
    os.getenv("STRIPE_PRICE_STANDARD", "price_inner_chamber_monthly"): {
        "tier": "inner_chamber", "amount_cents": 4900, "name": "Inner Chamber Monthly",
    },
    os.getenv("STRIPE_PRICE_TOP_TIER", "price_sovereign_circle_monthly"): {
        "tier": "sovereign_circle", "amount_cents": 14900, "name": "Sovereign Circle Monthly",
    },
    os.getenv("STRIPE_PRICE_FAMILY_TIER_1", "price_family_addon"): {
        "tier": "family_addon", "amount_cents": 7500, "name": "Family Add-on 1st",
    },
    os.getenv("STRIPE_PRICE_FAMILY_TIER_2", "price_family_addon_2nd"): {
        "tier": "family_addon", "amount_cents": 6000, "name": "Family Add-on 2nd",
    },
    os.getenv("STRIPE_PRICE_FAMILY_TIER_3", "price_family_addon_3rd"): {
        "tier": "family_addon", "amount_cents": 4500, "name": "Family Add-on 3rd",
    },
    os.getenv("STRIPE_PRICE_FAMILY_TIER_4", "price_family_addon_4th"): {
        "tier": "family_addon", "amount_cents": 3000, "name": "Family Add-on 4th",
    },
    os.getenv("STRIPE_PRICE_COACHING_SINGLE", "price_session_single"): {
        "tier": "session_pack", "amount_cents": 17500, "name": "Single Session",
    },
    os.getenv("STRIPE_PRICE_COACHING_4PACK", "price_session_4pack"): {
        "tier": "session_pack", "amount_cents": 60000, "name": "4-Pack Sessions",
    },
    os.getenv("STRIPE_PRICE_COACHING_8PACK", "price_session_8pack"): {
        "tier": "session_pack", "amount_cents": 112000, "name": "8-Pack Sessions",
    },
}

# Founding member discount prices
_founding_standard = os.getenv("STRIPE_PRICE_STANDARD_FOUNDING")
if _founding_standard:
    VALID_PRICE_IDS[_founding_standard] = {
        "tier": "inner_chamber", "amount_cents": 3900, "name": "Inner Chamber Founding",
    }
_founding_top = os.getenv("STRIPE_PRICE_TOP_TIER_FOUNDING")
if _founding_top:
    VALID_PRICE_IDS[_founding_top] = {
        "tier": "sovereign_circle", "amount_cents": 11900, "name": "Sovereign Circle Founding",
    }

# Maximum event age (5 minutes) before replay rejection
MAX_EVENT_AGE_SECONDS = 300


class WebhookFortress:
    """Three-cord webhook verification engine with secret rotation support."""

    # During a rotation window, both old and new secrets are accepted.
    ROTATION_WINDOW_HOURS = 24

    def __init__(self, db_pool=None):
        self._db = db_pool
        self._webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
        # Secondary secret for dual-verification during rotation window
        self._previous_secret: Optional[str] = None
        self._rotation_deadline: Optional[float] = None  # Unix timestamp

    async def is_ready(self) -> bool:
        """Check if WebhookFortress is operational (secret configured, DB alive)."""
        if not self._webhook_secret:
            return False
        try:
            if self._db:
                async with self._db.acquire() as conn:
                    await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    async def verify_all_three_cords(
        self, payload: bytes, sig_header: str
    ) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Run all three verification cords on an incoming webhook.
        Returns (passed: bool, event: dict | None, reason: str).
        """
        # ── Cord 1: Cryptographic Signature ──
        event, reason = self._cord1_signature(payload, sig_header)
        if event is None:
            await self._log_webhook_event(None, "unknown", False, False, False, reason)
            return False, None, f"Cord 1 FAIL: {reason}"

        event_id = event.get("id", "unknown")
        event_type = event.get("type", "unknown")

        # ── Idempotency check ──
        if await self._already_processed(event_id):
            return False, None, f"Duplicate event {event_id}"

        # ── Cord 2: Cross-Verification ──
        cord2_ok, cord2_reason = await self._cord2_cross_verify(event_id)
        if not cord2_ok:
            await self._log_webhook_event(event_id, event_type, True, False, False, cord2_reason)
            return False, None, f"Cord 2 FAIL: {cord2_reason}"

        # ── Cord 3: Business Logic ──
        cord3_ok, cord3_reason = await self._cord3_business_logic(event)
        if not cord3_ok:
            await self._log_webhook_event(event_id, event_type, True, True, False, cord3_reason)
            return False, None, f"Cord 3 FAIL: {cord3_reason}"

        # All three cords passed
        await self._log_webhook_event(event_id, event_type, True, True, True, "all_cords_passed")
        return True, event, "verified"

    # ─── Cord 1: Signature ────────────────────────────────────────────────────

    def _cord1_signature(
        self, payload: bytes, sig_header: str
    ) -> Tuple[Optional[Dict], str]:
        """Verify Stripe webhook signature with dual-secret support during rotation."""
        if not self._webhook_secret:
            _logger.error("STRIPE_WEBHOOK_SECRET not configured")
            return None, "webhook_secret_missing"

        # Try primary secret first
        secrets_to_try = [self._webhook_secret]

        # During rotation window, also accept the previous secret
        if self._previous_secret and self._rotation_deadline:
            if time.time() < self._rotation_deadline:
                secrets_to_try.append(self._previous_secret)
            else:
                # Rotation window expired — discard old secret
                _logger.info("Rotation window expired, discarding previous webhook secret")
                self._previous_secret = None
                self._rotation_deadline = None

        last_error = "invalid_signature"
        for secret in secrets_to_try:
            try:
                event = stripe.Webhook.construct_event(payload, sig_header, secret)
                # Replay protection: reject events older than 5 minutes
                created = event.get("created", 0)
                if time.time() - created > MAX_EVENT_AGE_SECONDS:
                    _logger.warning("Webhook event too old: age=%ds", time.time() - created)
                    return None, "event_too_old"
                return event, "signature_valid"
            except stripe.error.SignatureVerificationError:
                last_error = "invalid_signature"
                continue
            except Exception as exc:
                _logger.error("Cord 1 unexpected error: %s", type(exc).__name__)
                last_error = "signature_error"
                continue

        _logger.warning("Webhook signature verification failed (tried %d secrets)", len(secrets_to_try))
        return None, last_error

    # ─── Cord 2: Cross-Verify ─────────────────────────────────────────────────

    async def _cord2_cross_verify(self, event_id: str) -> Tuple[bool, str]:
        """Independently retrieve the event from Stripe API to confirm it exists."""
        try:
            retrieved = stripe.Event.retrieve(event_id)
            if not retrieved or retrieved.get("id") != event_id:
                _logger.warning("Cord 2: event %s not found on Stripe", event_id[:8])
                return False, "event_not_found_on_stripe"
            return True, "cross_verified"
        except stripe.error.InvalidRequestError:
            _logger.warning("Cord 2: Stripe says event %s is invalid", event_id[:8])
            return False, "event_invalid_on_stripe"
        except Exception as exc:
            _logger.error("Cord 2 error: %s", type(exc).__name__)
            return False, f"cross_verify_error_{type(exc).__name__}"

    # ─── Cord 3: Business Logic ───────────────────────────────────────────────

    async def _cord3_business_logic(self, event: Dict) -> Tuple[bool, str]:
        """Validate that the event makes business sense."""
        event_type = event.get("type", "")
        data_obj = event.get("data", {}).get("object", {})

        # Subscription events: validate price IDs
        if "subscription" in event_type or "invoice" in event_type:
            return self._validate_subscription_event(data_obj)

        # Checkout session events: validate amounts
        if "checkout.session" in event_type:
            return self._validate_checkout_event(data_obj)

        # Payment intent events: validate customer exists
        if "payment_intent" in event_type:
            return self._validate_payment_intent(data_obj)

        # Other event types pass by default (informational)
        return True, "event_type_allowed"

    def _validate_subscription_event(self, data_obj: Dict) -> Tuple[bool, str]:
        """Validate subscription-related webhook data."""
        items = data_obj.get("items", {}).get("data", [])
        for item in items:
            price = item.get("price", {})
            price_id = price.get("id")
            if price_id and price_id not in VALID_PRICE_IDS:
                _logger.warning("Cord 3: unknown price_id %s", price_id[:12] if price_id else "?")
                return False, f"unknown_price_id"

            # Amount sanity check
            amount = price.get("unit_amount")
            if price_id and price_id in VALID_PRICE_IDS and amount is not None:
                expected = VALID_PRICE_IDS[price_id]["amount_cents"]
                if abs(amount - expected) > 100:  # $1 tolerance for coupons
                    _logger.warning(
                        "Cord 3: amount mismatch for %s: got %d, expected %d",
                        price_id[:12] if price_id else "?", amount, expected,
                    )
                    return False, "amount_mismatch"

        # Customer must exist
        customer_id = data_obj.get("customer")
        if not customer_id:
            return False, "no_customer_id"

        return True, "subscription_valid"

    def _validate_checkout_event(self, data_obj: Dict) -> Tuple[bool, str]:
        """Validate checkout session webhook data."""
        amount_total = data_obj.get("amount_total")
        if amount_total is not None and amount_total > 50000_00:  # $50,000 cap
            _logger.warning("Cord 3: checkout amount suspiciously high: %d", amount_total)
            return False, "amount_suspiciously_high"
        return True, "checkout_valid"

    def _validate_payment_intent(self, data_obj: Dict) -> Tuple[bool, str]:
        """Validate payment intent webhook data."""
        customer_id = data_obj.get("customer")
        amount = data_obj.get("amount", 0)
        if amount > 50000_00:
            return False, "payment_amount_suspiciously_high"
        if not customer_id:
            # One-off payments without customer are allowed but flagged
            _logger.info("Cord 3: payment_intent without customer_id")
        return True, "payment_intent_valid"

    # ─── Secret Rotation ────────────────────────────────────────────────────────

    async def rotate_webhook_secret(self, new_secret: str) -> Dict[str, Any]:
        """
        Rotate the webhook signing secret with a dual-verification window.
        During the rotation window (24h by default), both old and new secrets
        are accepted for signature verification.

        After rotation, update STRIPE_WEBHOOK_SECRET in Stripe Dashboard and
        in the .env file, then call this method with the new secret.
        """
        if not new_secret or new_secret == self._webhook_secret:
            _logger.warning("Rotation skipped: new secret is same as current or empty")
            return {"rotated": False, "reason": "same_or_empty"}

        old_secret = self._webhook_secret
        self._previous_secret = old_secret
        self._webhook_secret = new_secret
        self._rotation_deadline = time.time() + (self.ROTATION_WINDOW_HOURS * 3600)

        _logger.warning(
            "WEBHOOK SECRET ROTATED — dual-verification window open for %dh",
            self.ROTATION_WINDOW_HOURS,
        )

        # Log rotation event
        if self._db:
            try:
                await self._db.execute(
                    """INSERT INTO webhook_events_v2
                       (event_id, event_type, cord1_passed, cord2_passed, cord3_passed,
                        processing_result, processed_at)
                       VALUES ($1, 'secret_rotation', TRUE, TRUE, TRUE, 'rotated', NOW())""",
                    f"rotation_{int(time.time())}",
                )
            except Exception as exc:
                _logger.error("Failed to log rotation: %s", exc)

        return {
            "rotated": True,
            "rotation_window_hours": self.ROTATION_WINDOW_HOURS,
            "deadline": self._rotation_deadline,
            "old_secret_hash": hashlib.sha256(
                (old_secret or "").encode()
            ).hexdigest()[:12],
            "new_secret_hash": hashlib.sha256(
                new_secret.encode()
            ).hexdigest()[:12],
        }

    def get_rotation_status(self) -> Dict[str, Any]:
        """Check current rotation window status."""
        if not self._previous_secret or not self._rotation_deadline:
            return {"in_rotation": False}

        remaining = self._rotation_deadline - time.time()
        if remaining <= 0:
            self._previous_secret = None
            self._rotation_deadline = None
            return {"in_rotation": False, "note": "window_just_expired"}

        return {
            "in_rotation": True,
            "remaining_hours": round(remaining / 3600, 1),
            "deadline_unix": self._rotation_deadline,
        }

    # ─── Logging & Idempotency ────────────────────────────────────────────────

    async def _already_processed(self, event_id: str) -> bool:
        """Check if this event was already processed (idempotency)."""
        if not self._db:
            return False
        try:
            row = await self._db.fetchrow(
                "SELECT id FROM webhook_events_v2 WHERE event_id = $1 AND processing_result = 'success'",
                event_id,
            )
            return row is not None
        except Exception:
            return False

    async def _log_webhook_event(
        self, event_id: Optional[str], event_type: str,
        cord1: bool, cord2: bool, cord3: bool, result: str,
    ) -> None:
        """Log the webhook verification result."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT INTO webhook_events_v2
                   (event_id, event_type, cord1_passed, cord2_passed, cord3_passed, processing_result, processed_at)
                   VALUES ($1, $2, $3, $4, $5, $6, NOW())
                   ON CONFLICT (event_id) DO UPDATE SET
                     cord1_passed = $3, cord2_passed = $4, cord3_passed = $5,
                     processing_result = $6, processed_at = NOW()""",
                event_id or "unknown", event_type, cord1, cord2, cord3, result,
            )
        except Exception as exc:
            _logger.error("Failed to log webhook event: %s", type(exc).__name__)

    async def mark_processed(self, event_id: str) -> None:
        """Mark an event as successfully processed."""
        if not self._db:
            return
        try:
            await self._db.execute(
                "UPDATE webhook_events_v2 SET processing_result = 'success', processed_at = NOW() WHERE event_id = $1",
                event_id,
            )
        except Exception as exc:
            _logger.error("Failed to mark event processed: %s", type(exc).__name__)
