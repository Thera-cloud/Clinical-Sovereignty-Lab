"""
Session Payment Agent — 72-hour advance payment collection.

Runs every 30 minutes, checks for upcoming sessions in the 72-hour window,
charges cards on file, sends SMS/email reminders, and auto-cancels unpaid
sessions at the 24-hour mark.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.utils.timezone_resolver import format_session_start_for_profile
from app.services.session_charge_guard import (
    NOT_COLLECTED_SQL,
    amount_within_ceiling,
    claim_charge,
    collected_reason,
    collection_state,
    idempotency_key,
    record_payment_history,
    release_claim,
    stripe_existing_charge,
)

logger = logging.getLogger("nate.session_payment_agent")


def _is_clone_node() -> bool:
    return os.getenv("IS_CLONE", "").lower() in ("true", "1", "yes")


PAYMENT_WINDOW_HOURS = 72
CANCELLATION_WINDOW_HOURS = 24
MIN_FEE_CENTS = 3000  # $30 minimum

# Canonical appointment time: REST/bridge writes scheduled_start; legacy rows use scheduled_at.
_APPT_TIME = "COALESCE(cs.scheduled_start, cs.scheduled_at)"
_APPT_TIME_BARE = "COALESCE(scheduled_start, scheduled_at)"
_NOT_CANCELLED = (
    "UPPER(cs.status) NOT IN "
    "('CANCELLED', 'RESCHEDULED', 'CANCELLED_BY_GOOGLE', 'CANCELED')"
)
_NOT_CANCELLED_BARE = (
    "UPPER(status) NOT IN "
    "('CANCELLED', 'RESCHEDULED', 'CANCELLED_BY_GOOGLE', 'CANCELED')"
)


def _format_scheduled_for_session(session: dict, tz_key: str = "client_timezone") -> str:
    """Human-readable local session time for email bodies (TZ-NOTIFICATION-FIX)."""
    scheduled = session.get("scheduled_at")
    if not scheduled:
        return "your upcoming session"
    profile = {"timezone": session.get(tz_key) or session.get("client_timezone")}
    text, tz_name = format_session_start_for_profile(scheduled, profile)
    return f"{text} ({tz_name})"


class SessionPaymentAgent:
    """Background agent that processes session payments 72 hours in advance."""

    def __init__(self, db_pool=None, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if _is_clone_node():
            logger.info("SessionPaymentAgent: skipped (IS_CLONE) — GREEN owns charges")
            return
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
        if _is_clone_node():
            return
        if not self.db_pool:
            return

        # QUANTUM-CRYSTAL-ARCH: expire stale Nate negotiations (24h) alongside payment sweep
        try:
            from app.services.session_negotiation_service import (
                expire_stale_negotiations,
                negotiation_enabled,
            )

            if negotiation_enabled():
                await expire_stale_negotiations(self.db_pool, max_age_hours=24)
        except Exception as e:
            logger.warning("SessionPaymentAgent: negotiation expire skipped: %s", e)

        now = datetime.now(timezone.utc)
        window_start = now
        window_end = now + timedelta(hours=PAYMENT_WINDOW_HOURS)
        cancel_deadline = now + timedelta(hours=CANCELLATION_WINDOW_HOURS)
        unpaid_cancel_sessions = []

        async with self.db_pool.acquire() as conn:
            try:
                from app.services.session_booking_billing import APPLY_CUSTOM_SESSION_RATE_SQL
                from app.services.session_invoice_ledger import HYDRATE_SESSION_PRICE_SQL

                await conn.execute(APPLY_CUSTOM_SESSION_RATE_SQL)
                await conn.execute(HYDRATE_SESSION_PRICE_SQL)
            except Exception as e:
                logger.warning("SessionPaymentAgent: price hydrate skipped: %s", e)

            # Find sessions in the payment window that need charging
            # QUANTUM-CRYSTAL-ARCH: charge only after coach accepts (scheduled/confirmed/active)
            sessions_to_charge = await conn.fetch(
                f"""SELECT cs.id, cs.session_id AS session_id_str, cs.coach_id, cs.client_id,
                          {_APPT_TIME} AS scheduled_at, cs.price_cents,
                          cs.payment_status, cs.session_data,
                          u.profile_data->>'name' as client_name,
                          u.profile_data->>'email' as client_email,
                          u.profile_data->>'phone' as client_phone,
                          u.profile_data->>'timezone' as client_timezone,
                          COALESCE(NULLIF(u.stripe_customer_id, ''),
                                   u.profile_data->>'stripe_customer_id') as stripe_customer_id,
                          COALESCE(u.profile_data->>'default_payment_method_id', '')
                              as client_default_pm,
                          COALESCE(cu.profile_data->>'stripe_connect_id', '') as coach_connect_id,
                          COALESCE(cu.profile_data->>'payment_mode', 'coach_handles')
                              as coach_payment_mode
                   FROM coaching_sessions cs
                   LEFT JOIN users u ON u.id::text = cs.client_id::text
                      OR u.hardware_id = cs.client_id::text
                   LEFT JOIN users cu ON cu.id::text = cs.coach_id::text
                      OR cu.hardware_id = cs.coach_id::text
                   WHERE {_APPT_TIME} BETWEEN $1 AND $2
                   AND cs.payment_status = 'pending'
                   AND {NOT_COLLECTED_SQL}
                   AND COALESCE(cs.price_cents, 0) > 0
                   AND COALESCE(cs.session_data->>'stripe_invoice_id', '') = ''
                   AND COALESCE(cs.session_data->>'collect_later', '') NOT IN ('true','1','yes')
                   AND UPPER(cs.status) IN ('SCHEDULED', 'CONFIRMED', 'ACTIVE')
                   AND {_NOT_CANCELLED}""",
                window_start, window_end,
            )

            charged = 0
            reminded = 0
            cancelled = 0
            # Charge skipped because Stripe could not be verified. Do not cancel
            # those sessions this cycle — a search/API failure is not non-payment.
            unverified_session_ids = set()

            for session in sessions_to_charge:
                session_id = session["id"]
                fee_cents = session["price_cents"] or 0
                stripe_customer = session["stripe_customer_id"]

                charge_amount = max(fee_cents, MIN_FEE_CENTS) if fee_cents > 0 else 0

                if charge_amount <= 0:
                    continue
                if not amount_within_ceiling(charge_amount):
                    logger.error(
                        "SessionPaymentAgent: %s charge %s cents exceeds ceiling — refusing",
                        session["session_id_str"], charge_amount,
                    )
                    await self._log_event(conn, session_id, "charge_skipped", charge_amount,
                                          note=f"amount {charge_amount} over ceiling")
                    continue

                if stripe_customer:
                    # Tri-state: True charged, False card failed (remind + invoice),
                    # None = already collected / could not verify → do nothing.
                    success = await self._charge_card(
                        conn, session, stripe_customer, charge_amount
                    )
                    if success is None:
                        unverified_session_ids.add(session["id"])
                    elif success is True:
                        charged += 1
                    elif success is False:
                        await self._send_payment_reminder(conn, session, charge_amount)
                        await self._ensure_open_invoice(conn, session, charge_amount)
                        reminded += 1
                else:
                    await self._send_payment_reminder(conn, session, charge_amount)
                    await self._ensure_open_invoice(conn, session, charge_amount)
                    reminded += 1

            # Auto-cancel unpaid sessions past the 24-hour deadline
            overdue = await conn.fetch(
                f"""SELECT id, session_id, coach_id, client_id, client_name,
                          google_event_id, scheduled_end, session_data,
                          {_APPT_TIME_BARE} AS scheduled_at
                   FROM coaching_sessions
                   WHERE {_APPT_TIME_BARE} <= $1
                   AND payment_status = 'pending'
                   AND COALESCE(price_cents, 0) > 0
                   AND COALESCE(session_data->>'late_cancel_fee', '') NOT IN ('true','1','yes')
                   AND COALESCE(session_data->>'collect_later', '') NOT IN ('true','1','yes')
                   AND {_NOT_CANCELLED_BARE}""",
                cancel_deadline,
            )

            for s in overdue:
                if s["id"] in unverified_session_ids:
                    logger.warning(
                        "SessionPaymentAgent: skip 24h cancel for %s — charge was not verified this cycle",
                        s.get("session_id"),
                    )
                    continue
                await conn.execute(
                    """UPDATE coaching_sessions
                       SET status = 'cancelled', payment_status = 'cancelled',
                           session_data = COALESCE(session_data, '{}'::jsonb)
                             || '{"cancel_notify_sent": true}'::jsonb
                             || jsonb_build_object(
                                  'cancellation_reason',
                                  'Payment was not received before the 24-hour deadline.',
                                  'cancelled_at', NOW()::text
                                ),
                           updated_at = NOW()
                       WHERE id = $1""",
                    s["id"],
                )
                await self._log_event(conn, s["id"], "cancellation", 0, note="Auto-cancelled: payment overdue")
                cancelled += 1
                try:
                    from app.services.session_invoice_ledger import void_open_session_invoice
                    await void_open_session_invoice(conn, dict(s))
                except Exception as e:
                    logger.warning(
                        "SessionPaymentAgent: void invoice on unpaid cancel failed sid=%s: %s",
                        s.get("session_id"), e,
                    )
                unpaid_cancel_sessions.append({
                    "session_id": s["session_id"],
                    "client_id": s["client_id"],
                    "coach_id": s["coach_id"],
                    "client_name": s.get("client_name"),
                    "google_event_id": s.get("google_event_id"),
                    "scheduled_start": s["scheduled_at"],
                    "scheduled_end": s.get("scheduled_end"),
                    "cancellation_reason": (
                        "Payment was not received before the 24-hour deadline."
                    ),
                })

            try:
                from app.services.session_booking_billing import EXPIRE_STALE_NO_SHOW_SQL
                await conn.execute(EXPIRE_STALE_NO_SHOW_SQL)
            except Exception as e:
                logger.warning("SessionPaymentAgent: expire-stale no_show skipped: %s", e)

            # 48-hour session reminders (Phase 7)
            reminder_48h_start = now + timedelta(hours=47)
            reminder_48h_end = now + timedelta(hours=49)
            upcoming_48h = await conn.fetch(
                f"""SELECT cs.id, cs.session_id, cs.coach_id, cs.client_id,
                          {_APPT_TIME} AS scheduled_at,
                          cs.scheduled_end, cs.zoom_link, cs.zoom_host_url,
                          cs.payment_status,
                          u.profile_data->>'name' as client_name,
                          u.profile_data->>'email' as client_email,
                          u.profile_data->>'phone' as client_phone,
                          u.profile_data->>'timezone' as client_timezone,
                          cu.profile_data->>'name' as coach_name,
                          cu.profile_data->>'email' as coach_email,
                          cu.profile_data->>'timezone' as coach_timezone
                   FROM coaching_sessions cs
                   LEFT JOIN users u ON u.id::text = cs.client_id::text
                      OR u.hardware_id = cs.client_id::text
                   LEFT JOIN users cu ON cu.id::text = cs.coach_id::text
                      OR cu.hardware_id = cs.coach_id::text
                   WHERE {_APPT_TIME} BETWEEN $1 AND $2
                   AND {_NOT_CANCELLED}""",
                reminder_48h_start, reminder_48h_end,
            )

            for s in upcoming_48h:
                await self._send_48h_reminder(conn, s)
                reminded += 1

            # Backfill tap-to-confirm for sessions that missed the 47-49h window
            # (agent down, or old 48h email with no token).
            try:
                pending_confirm = await conn.fetch(
                    f"""SELECT cs.id, cs.session_id, cs.coach_id, cs.client_id,
                              {_APPT_TIME} AS scheduled_at,
                              cs.scheduled_end, cs.zoom_link, cs.zoom_host_url,
                              cs.payment_status,
                              u.profile_data->>'name' as client_name,
                              u.profile_data->>'email' as client_email,
                              u.profile_data->>'timezone' as client_timezone,
                              cu.profile_data->>'name' as coach_name,
                              cu.profile_data->>'email' as coach_email
                       FROM coaching_sessions cs
                       LEFT JOIN users u ON u.id::text = cs.client_id::text
                          OR u.hardware_id = cs.client_id::text
                       LEFT JOIN users cu ON cu.id::text = cs.coach_id::text
                          OR cu.hardware_id = cs.coach_id::text
                       WHERE {_APPT_TIME} BETWEEN $1 AND $2
                       AND {_NOT_CANCELLED}
                       AND cs.client_confirmed_at IS NULL
                       AND cs.confirm_token_hash IS NULL""",
                    now + timedelta(hours=12), now + timedelta(hours=72),
                )
                for s in pending_confirm:
                    await self._send_48h_reminder(conn, s, notif_type="confirm_request_48h")
            except Exception as e:
                logger.warning("SessionPaymentAgent: confirm-token backfill skipped: %s", e)

            # Confirmation notifications for newly paid sessions
            newly_paid = await conn.fetch(
                f"""SELECT cs.id, cs.session_id, cs.client_id, cs.coach_id,
                          {_APPT_TIME} AS scheduled_at,
                          cs.scheduled_end, cs.zoom_link, cs.zoom_host_url,
                          u.profile_data->>'name' as client_name,
                          u.profile_data->>'email' as client_email,
                          u.profile_data->>'timezone' as client_timezone,
                          cu.profile_data->>'email' as coach_email,
                          cu.profile_data->>'name' as coach_name,
                          cu.profile_data->>'timezone' as coach_timezone
                   FROM coaching_sessions cs
                   LEFT JOIN users u ON u.id::text = cs.client_id::text
                      OR u.hardware_id = cs.client_id::text
                   LEFT JOIN users cu ON cu.id::text = cs.coach_id::text
                      OR cu.hardware_id = cs.coach_id::text
                   WHERE cs.payment_status = 'paid'
                   AND {_NOT_CANCELLED}
                   AND {_APPT_TIME} > NOW()
                   AND NOT EXISTS (
                       SELECT 1 FROM session_notifications sn
                       WHERE sn.session_id = cs.id AND sn.notification_type = 'confirmation'
                   )""",
            )

            for s in newly_paid:
                await self._send_confirmation(conn, s)

            try:
                await self._issue_unpaid_session_invoices(conn)
            except Exception as e:
                logger.warning("SessionPaymentAgent: unpaid session invoices skipped: %s", e)

            if charged or reminded or cancelled:
                logger.info(
                    "SessionPaymentAgent: cycle complete — %d charged, %d reminded, %d cancelled",
                    charged, reminded, cancelled,
                )

        for sess in unpaid_cancel_sessions:
            notify_sys = (
                getattr(self.app_state, "notification_system", None)
                if self.app_state
                else None
            )
            try:
                from app.services.session_approval import (
                    notify_client_of_coach_cancel,
                    notify_coach_of_client_cancel,
                )
                await notify_client_of_coach_cancel(
                    self.db_pool,
                    sess,
                    notification_system=notify_sys,
                    template="session_cancelled_unpaid",
                    sms_body=(
                        "Sanctuary: your session was cancelled because payment "
                        "was not received before the 24-hour deadline. "
                        "Open Schedule to book a new time."
                    ),
                )
                await notify_coach_of_client_cancel(
                    self.db_pool, sess, notification_system=notify_sys,
                )
            except Exception as e:
                logger.warning(
                    "SessionPaymentAgent: unpaid cancel notify failed sid=%s: %s",
                    sess.get("session_id"),
                    e,
                )
            try:
                from app.services.google_calendar_session_sync import (
                    sync_session_for_participants as _gcal_del,
                )
                await _gcal_del(self.db_pool, sess, action="delete")
            except Exception as e:
                logger.warning(
                    "SessionPaymentAgent: unpaid GCal delete failed sid=%s: %s",
                    sess.get("session_id"),
                    e,
                )

        try:
            from app.services.session_invoice_ledger import remind_open_stripe_invoices

            notify = getattr(self.app_state, "notification_system", None) if self.app_state else None
            n = await remind_open_stripe_invoices(self.db_pool, notify)
            if n:
                logger.info("SessionPaymentAgent: sent %d unpaid-invoice reminders", n)
        except Exception as e:
            logger.warning("SessionPaymentAgent: invoice dunning skipped: %s", e)

        try:
            from app.services.session_collect_later import run_collect_later_cycle

            n = await run_collect_later_cycle(self.db_pool, self.app_state)
            if n:
                logger.info("SessionPaymentAgent: collect-later cycle actions=%d", n)
        except Exception as e:
            logger.warning("SessionPaymentAgent: collect-later cycle skipped: %s", e)

        try:
            from app.services.session_invoice_repay import heal_open_session_invoices

            n = await heal_open_session_invoices(self.db_pool)
            if n:
                logger.info("SessionPaymentAgent: healed %d open session invoices", n)
        except Exception as e:
            logger.warning("SessionPaymentAgent: open-invoice heal skipped: %s", e)

        try:
            from app.services.payment_method_notices import run_payment_method_notice_cycle

            n = await run_payment_method_notice_cycle(self.db_pool, self.app_state)
            if n:
                logger.info("SessionPaymentAgent: payment-method notices=%d", n)
        except Exception as e:
            logger.warning("SessionPaymentAgent: payment-method notices skipped: %s", e)

    async def _issue_unpaid_session_invoices(self, conn):
        """Capture unpaid priced sessions as Stripe send_invoice (no second charge)."""
        rows = await conn.fetch(
            f"""SELECT cs.id, cs.session_id AS session_id_str, cs.price_cents,
                       cs.session_data, cs.payment_status, cs.coach_id,
                       COALESCE(NULLIF(u.stripe_customer_id, ''),
                                u.profile_data->>'stripe_customer_id') as stripe_customer_id,
                       u.profile_data->>'email' as client_email,
                       u.profile_data->>'name' as client_name
                  FROM coaching_sessions cs
                  LEFT JOIN users u ON u.hardware_id = cs.client_id::text
                     OR u.id::text = cs.client_id::text
                 WHERE cs.payment_status = 'pending'
                   AND COALESCE(cs.price_cents, 0) > 0
                   AND COALESCE(cs.stripe_payment_intent_id, '') = ''
                   AND COALESCE(cs.session_data->>'stripe_invoice_id', '') = ''
                   AND {_NOT_CANCELLED}
                   AND {_APPT_TIME} < NOW()
                 LIMIT 25"""
        )
        for session in rows:
            amount = int(session["price_cents"] or 0)
            await self._ensure_open_invoice(conn, session, amount)

    async def _ensure_open_invoice(self, conn, session, amount_cents: int):
        """Create one Stripe send_invoice for a pending session. Idempotent."""
        data = session.get("session_data") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data) if data else {}
            except Exception:
                data = {}
        if isinstance(data, dict) and data.get("stripe_invoice_id"):
            return
        customer = (session.get("stripe_customer_id") or "").strip()
        sid = session.get("session_id_str") or str(session.get("id") or "")
        if not customer or amount_cents <= 0:
            return
        import stripe
        from app.services.session_invoice_ledger import (
            create_open_session_invoice,
            persist_session_invoice,
        )

        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        if not stripe.api_key:
            return
        try:
            inv = create_open_session_invoice(
                customer_id=customer,
                amount_cents=amount_cents,
                session_id_str=sid,
                description=f"Coaching session {sid}",
            )
            if not inv:
                return
            await persist_session_invoice(conn, session["id"], inv)
            hosted = getattr(inv, "hosted_invoice_url", None) or ""
            email = (session.get("client_email") or "").strip()
            notify = getattr(self.app_state, "notification_system", None) if self.app_state else None
            if email and notify and hasattr(notify, "_send_email"):
                name = session.get("client_name") or "there"
                await notify._send_email(
                    email,
                    "Invoice for unpaid coaching session",
                    f"<p>Hello {name},</p>"
                    f"<p>An invoice for ${amount_cents / 100:.2f} is ready for session {sid}.</p>"
                    "<p>This is not an extra charge — it is the session fee that was not "
                    "collected automatically. Pay from Billing → Invoices or this link:</p>"
                    f"<p><a href=\"{hosted}\">Pay invoice</a></p>"
                    "<p>We will remind you every 7 days until this is paid.</p>"
                    "<p>Sovereign Sanctuary</p>",
                )
            await self._log_event(
                conn, session["id"], "invoice_issued", amount_cents,
                stripe_id=inv.id, note=hosted,
            )
        except Exception as e:
            logger.warning(
                "SessionPaymentAgent: invoice issue failed sid=%s: %s",
                sid, e,
            )

    def _queue_pm_blocked(self, session, reason: str) -> None:
        try:
            from app.services.payment_method_notices import notify_payment_blocked
            asyncio.create_task(notify_payment_blocked(
                self.db_pool, self.app_state,
                user_key=str(session.get("client_id") or ""),
                reason=(reason or "")[:200],
            ))
        except Exception:
            pass

    async def _reconcile_existing_intent(self, conn, session, intent, amount_cents: int) -> None:
        """Stripe already holds a succeeded PaymentIntent for this session but our row
        says pending — repair the row instead of charging again."""
        session_id = session["id"]
        pi_id = str(getattr(intent, "id", None) or (intent.get("id") if isinstance(intent, dict) else "") or "")
        try:
            pi_amount = int(getattr(intent, "amount", None) or (intent.get("amount") if isinstance(intent, dict) else 0) or amount_cents)
        except (TypeError, ValueError):
            pi_amount = amount_cents
        latest_charge = getattr(intent, "latest_charge", None) or (intent.get("latest_charge") if isinstance(intent, dict) else None)
        charge_id = latest_charge if isinstance(latest_charge, str) else getattr(latest_charge, "id", None)
        logger.error(
            "SessionPaymentAgent: %s already collected in Stripe (%s) but row was pending — "
            "reconciling, NOT charging again",
            session.get("session_id_str"), pi_id,
        )
        await conn.execute(
            """UPDATE coaching_sessions
                  SET payment_status = 'paid',
                      payment_amount_cents = COALESCE(payment_amount_cents, $2),
                      stripe_payment_intent_id = $3,
                      session_data = (COALESCE(session_data, '{}'::jsonb) - 'charge_claim_at')
                                     || jsonb_build_object('billing_obligation', 'collected',
                                                           'stripe_payment_intent_id', $3::text,
                                                           'reconciled_from_stripe_at', NOW()::text),
                      updated_at = NOW()
                WHERE id = $1""",
            session_id, pi_amount, pi_id,
        )
        await self._log_event(
            conn, session_id, "charge_reconciled", pi_amount, stripe_id=pi_id,
            note="row said pending; Stripe already succeeded — duplicate charge prevented",
        )
        await record_payment_history(
            conn,
            client_key=str(session.get("client_id") or ""),
            intent_id=pi_id,
            charge_id=charge_id,
            amount_cents=pi_amount,
            receipt_url=None,
            metadata={"session_id": session.get("session_id_str"), "session_uuid": str(session_id),
                      "coach_id": str(session.get("coach_id") or ""),
                      "source": "session_payment_agent.reconcile"},
        )

    async def _charge_card(self, conn, session, stripe_customer_id: str, amount_cents: int) -> Optional[bool]:
        """Charge client default PM; Connect destination + app fee when coach linked; receipt email.

        Returns True when charged, False when the card could not be charged (caller
        sends reminder + invoice), None when the session is already collected or
        collection cannot be verified (caller must do nothing — never remind,
        never invoice, never charge).
        """
        session_id = session["id"]
        session_id_str = session.get("session_id_str") or str(session_id)
        pm_id = ""
        claimed = False
        try:
            import stripe
            from app.services.session_financial_records import (
                platform_fee_cents_from_session,
                mark_coach_ledger_collected,
            )

            stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

            if not stripe.api_key:
                logger.warning("SessionPaymentAgent: STRIPE_SECRET_KEY not set")
                return False

            # Guard 1 — fresh DB truth (payment_status / PI id / obligation / ledger).
            state = await collection_state(conn, session_id)
            reason = collected_reason(state)
            if reason:
                await self._log_event(conn, session_id, "charge_skipped", amount_cents,
                                      note=f"already collected: {reason}")
                return None

            # Guard 2 — Stripe truth, independent of our DB. Fail closed.
            try:
                existing = await asyncio.to_thread(
                    stripe_existing_charge, stripe, session_id, session_id_str
                )
            except Exception as se:
                logger.error(
                    "SessionPaymentAgent: cannot verify Stripe for %s (%s) — skipping this cycle",
                    session_id_str, se,
                )
                await self._log_event(conn, session_id, "charge_skipped", amount_cents,
                                      note=f"stripe verification failed: {se}")
                return None
            if existing is not None:
                await self._reconcile_existing_intent(conn, session, existing, amount_cents)
                return None

            pm_id = ""
            try:
                from app.services.session_pm_sync import sync_default_pm_from_stripe
                pm_id = await sync_default_pm_from_stripe(
                    self.db_pool,
                    user_key=str(session.get("client_id") or ""),
                    customer_id=stripe_customer_id,
                )
            except Exception:
                pm_id = ""
            if not pm_id:
                try:
                    cu = stripe.Customer.retrieve(stripe_customer_id)
                    inv = getattr(cu, "invoice_settings", None)
                    pm_id = (
                        (inv.get("default_payment_method") if isinstance(inv, dict)
                         else getattr(inv, "default_payment_method", None))
                        or ""
                    )
                    if pm_id and not isinstance(pm_id, str):
                        pm_id = getattr(pm_id, "id", "") or ""
                except Exception:
                    pm_id = ""
            if not pm_id:
                pm_id = (session.get("client_default_pm") or "").strip()
            if not pm_id:
                payment_methods = stripe.PaymentMethod.list(
                    customer=stripe_customer_id, type="card", limit=1
                )
                if not payment_methods.data:
                    await self._log_event(
                        conn, session_id, "charge_failed", amount_cents, error="No card on file"
                    )
                    self._queue_pm_blocked(session, "No card on file")
                    return False
                pm_id = payment_methods.data[0].id

            sd = session.get("session_data") or {}
            if isinstance(sd, str):
                try:
                    sd = json.loads(sd) if sd else {}
                except Exception:
                    sd = {}
            blocked_pm = str((sd or {}).get("charge_blocked_pm") or "").strip()
            if blocked_pm and pm_id and blocked_pm == pm_id:
                await self._log_event(
                    conn, session_id, "charge_skipped", amount_cents,
                    error="Same declined card — waiting for a new payment method",
                )
                return False

            connect_id = (session.get("coach_connect_id") or "").strip()
            app_fee = platform_fee_cents_from_session(session, amount_cents)
            if app_fee >= amount_cents:
                app_fee = max(0, amount_cents - 1)

            pi_kwargs = {
                "amount": amount_cents,
                "currency": "usd",
                "customer": stripe_customer_id,
                "payment_method": pm_id,
                "off_session": True,
                "confirm": True,
                "metadata": {
                    "session_id": session_id_str,
                    "session_uuid": str(session_id),
                    "type": "session_payment",
                    "coach_id": str(session.get("coach_id") or ""),
                    "platform_fee_cents": str(app_fee),
                },
            }
            client_email = (session.get("client_email") or "").strip()
            if client_email:
                pi_kwargs["receipt_email"] = client_email

            # Destination charge: coach Connect gets net; platform keeps application_fee
            if connect_id:
                pi_kwargs["application_fee_amount"] = app_fee
                pi_kwargs["transfer_data"] = {"destination": connect_id}

            # Guard 3 — atomic claim: only one caller per session can reach Stripe.
            claimed = await claim_charge(conn, session_id)
            if not claimed:
                await self._log_event(conn, session_id, "charge_skipped", amount_cents,
                                      note="charge claim not won — in flight elsewhere or already collected")
                return None

            # Guard 4 — Stripe idempotency: a retry can never mint a second PaymentIntent.
            intent = stripe.PaymentIntent.create(
                **pi_kwargs,
                idempotency_key=idempotency_key(session_id, amount_cents, pm_id),
            )

            if intent.status == "succeeded":
                receipt_url = None
                try:
                    if intent.latest_charge:
                        ch = stripe.Charge.retrieve(intent.latest_charge)
                        receipt_url = getattr(ch, "receipt_url", None)
                except Exception:
                    pass

                await conn.execute(
                    """UPDATE coaching_sessions
                       SET payment_status = 'paid', payment_amount_cents = $1,
                           stripe_payment_intent_id = $2,
                           session_data = (COALESCE(session_data, '{}'::jsonb) - 'charge_claim_at')
                                          || $4::jsonb,
                           updated_at = NOW()
                       WHERE id = $3""",
                    amount_cents,
                    intent.id,
                    session_id,
                    json.dumps(
                        {
                            "billing_obligation": "collected",
                            "stripe_payment_intent_id": intent.id,
                            "receipt_url": receipt_url,
                            "application_fee_cents": app_fee if connect_id else 0,
                            "connect_destination": connect_id or None,
                            "charged_payment_method_id": pm_id,
                        }
                    ),
                )
                await self._log_event(
                    conn,
                    session_id,
                    "charge_succeeded",
                    amount_cents,
                    stripe_id=intent.id,
                    note=(
                        f"receipt={receipt_url or 'pending'};"
                        f"pm={pm_id};connect={connect_id or 'none'};fee={app_fee}"
                    ),
                )
                if receipt_url:
                    await self._log_event(
                        conn,
                        session_id,
                        "receipt_issued",
                        amount_cents,
                        stripe_id=intent.id,
                        note=receipt_url,
                    )
                try:
                    await mark_coach_ledger_collected(
                        self.db_pool,
                        coach_id=str(session.get("coach_id") or ""),
                        session_id=session_id_str,
                        stripe_payment_intent_id=intent.id,
                        amount_cents=amount_cents,
                        receipt_url=receipt_url,
                    )
                except Exception as le:
                    logger.warning("SessionPaymentAgent: ledger collected update failed: %s", le)
                # Billing → History mirror (payment_history) so the charge is visible
                # everywhere refunds/receipts are reviewed.
                latest_charge = getattr(intent, "latest_charge", None)
                await record_payment_history(
                    conn,
                    client_key=str(session.get("client_id") or ""),
                    intent_id=intent.id,
                    charge_id=latest_charge if isinstance(latest_charge, str) else getattr(latest_charge, "id", None),
                    amount_cents=amount_cents,
                    receipt_url=receipt_url,
                    metadata={"session_id": session_id_str, "session_uuid": str(session_id),
                              "coach_id": str(session.get("coach_id") or ""),
                              "application_fee_cents": app_fee if connect_id else 0,
                              "source": "session_payment_agent"},
                )
                return True
            else:
                await release_claim(conn, session_id)
                await self._log_event(
                    conn, session_id, "charge_failed", amount_cents,
                    stripe_id=getattr(intent, "id", None),
                    error=f"Status: {intent.status}",
                )
                self._queue_pm_blocked(session, f"Status: {intent.status}")
                return False

        except Exception as e:
            logger.warning(
                "SessionPaymentAgent: Stripe charge failed for session %s: %s",
                session_id, e,
            )
            if claimed:
                await release_claim(conn, session_id)
            await self._log_event(conn, session_id, "charge_failed", amount_cents, error=str(e))
            self._queue_pm_blocked(session, str(e))
            try:
                fail_pm = ""
                try:
                    fail_pm = pm_id
                except Exception:
                    fail_pm = ""
                if fail_pm:
                    await conn.execute(
                        """UPDATE coaching_sessions
                              SET session_data = COALESCE(session_data, '{}'::jsonb)
                                || jsonb_build_object('charge_blocked_pm', $2::text),
                                  updated_at = NOW()
                            WHERE id = $1""",
                        session_id,
                        fail_pm,
                    )
            except Exception:
                pass
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
                when_str = _format_scheduled_for_session(session)
                subject = "Payment Due — Upcoming Session"
                body = f"""<p>Hello {client_name},</p>
<p>Your coaching session is scheduled for <strong>{when_str}</strong>.</p>
<p>Payment of ${amount_cents / 100:.2f} is due at least <strong>24 hours before</strong>
the session. Pay now on <strong>Billing → Invoices</strong>, or your default card
is charged in the 72 hours leading up to the appointment.</p>
<p>If payment is not received 24 hours before the start, the session is cancelled
and that non-payment is your consent to cancel so the slot can be filled.</p>
<p>To update a card or bank: log in → <strong>Settings → Payments</strong>
(coach-only: the Settings tab). Use Update Card or Update Bank, then tap the star
so it is the default.</p>
<p><a href="https://app.sovereignsanctuary.net">Open Sovereign Sanctuary</a></p>
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

    async def _send_48h_reminder(self, conn, session, notif_type: str = "reminder_48h"):
        """Send 48-hour session reminder with a tap-to-confirm token."""
        session_id = session["id"]
        already = await conn.fetchval(
            """SELECT EXISTS(SELECT 1 FROM session_notifications
               WHERE session_id = $1 AND notification_type = $2)""",
            session_id, notif_type,
        )
        if already:
            return

        notify = getattr(self.app_state, "notification_system", None) if self.app_state else None
        client_email = session["client_email"]
        client_name = session["client_name"] or "Client"
        session_date = _format_scheduled_for_session(session)
        payment_status = session["payment_status"] or "pending"
        confirm_url = ""
        try:
            from app.services.session_confirm import confirm_url as _confirm_url, issue_confirm_token
            raw = await issue_confirm_token(conn, session_id, session.get("scheduled_at"))
            if raw:
                confirm_url = _confirm_url(raw)
        except Exception as e:
            logger.warning("SessionPaymentAgent: confirm token mint failed: %s", e)

        if client_email and notify and hasattr(notify, "_send_email"):
            try:
                payment_note = ""
                if payment_status != "paid":
                    payment_note = (
                        "<p>Your card on file is still charged about 24 hours before "
                        "the session. The session is cancelled only if that charge "
                        "does not succeed.</p>"
                        "<p>Pay now on Billing → Invoices, or update the card under "
                        "Settings → Payments and tap the star so it is the default.</p>"
                    )
                confirm_note = ""
                if confirm_url:
                    confirm_note = (
                        "<p style='text-align:center;margin:24px 0;'>"
                        f"<a href='{confirm_url}' style='display:inline-block;background:#C9A962;"
                        "color:#050505;font-weight:bold;padding:12px 28px;border-radius:6px;"
                        "text-decoration:none;'>Confirm this appointment</a></p>"
                        "<p>Tap the gold button to confirm you will attend. This is not a charge. "
                        "The link is unique to this session.</p>"
                    )
                else:
                    confirm_note = (
                        "<p><strong>Please confirm this appointment</strong> from Schedule "
                        "in the app if the button is missing.</p>"
                    )

                from app.services.calendar_invite import html_cta_fragment, invite_from_session

                invite = invite_from_session(session, coach_name=session.get("coach_name") or "your coach")
                subject = (
                    "Please confirm your session"
                    if notif_type == "confirm_request_48h"
                    else "Session Reminder — 48 Hours"
                )
                body = f"""<p>Hello {client_name},</p>
<p>This is a reminder that your coaching session is scheduled for <strong>{session_date}</strong>.</p>
{confirm_note}
{payment_note}
<p><strong>Cancellation policy:</strong> Cancel 24 hours or more before the session to void the invoice / receive a refund. Cancel inside 24 hours and payment is still due because that slot cannot be filled.</p>
{html_cta_fragment(invite, include_join=True)}
<p>See you soon!<br>Sovereign Sanctuary</p>"""

                await notify._send_email(client_email, subject, body)
                await conn.execute(
                    """INSERT INTO session_notifications (session_id, notification_type, channel, recipient_id)
                       VALUES ($1, $2, 'email', $3) ON CONFLICT DO NOTHING""",
                    session_id, notif_type, session["client_id"],
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
        session_date = _format_scheduled_for_session(session)
        coach_session_date = _format_scheduled_for_session(session, tz_key="coach_timezone")

        if client_email:
            try:
                from app.services.calendar_invite import html_cta_fragment, invite_from_session

                invite = invite_from_session(session, coach_name=coach_name)
                await notify._send_email(
                    client_email,
                    "Session Confirmed — Payment Received",
                    f"""<p>Hello {client_name},</p>
<p>Your payment has been received. Your session on <strong>{session_date}</strong> is confirmed.</p>
{html_cta_fragment(invite, include_join=True)}
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
<p>Payment received for your session with <strong>{client_name}</strong> on <strong>{coach_session_date}</strong>.</p>
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
        """Log a payment event.

        session_payment_events.event_type is a closed CHECK list. charge_skipped
        is not on it — remap so a failed Stripe verify is visible to ops.
        """
        allowed = {
            "charge_attempted", "charge_succeeded", "charge_failed", "refund",
            "cancellation", "reminder_sent", "test_charge_simulated",
            "obligation_created", "receipt_issued",
        }
        stored_type = event_type if event_type in allowed else "charge_failed"
        stored_error = error
        if stored_type != event_type:
            stored_error = f"{event_type}: {error or note or ''}"[:180]
        try:
            await conn.execute(
                """INSERT INTO session_payment_events (session_id, event_type, amount_cents,
                      stripe_payment_intent_id, error_message, metadata)
                   VALUES ($1, $2, $3, $4, $5, $6::jsonb)""",
                session_id, stored_type, amount_cents, stripe_id, stored_error,
                json.dumps({"note": str(note or "")[:1000], "requested_type": event_type}),
            )
        except Exception as e:
            logger.warning("SessionPaymentAgent: failed to log event: %s", e)
