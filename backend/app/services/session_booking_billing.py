"""Session booking billing — card gate, membership session discounts, cancel refunds.

Policy (client-facing): charge membership session rate after coach accepts,
via SessionPaymentAgent in the 72h pre-session window. Inner Chamber: $50 off
every session. Sovereign Circle: $50 off the household's first session each
month, then $85 off each additional (family-scoped). Cancel ≥24h before
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
    "By booking, you agree to pay your membership session rate "
    "(Inner Chamber: $50 off every session; Sovereign Circle: $50 off the "
    "household's first session each month, then $85 off each additional). "
    "After your coach accepts, your card on file will be charged in the "
    "72-hour window before the session. Payment is due before the session. "
    "Cancel at least 24 hours before the start time for a full refund. "
    "Cancellations inside 24 hours are not refundable."
)

# Membership discounts off the coach's listed rate (cents). CoachN $175 →
# Inner Chamber $125 every session; Sovereign Circle $125 first / $90 after.
INNER_CHAMBER_SESSION_DISCOUNT_CENTS = 5000
SOVEREIGN_CIRCLE_FIRST_SESSION_DISCOUNT_CENTS = 5000
SOVEREIGN_CIRCLE_ADDITIONAL_SESSION_DISCOUNT_CENTS = 8500

_COUNT_STATUSES_EXCLUDED = (
    "cancelled",
    "canceled",
    "declined",
    "rejected",
    "no_show",
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


def session_discount_cents(plan: str | None, prior_family_sessions_this_month: int) -> int:
    """Membership discount off listed coach rate. Family-scoped for Sovereign Circle."""
    from app.constants.tiers import session_plan_bucket

    bucket = session_plan_bucket(plan)
    prior = max(0, int(prior_family_sessions_this_month or 0))
    if bucket == "IC":
        return INNER_CHAMBER_SESSION_DISCOUNT_CENTS
    if bucket == "SC":
        if prior <= 0:
            return SOVEREIGN_CIRCLE_FIRST_SESSION_DISCOUNT_CENTS
        return SOVEREIGN_CIRCLE_ADDITIONAL_SESSION_DISCOUNT_CENTS
    return 0


def billed_session_cents(coach_fee_dollars: Any, discount_cents: int) -> int:
    listed = fee_cents_from_coach_fee(coach_fee_dollars)
    if listed <= 0:
        return 0
    return max(0, listed - max(0, int(discount_cents or 0)))


def _month_bounds(dt: datetime) -> Tuple[datetime, datetime]:
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _prior_family_sessions_this_month(
    db_pool,
    client_hardware_id: str,
    family_id: str,
    month_start: datetime,
    month_end: datetime,
) -> int:
    if not db_pool:
        return 0
    fid = (family_id or "").strip()
    hid = (client_hardware_id or "").strip()
    if not hid and not fid:
        return 0
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS cnt
                FROM coaching_sessions
                WHERE scheduled_start >= $1 AND scheduled_start < $2
                  AND COALESCE(status, '') <> ALL($3::text[])
                  AND COALESCE(payment_status, '') NOT IN ('refunded', 'waived')
                  AND (
                    ($4 <> '' AND (
                      family_id = $4
                      OR client_id IN (
                        SELECT hardware_id FROM users
                        WHERE deleted_at IS NULL
                          AND (
                            family_id::text = $4
                            OR COALESCE(profile_data->>'family_id', '') = $4
                          )
                      )
                    ))
                    OR client_id = $5
                  )
                """,
                month_start,
                month_end,
                list(_COUNT_STATUSES_EXCLUDED),
                fid,
                hid,
            )
            return int((row["cnt"] if row else 0) or 0)
    except Exception as e:
        logger.warning("prior family session count failed: %s", e)
        return 0


async def quote_session_price_cents(
    db_pool,
    *,
    client_hardware_id: str,
    family_id: str,
    coach_fee_dollars: Any,
    scheduled_start: Any = None,
    client_plan: Optional[str] = None,
) -> int:
    """Client charge in cents after membership discount (family-scoped for SC)."""
    plan = client_plan
    if db_pool and client_hardware_id:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT COALESCE(profile_data->>'subscription_plan', tier) AS plan
                    FROM users
                    WHERE hardware_id = $1 OR username = $1
                    LIMIT 1
                    """,
                    client_hardware_id,
                )
                if row and row["plan"]:
                    plan = row["plan"]
        except Exception as e:
            logger.warning("quote_session_price_cents plan lookup: %s", e)

    when = datetime.now(timezone.utc)
    if scheduled_start:
        if isinstance(scheduled_start, datetime):
            when = _as_aware(scheduled_start)
        else:
            try:
                when = _as_aware(
                    datetime.fromisoformat(str(scheduled_start).replace("Z", "+00:00"))
                )
            except Exception:
                pass
    month_start, month_end = _month_bounds(when)
    prior = await _prior_family_sessions_this_month(
        db_pool, client_hardware_id, family_id, month_start, month_end
    )
    discount = session_discount_cents(plan, prior)
    return billed_session_cents(coach_fee_dollars, discount)


def apply_fee_to_session(session: Dict[str, Any], coach_fee_dollars: float, fee_info: Dict[str, Any]) -> None:
    """Stamp session with billable fields for PG + payment agent."""
    cents = int(session.get("price_cents") or 0) or fee_cents_from_coach_fee(coach_fee_dollars)
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
