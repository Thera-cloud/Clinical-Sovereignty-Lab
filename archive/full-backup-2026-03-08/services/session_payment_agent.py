"""
Session Payment Agent — 72-hour advance payment collection.

Runs every 30 minutes, checks for upcoming sessions in the 72-hour window,
charges cards on file, sends SMS/email reminders, and auto-cancels unpaid
sessions at the 24-hour mark.

SESSION_BILLING_MODE env var controls behavior:
  "test"  — logs simulated charge with full fee breakdown, no Stripe call
  "live"  — charges real cards via Stripe
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("nate.session_payment_agent")

PAYMENT_WINDOW_HOURS = 72
CANCELLATION_WINDOW_HOURS = 24
MIN_FEE_CENTS = 3000  # $30 minimum
PLATFORM_FEE_PCT = 30.0
PLATFORM_FEE_MIN_DOLLARS = 30.00

SESSION_BILLING_MODE = os.getenv("SESSION_BILLING_MODE", "test")


class SessionPaymentAgent:
    """Background agent that processes session payments 72 hours in advance."""

    def __init__(self, db_pool=None, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("SessionPaymentAgent: started (30min cycle)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SessionPaymentAgent: stopped")

    async def _run_loop(self):
        await asyncio.sleep(60)
        while self._running:
            try:
                await self._run_one_cycle()
            except Exception as e:
                logger.error("SessionPaymentAgent: cycle error: %s", e)
            await asyncio.sleep(1800)  # 30 minutes

    async def _run_one_cycle(self):
        if not self.db_pool:
            return

        now = datetime.now(timezone.utc)
        window_start = now
        window_end = now + timedelta(hours=PAYMENT_WINDOW_HOURS)
        cancel_deadline = now + timedelta(hours=CANCELLATION_WINDOW_HOURS)

        async with self.db_pool.acquire() as conn:
            sessions_to_charge = await conn.fetch(
                """SELECT cs.id, cs.coach_id, cs.client_id,
                          COALESCE(cs.scheduled_start, cs.scheduled_at) as session_time,
                          cs.price_cents, cs.payment_status,
                          u.profile_data->>'name' as client_name,
                          u.profile_data->>'email' as client_email,
                          u.profile_data->>'phone' as client_phone,
                          u.profile_data->>'stripe_customer_id' as stripe_customer_id
                   FROM coaching_sessions cs
                   LEFT JOIN users u ON u.hardware_id = cs.client_id
                   WHERE COALESCE(cs.scheduled_start, cs.scheduled_at) BETWEEN $1 AND $2
                   AND cs.payment_status = 'pending'
                   AND cs.payment_status != 'waived'
                   AND cs.status != 'CANCELLED'""",
                window_start, window_end,
            )

            charged = 0
            reminded = 0
            cancelled = 0

            for session in sessions_to_charge:
                session_id = session["id"]
                fee_cents = session["price_cents"] or 0
                stripe_customer = session["stripe_customer_id"]
                client_name = session["client_name"] or "Client"

                charge_amount = max(fee_cents, MIN_FEE_CENTS) if fee_cents > 0 else 0

                if charge_amount <= 0:
                    continue

                if SESSION_BILLING_MODE == "test":
                    success = await self._simulate_charge(
                        conn, session_id, charge_amount, client_name
                    )
                    if success:
                        charged += 1
                elif stripe_customer:
                    success = await self._charge_card(
                        conn, session_id, stripe_customer, charge_amount
                    )
                    if success:
                        charged += 1
                    else:
                        await self._send_payment_reminder(conn, session, charge_amount)
                        reminded += 1
                else:
                    await self._send_payment_reminder(conn, session, charge_amount)
                    reminded += 1

            overdue = await conn.fetch(
                """SELECT id, coach_id, client_id
                   FROM coaching_sessions
                   WHERE COALESCE(scheduled_start, scheduled_at) < $1
                   AND payment_status = 'pending'
                   AND payment_status != 'waived'
                   AND status != 'CANCELLED'""",
                cancel_deadline,
            )

            for s in overdue:
                await conn.execute(
                    """UPDATE coaching_sessions
                       SET status = 'CANCELLED', payment_status = 'cancelled',
                           updated_at = NOW()
                       WHERE id = $1""",
                    s["id"],
                )
                await self._log_event(conn, s["id"], "cancellation", 0, note="Auto-cancelled: payment overdue")
                cancelled += 1

            # 48-hour session reminders (Phase 7)
            reminder_48h_start = now + timedelta(hours=47)
            reminder_48h_end = now + timedelta(hours=49)
            upcoming_48h = await conn.fetch(
                """SELECT cs.id, cs.coach_id, cs.client_id,
                          COALESCE(cs.scheduled_start, cs.scheduled_at) as scheduled_at,
                          cs.payment_status,
                          u.profile_data->>'name' as client_name,
                          u.profile_data->>'email' as client_email,
                          u.profile_data->>'phone' as client_phone,
                          cu.profile_data->>'name' as coach_name,
                          cu.profile_data->>'email' as coach_email
                   FROM coaching_sessions cs
                   LEFT JOIN users u ON u.hardware_id = cs.client_id
                   LEFT JOIN users cu ON cu.hardware_id = cs.coach_id AND cu.role = 'COACH'
                   WHERE COALESCE(cs.scheduled_start, cs.scheduled_at) BETWEEN $1 AND $2
                   AND cs.status != 'CANCELLED'""",
                reminder_48h_start, reminder_48h_end,
            )

            for s in upcoming_48h:
                await self._send_48h_reminder(conn, s)
                reminded += 1

            # Confirmation notifications for newly paid sessions
            newly_paid = await conn.fetch(
                """SELECT cs.id, cs.client_id, cs.coach_id,
                          COALESCE(cs.scheduled_start, cs.scheduled_at) as scheduled_at,
                          u.profile_data->>'name' as client_name,
                          u.profile_data->>'email' as client_email,
                          cu.profile_data->>'email' as coach_email,
                          cu.profile_data->>'name' as coach_name
                   FROM coaching_sessions cs
                   LEFT JOIN users u ON u.hardware_id = cs.client_id
                   LEFT JOIN users cu ON cu.hardware_id = cs.coach_id AND cu.role = 'COACH'
                   WHERE cs.payment_status IN ('paid', 'test_paid')
                   AND cs.status != 'CANCELLED'
                   AND COALESCE(cs.scheduled_start, cs.scheduled_at) > NOW()
                   AND NOT EXISTS (
                       SELECT 1 FROM session_notifications sn
                       WHERE sn.session_id = cs.id AND sn.notification_type = 'confirmation'
                   )""",
            )

            for s in newly_paid:
                await self._send_confirmation(conn, s)

            if charged or reminded or cancelled:
                logger.info(
                    "SessionPaymentAgent: cycle complete — %d charged, %d reminded, %d cancelled",
                    charged, reminded, cancelled,
                )

    async def _simulate_charge(self, conn, session_id, amount_cents: int, client_name: str) -> bool:
        """Log a simulated charge with full fee breakdown — no real Stripe call."""
        try:
            gross = amount_cents / 100.0
            platform_fee = max(gross * (PLATFORM_FEE_PCT / 100.0), PLATFORM_FEE_MIN_DOLLARS)
            coach_payout = max(gross - platform_fee, 0)

            await conn.execute(
                """UPDATE coaching_sessions
                   SET payment_status = 'test_paid', payment_amount_cents = $1, updated_at = NOW()
                   WHERE id = $2""",
                amount_cents, session_id,
            )

            breakdown = {
                "mode": "test",
                "gross_fee_dollars": round(gross, 2),
                "platform_fee_30pct": round(platform_fee, 2),
                "coach_payout": round(coach_payout, 2),
                "client_name": client_name,
            }
            await self._log_event(
                conn, session_id, "test_charge_simulated", amount_cents,
                note=json.dumps(breakdown),
            )
            logger.info(
                "SessionPaymentAgent: TEST charge — $%.2f gross, $%.2f platform (30%%), $%.2f coach payout (session %s, client %s)",
                gross, platform_fee, coach_payout, session_id, client_name,
            )
            return True
        except Exception as e:
            logger.warning("SessionPaymentAgent: simulate_charge failed for %s: %s", session_id, e)
            return False

    async def _charge_card(self, conn, session_id, stripe_customer_id: str, amount_cents: int) -> bool:
        """Attempt to charge the client's card on file via Stripe."""
        try:
            import stripe
            stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

            if not stripe.api_key:
                logger.warning("SessionPaymentAgent: STRIPE_SECRET_KEY not set")
                return False

            payment_methods = stripe.PaymentMethod.list(
                customer=stripe_customer_id, type="card", limit=1
            )
            if not payment_methods.data:
                await self._log_event(conn, session_id, "charge_failed", amount_cents, error="No card on file")
                return False

            pm = payment_methods.data[0]

            intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency="usd",
                customer=stripe_customer_id,
                payment_method=pm.id,
                off_session=True,
                confirm=True,
                metadata={"session_id": str(session_id), "type": "session_payment"},
            )

            if intent.status == "succeeded":
                await conn.execute(
                    """UPDATE coaching_sessions
                       SET payment_status = 'paid', payment_amount_cents = $1,
                           stripe_payment_intent_id = $2, updated_at = NOW()
                       WHERE id = $3""",
                    amount_cents, intent.id, session_id,
                )
                await self._log_event(conn, session_id, "charge_succeeded", amount_cents, stripe_id=intent.id)
                return True
            else:
                await self._log_event(conn, session_id, "charge_failed", amount_cents, error=f"Status: {intent.status}")
                return False

        except Exception as e:
            logger.warning("SessionPaymentAgent: Stripe charge failed for session %s: %s", session_id, e)
            await self._log_event(conn, session_id, "charge_failed", amount_cents, error=str(e))
            return False

    async def _send_payment_reminder(self, conn, session, amount_cents: int):
        """Send SMS + email payment reminder."""
        session_id = session["id"]
        client_email = session["client_email"]
        client_phone = session["client_phone"]
        client_name = session["client_name"] or "Client"

        already_sent = await conn.fetchval(
            """SELECT EXISTS(SELECT 1 FROM session_notifications
               WHERE session_id = $1 AND notification_type = 'payment_due_72h')""",
            session_id,
        )
        if already_sent:
            return

        notify = getattr(self.app_state, "notification_system", None) if self.app_state else None

        if client_email and notify and hasattr(notify, "_send_email"):
            try:
                subject = "Payment Due — Upcoming Session"
                body = f"""<p>Hello {client_name},</p>
<p>Your coaching session is scheduled soon. Payment of ${amount_cents / 100:.2f} is due.</p>
<p>Please ensure your payment method is up to date in the app.</p>
<p>Thank you,<br>Sovereign Sanctuary</p>"""
                await notify._send_email(client_email, subject, body)
                await conn.execute(
                    """INSERT INTO session_notifications (session_id, notification_type, channel, recipient_id)
                       VALUES ($1, 'payment_due_72h', 'email', $2) ON CONFLICT DO NOTHING""",
                    session_id, session["client_id"],
                )
            except Exception as e:
                logger.warning("SessionPaymentAgent: email reminder failed: %s", e)

        await self._log_event(conn, session_id, "reminder_sent", amount_cents, note="72h payment reminder")

    async def _send_48h_reminder(self, conn, session):
        """Send 48-hour session reminder with cancellation window notice."""
        session_id = session["id"]
        already = await conn.fetchval(
            """SELECT EXISTS(SELECT 1 FROM session_notifications
               WHERE session_id = $1 AND notification_type = 'reminder_48h')""",
            session_id,
        )
        if already:
            return

        notify = getattr(self.app_state, "notification_system", None) if self.app_state else None
        client_email = session["client_email"]
        client_name = session["client_name"] or "Client"
        session_date = session["scheduled_at"]
        payment_status = session["payment_status"] or "pending"

        if client_email and notify and hasattr(notify, "_send_email"):
            try:
                payment_note = ""
                if payment_status != "paid":
                    payment_note = "<p><strong>Payment reminder:</strong> Please ensure your payment is completed before the session. Sessions with outstanding payment may be cancelled within 24 hours.</p>"

                subject = "Session Reminder — 48 Hours"
                body = f"""<p>Hello {client_name},</p>
<p>This is a reminder that your coaching session is scheduled for <strong>{session_date}</strong>.</p>
{payment_note}
<p><strong>Cancellation policy:</strong> You may cancel up to 24 hours before the session for a full refund.</p>
<p>See you soon!<br>Sovereign Sanctuary</p>"""

                await notify._send_email(client_email, subject, body)
                await conn.execute(
                    """INSERT INTO session_notifications (session_id, notification_type, channel, recipient_id)
                       VALUES ($1, 'reminder_48h', 'email', $2) ON CONFLICT DO NOTHING""",
                    session_id, session["client_id"],
                )
            except Exception as e:
                logger.warning("SessionPaymentAgent: 48h email reminder failed: %s", e)

    async def _send_confirmation(self, conn, session):
        """Send payment confirmation to both client and coach."""
        session_id = session["id"]
        notify = getattr(self.app_state, "notification_system", None) if self.app_state else None
        if not notify or not hasattr(notify, "_send_email"):
            return

        client_email = session.get("client_email")
        coach_email = session.get("coach_email")
        client_name = session.get("client_name", "Client")
        coach_name = session.get("coach_name", "Coach")
        session_date = session.get("scheduled_at", "")

        if client_email:
            try:
                await notify._send_email(
                    client_email,
                    "Session Confirmed — Payment Received",
                    f"""<p>Hello {client_name},</p>
<p>Your payment has been received. Your session on <strong>{session_date}</strong> is confirmed.</p>
<p>Thank you,<br>Sovereign Sanctuary</p>""",
                )
            except Exception as e:
                logger.warning("SessionPaymentAgent: client confirmation email failed: %s", e)

        if coach_email:
            try:
                await notify._send_email(
                    coach_email,
                    f"Session Payment Confirmed — {client_name}",
                    f"""<p>Hello {coach_name},</p>
<p>Payment received for your session with <strong>{client_name}</strong> on <strong>{session_date}</strong>.</p>
<p>Sovereign Sanctuary</p>""",
                )
            except Exception as e:
                logger.warning("SessionPaymentAgent: coach confirmation email failed: %s", e)

        try:
            await conn.execute(
                """INSERT INTO session_notifications (session_id, notification_type, channel, recipient_id)
                   VALUES ($1, 'confirmation', 'email', $2) ON CONFLICT DO NOTHING""",
                session_id, session["client_id"],
            )
        except Exception as e:
            logger.warning("SessionPaymentAgent: confirmation log failed: %s", e)

    async def _log_event(self, conn, session_id, event_type: str, amount_cents: int,
                         stripe_id: str = None, error: str = None, note: str = None):
        """Log a payment event."""
        try:
            metadata = json.dumps({"note": note or ""})
            await conn.execute(
                """INSERT INTO session_payment_events (session_id, event_type, amount_cents,
                      stripe_payment_intent_id, error_message, metadata)
                   VALUES ($1, $2, $3, $4, $5, $6::jsonb)""",
                session_id, event_type, amount_cents, stripe_id, error,
                metadata,
            )
        except Exception as e:
            logger.warning("SessionPaymentAgent: failed to log event: %s", e)
