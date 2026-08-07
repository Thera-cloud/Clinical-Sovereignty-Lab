"""Session booking billing — card gate, coach fee → price_cents, cancel refunds.

Policy (client-facing): charge full coach coaching_fee after coach accepts,
via SessionPaymentAgent in the 72h pre-session window. Cancel ≥24h before
start → full Stripe refund if already paid. Cancel inside 24h → no refund.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("nate.session_booking_billing")

# Shown in client schedule UI and emails — keep in sync with Flutter copy.
SESSION_PAYMENT_POLICY = (
    "By booking, you agree to pay your coach's full session rate. "
    "After your coach accepts, your card on file will be charged in the "
    "72-hour window before the session. Payment is due before the session. "
    "Cancel at least 24 hours before the start time for a full refund. "
    "Cancellations inside 24 hours are not refundable."
)


def booking_billing_enabled() -> bool:
    return os.getenv("ENABLE_SESSION_BOOKING_BILLING", "true").lower() in (
        "1",
        "true",
        "yes",
    )


def fee_cents_from_coach_fee(coach_fee: Any) -> int:
    """Convert coach profile coaching_fee (dollars) to integer cents."""
    try:
        dollars = float(coach_fee or 0)
    except (TypeError, ValueError):
        return 0
    if dollars <= 0:
        return 0
    return int(round(dollars * 100))


def apply_fee_to_session(session: Dict[str, Any], coach_fee_dollars: float, fee_info: Dict[str, Any]) -> None:
    """Stamp session with billable fields for PG + payment agent."""
    cents = fee_cents_from_coach_fee(coach_fee_dollars)
    session["coach_fee"] = fee_info.get("coach_fee", coach_fee_dollars)
    session["platform_fee"] = fee_info.get("platform_fee", 0)
    session["coach_payout"] = fee_info.get("coach_payout", 0)
    session["price_cents"] = cents
    if cents > 0 and not session.get("payment_status"):
        session["payment_status"] = "pending"


async def resolve_stripe_customer_id(db_pool, hardware_id: str) -> Optional[str]:
    if not db_pool or not hardware_id:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT stripe_customer_id,
                          profile_data->>'stripe_customer_id' AS pd_cid
                   FROM users
                   WHERE hardware_id = $1 AND deleted_at IS NULL
                   LIMIT 1""",
                hardware_id,
            )
            if not row:
                return None
            return (row["stripe_customer_id"] or row["pd_cid"] or "") or None
    except Exception as e:
        logger.warning("resolve_stripe_customer_id: %s", e)
        return None


async def client_has_card_on_file(db_pool, hardware_id: str) -> bool:
    """True if Stripe customer exists and has at least one card payment method."""
    customer_id = await resolve_stripe_customer_id(db_pool, hardware_id)
    if not customer_id:
        return False
    try:
        import stripe

        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        if not stripe.api_key:
            return False
        pms = stripe.PaymentMethod.list(customer=customer_id, type="card", limit=1)
        return bool(pms.data)
    except Exception as e:
        logger.warning("client_has_card_on_file: %s", e)
        return False


def _parse_start(session: Dict[str, Any]) -> Optional[datetime]:
    raw = (session.get("scheduled_start") or session.get("scheduled_at") or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


async def refund_on_client_cancel(
    db_pool,
    session: Dict[str, Any],
) -> Tuple[str, str]:
    """Refund if paid and cancel is ≥24h before start.

    Returns (outcome, detail) where outcome is one of:
    refunded | not_paid | too_late | no_intent | error | skipped
    """
    if not booking_billing_enabled():
        return "skipped", "billing disabled"
    start = _parse_start(session)
    if not start:
        return "error", "missing scheduled_start"
    now = datetime.now(timezone.utc)
    if start - now < timedelta(hours=24):
        return "too_late", "inside 24h cancellation window — no refund"

    intent_id = (
        session.get("stripe_payment_intent_id")
        or session.get("stripe_payment_intent")
        or ""
    ).strip()
    payment_status = (session.get("payment_status") or "").lower()

    # Prefer PG truth for paid + intent
    if db_pool and session.get("session_id"):
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT payment_status, stripe_payment_intent_id, price_cents
                       FROM coaching_sessions WHERE session_id = $1 LIMIT 1""",
                    session["session_id"],
                )
                if row:
                    payment_status = (row["payment_status"] or payment_status or "").lower()
                    intent_id = (row["stripe_payment_intent_id"] or intent_id or "").strip()
        except Exception as e:
            logger.warning("refund_on_client_cancel PG read: %s", e)

    if payment_status != "paid":
        return "not_paid", "no charge to refund"
    if not intent_id:
        return "no_intent", "paid but missing payment intent"

    try:
        import stripe

        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        if not stripe.api_key:
            return "error", "STRIPE_SECRET_KEY missing"
        refund = stripe.Refund.create(payment_intent=intent_id)
        if db_pool:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """UPDATE coaching_sessions
                       SET payment_status = 'refunded', updated_at = NOW()
                       WHERE session_id = $1""",
                    session.get("session_id"),
                )
                try:
                    import json as _json
                    await conn.execute(
                        """INSERT INTO session_payment_events
                           (session_id, event_type, amount_cents, stripe_payment_intent_id, metadata)
                           VALUES (
                             (SELECT id FROM coaching_sessions WHERE session_id = $1 LIMIT 1),
                             'refund', $2, $3, $4::jsonb
                           )""",
                        session.get("session_id"),
                        int(refund.amount or 0),
                        intent_id,
                        _json.dumps({"source": "client_cancel", "refund_id": refund.id}),
                    )
                except Exception:
                    pass
        session["payment_status"] = "refunded"
        return "refunded", refund.id
    except Exception as e:
        logger.warning("refund_on_client_cancel Stripe: %s", e)
        return "error", str(e)
