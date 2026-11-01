"""Card/bank update notices: expiry, blocked charges, setup-checkout default PM."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.payment_method_notices")

NOTICE_INTERVAL_DAYS = 7
EXPIRING_WITHIN_DAYS = 45
SCAN_INTERVAL_HOURS = 12
SETTINGS_URL = "https://app.sovereignsanctuary.net"
SETTINGS_HINT = (
    "Log in at Sovereign Sanctuary → Settings → Payments "
    "(coach-only home: Settings tab). Use Update Card or Update Bank, "
    "then tap the star so the new method is the default."
)


def card_health(exp_month: int, exp_year: int, now: Optional[datetime] = None) -> str:
    """Return expired | expiring | ok. Cards remain valid through the expiry month."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        month = int(exp_month)
        year = int(exp_year)
    except (TypeError, ValueError):
        return "ok"
    if month < 1 or month > 12 or year < 2000:
        return "ok"
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    if now >= end:
        return "expired"
    if end - now <= timedelta(days=EXPIRING_WITHIN_DAYS):
        return "expiring"
    return "ok"


def should_resend(last_sent: Optional[datetime], now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if last_sent is None:
        return True
    if last_sent.tzinfo is None:
        last_sent = last_sent.replace(tzinfo=timezone.utc)
    return now - last_sent >= timedelta(days=NOTICE_INTERVAL_DAYS)


def _notice_copy(notice_type: str, name: str, detail: str) -> tuple[str, str]:
    who = name or "there"
    extra = f"<p>{detail}</p>" if detail else ""
    if notice_type == "expired_card":
        subject = "Update your card or bank — the card on file has expired"
        why = "The card we have on file has expired, so live-session and membership charges cannot go through."
    elif notice_type == "expiring_card":
        subject = "Your card expires soon — please update it"
        why = "The card on file expires within 45 days. Update it now so your next session is not interrupted."
    else:
        subject = "Payment was declined — update your card or bank"
        why = "A payment was blocked (declined, expired, or no default method). Please update your card or bank account."
    body = (
        f"<p>Hello {who},</p>"
        f"<p>{why}</p>"
        f"{extra}"
        f"<p>{SETTINGS_HINT}</p>"
        f"<p><a href=\"{SETTINGS_URL}\">Open Sovereign Sanctuary</a></p>"
        "<p>Sovereign Sanctuary</p>"
    )
    return subject, body


async def _mark_sent(conn, user_id: str, notice_type: str, detail: str) -> None:
    await conn.execute(
        """INSERT INTO payment_method_notices
               (user_id, notice_type, last_sent_at, send_count, detail)
           VALUES ($1, $2, NOW(), 1, $3)
           ON CONFLICT (user_id, notice_type) DO UPDATE SET
                last_sent_at = NOW(),
                send_count = payment_method_notices.send_count + 1,
                detail = EXCLUDED.detail""",
        user_id, notice_type, (detail or "")[:300],
    )


async def clear_notices(db, user_key: str) -> None:
    if not db or not user_key:
        return
    try:
        async with db.acquire() as conn:
            await conn.execute(
                "DELETE FROM payment_method_notices WHERE user_id = $1",
                user_key,
            )
    except Exception as e:
        logger.warning("clear_notices: %s", e)


async def send_notice(
    db,
    app_state,
    *,
    user_id: str,
    email: str,
    name: str,
    notice_type: str,
    detail: str = "",
) -> bool:
    if not db or not user_id or not email:
        return False
    try:
        async with db.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT last_sent_at FROM payment_method_notices
                    WHERE user_id = $1 AND notice_type = $2""",
                user_id, notice_type,
            )
            last = row["last_sent_at"] if row else None
            if not should_resend(last):
                return False
            notify = getattr(app_state, "notification_system", None) if app_state else None
            subject, body = _notice_copy(notice_type, name, detail)
            if notify and hasattr(notify, "_send_email"):
                await notify._send_email(email, subject, body)
            else:
                from app.services.notifications_service import EmailService
                await EmailService().send_email(email, "payment_method_update", {
                    "name": name or "there",
                    "why": {
                        "expired_card": "The card we have on file has expired.",
                        "expiring_card": "The card on file expires within 45 days.",
                    }.get(notice_type, "A payment was blocked. Please update your card or bank."),
                    "detail": detail or "",
                    "settings_hint": SETTINGS_HINT,
                })
            await _mark_sent(conn, user_id, notice_type, detail)
            logger.info("payment_method_notice %s → %s", notice_type, user_id)
            return True
    except Exception as e:
        logger.warning("send_notice(%s,%s): %s", user_id, notice_type, e)
        return False


async def notify_payment_blocked(db, app_state, *, user_key: str, reason: str = "") -> bool:
    if not db or not user_key:
        return False
    try:
        async with db.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT hardware_id,
                          COALESCE(NULLIF(email, ''), profile_data->>'email') AS email,
                          COALESCE(NULLIF(name, ''), profile_data->>'name') AS name
                     FROM users
                    WHERE hardware_id = $1 OR username = $1
                    LIMIT 1""",
                user_key,
            )
        if not row or not row["email"]:
            return False
        return await send_notice(
            db, app_state,
            user_id=row["hardware_id"] or user_key,
            email=row["email"],
            name=row["name"] or "there",
            notice_type="payment_blocked",
            detail=(reason or "")[:200],
        )
    except Exception as e:
        logger.warning("notify_payment_blocked: %s", e)
        return False


async def promote_checkout_setup(db, session: Dict[str, Any]) -> bool:
    """After Stripe Checkout setup, set the new card/bank as the customer default."""
    meta = session.get("metadata") or {}
    user_key = str(meta.get("user_id") or "")
    customer = session.get("customer")
    if isinstance(customer, dict):
        customer = customer.get("id")
    si = session.get("setup_intent")
    try:
        import stripe
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        if not stripe.api_key:
            return False
        if isinstance(si, str) and si:
            si = stripe.SetupIntent.retrieve(si)
        pm_id = None
        if si is not None:
            raw = getattr(si, "payment_method", None)
            if isinstance(si, dict):
                raw = si.get("payment_method")
            pm_id = raw if isinstance(raw, str) else getattr(raw, "id", None)
        if not pm_id:
            return False
        from app.services.session_financial_records import mirror_default_payment_method
        await mirror_default_payment_method(
            db,
            user_key=user_key,
            payment_method_id=pm_id,
            stripe_customer_id=str(customer or "") or None,
        )
        await clear_notices(db, user_key)
        return True
    except Exception as e:
        logger.warning("promote_checkout_setup: %s", e)
        return False


async def scan_expiring_cards(db, app_state) -> int:
    """Stripe-backed expiry scan for CLIENT accounts with a customer id."""
    if not db:
        return 0
    sent = 0
    try:
        import stripe
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        if not stripe.api_key:
            return 0
        async with db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT hardware_id,
                          COALESCE(NULLIF(email, ''), profile_data->>'email') AS email,
                          COALESCE(NULLIF(name, ''), profile_data->>'name') AS name,
                          COALESCE(NULLIF(stripe_customer_id, ''),
                                   profile_data->>'stripe_customer_id') AS cid
                     FROM users
                    WHERE role = 'CLIENT'
                      AND COALESCE(NULLIF(stripe_customer_id, ''),
                                   profile_data->>'stripe_customer_id', '') <> ''"""
            )
        now = datetime.now(timezone.utc)
        for row in rows:
            cid = (row["cid"] or "").strip()
            email = (row["email"] or "").strip()
            hw = row["hardware_id"] or ""
            if not cid or not email or not hw:
                continue
            try:
                cust = stripe.Customer.retrieve(cid)
                inv = getattr(cust, "invoice_settings", None)
                default_pm = None
                if isinstance(inv, dict):
                    default_pm = inv.get("default_payment_method")
                elif inv is not None:
                    default_pm = getattr(inv, "default_payment_method", None)
                if default_pm and not isinstance(default_pm, str):
                    default_pm = getattr(default_pm, "id", None)
                cards = stripe.PaymentMethod.list(customer=cid, type="card", limit=5)
                target = None
                for pm in cards.data:
                    if default_pm and pm.id == default_pm:
                        target = pm
                        break
                if target is None and cards.data:
                    target = cards.data[0]
                if target is None or not getattr(target, "card", None):
                    continue
                health = card_health(target.card.exp_month, target.card.exp_year, now)
                if health == "ok":
                    continue
                last4 = getattr(target.card, "last4", "") or ""
                detail = f"Visa/card ending {last4} exp {target.card.exp_month}/{target.card.exp_year}"
                ntype = "expired_card" if health == "expired" else "expiring_card"
                if await send_notice(
                    db, app_state,
                    user_id=hw, email=email, name=row["name"] or "there",
                    notice_type=ntype, detail=detail,
                ):
                    sent += 1
            except Exception as e:
                logger.warning("scan_expiring_cards user=%s: %s", hw, e)
    except Exception as e:
        logger.warning("scan_expiring_cards: %s", e)
    return sent


async def run_payment_method_notice_cycle(db, app_state, *, force_expiry_scan: bool = False) -> int:
    sent = 0
    try:
        async with db.acquire() as conn:
            fails = await conn.fetch(
                """SELECT DISTINCT s.client_id, e.error_message
                     FROM session_payment_events e
                     JOIN coaching_sessions s ON s.id = e.session_id
                    WHERE e.event_type = 'charge_failed'
                      AND e.created_at > NOW() - INTERVAL '6 hours'"""
            )
        for row in fails:
            if await notify_payment_blocked(
                db, app_state,
                user_key=str(row["client_id"] or ""),
                reason=str(row["error_message"] or "")[:200],
            ):
                sent += 1
    except Exception as e:
        logger.warning("run_payment_method_notice_cycle blocked: %s", e)

    due = force_expiry_scan
    if not due:
        try:
            async with db.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT last_sent_at FROM payment_method_notices
                        WHERE user_id = '_system' AND notice_type = 'expiry_scan'"""
                )
            last = row["last_sent_at"] if row else None
            if last is None:
                due = True
            else:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                due = datetime.now(timezone.utc) - last >= timedelta(hours=SCAN_INTERVAL_HOURS)
        except Exception as e:
            logger.warning("run_payment_method_notice_cycle scan watermark: %s", e)
            due = False
    if due:
        try:
            sent += await scan_expiring_cards(db, app_state)
            async with db.acquire() as conn:
                await _mark_sent(conn, "_system", "expiry_scan", "ok")
        except Exception as e:
            logger.warning("run_payment_method_notice_cycle expiry: %s", e)
    return sent
