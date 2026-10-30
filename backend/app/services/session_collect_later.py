"""Coach collect-later override for live sessions.

Coach Command SCHEDULE → Create Session toggle stamps the session so the
24h unpaid sweeper will not cancel it. Stripe records a send_invoice due
on the session day. After the session, the client is emailed to pay and
update their payment method (24h after end, then every 3 days). Balances
past 30 days pause membership until the method is updated and invoices
are collected.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.session_collect_later")

NOTICE_AFTER_COMPLETE_HOURS = 24
NUDGE_INTERVAL_DAYS = 3
PAUSE_AFTER_DUE_DAYS = 30


def is_collect_later(data: Any) -> bool:
    if isinstance(data, str):
        try:
            data = json.loads(data) if data else {}
        except Exception:
            data = {}
    if not isinstance(data, dict):
        return False
    v = data.get("collect_later")
    return v is True or str(v or "").lower() in ("true", "1", "yes")


def collect_later_sql_skip(alias: str = "session_data") -> str:
    """SQL fragment: true rows are coach-overridden and must not auto-cancel."""
    col = f"{alias}" if "." not in alias else alias
    return (
        f"COALESCE({col}->>'collect_later', '') NOT IN ('true','1','yes')"
    )


def invoice_due_unix(session_start: datetime, now: Optional[datetime] = None) -> int:
    """Due end of session calendar day UTC; never in the past (Stripe rejects that)."""
    now = now or datetime.now(timezone.utc)
    if session_start.tzinfo is None:
        session_start = session_start.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    due = datetime(
        session_start.year, session_start.month, session_start.day,
        23, 59, tzinfo=timezone.utc,
    )
    if due <= now:
        due = now + timedelta(hours=1)
    return int(due.timestamp())


def should_send_complete_notice(
    session_end: Optional[datetime],
    notice_at: Any,
    now: Optional[datetime] = None,
) -> bool:
    now = now or datetime.now(timezone.utc)
    if notice_at or not session_end:
        return False
    if session_end.tzinfo is None:
        session_end = session_end.replace(tzinfo=timezone.utc)
    return now >= session_end + timedelta(hours=NOTICE_AFTER_COMPLETE_HOURS)


def should_send_pm_nudge(
    last_nudge_at: Any,
    complete_notice_sent: bool,
    now: Optional[datetime] = None,
) -> bool:
    if not complete_notice_sent:
        return False
    now = now or datetime.now(timezone.utc)
    if last_nudge_at is None:
        return True
    dt = last_nudge_at
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return True
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt) >= timedelta(days=NUDGE_INTERVAL_DAYS)


def should_pause_membership(
    due_unix: Optional[int],
    already_paused: bool,
    now: Optional[datetime] = None,
) -> bool:
    if already_paused or not due_unix:
        return False
    now = now or datetime.now(timezone.utc)
    due = datetime.fromtimestamp(int(due_unix), tz=timezone.utc)
    return now >= due + timedelta(days=PAUSE_AFTER_DUE_DAYS)


def _parse_dt(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _session_data(row: Dict[str, Any]) -> Dict[str, Any]:
    data = row.get("session_data") or {}
    if isinstance(data, str):
        try:
            data = json.loads(data) if data else {}
        except Exception:
            data = {}
    return data if isinstance(data, dict) else {}


async def client_booking_paused(db, client_id: str) -> bool:
    """True when a 30-day collect-later hold is open (table is source of truth)."""
    if not db or not client_id:
        return False
    sql = """SELECT 1 FROM session_billing_holds
              WHERE user_id = $1 AND released_at IS NULL LIMIT 1"""
    try:
        if hasattr(db, "acquire"):
            async with db.acquire() as conn:
                row = await conn.fetchrow(sql, client_id)
        else:
            row = await db.fetchrow(sql, client_id)
        return bool(row)
    except Exception as e:
        logger.warning("client_booking_paused: %s", e)
        return False


async def _resolve_stripe_customer(conn, client_id: str) -> Optional[str]:
    row = await conn.fetchrow(
        """SELECT stripe_customer_id,
                  profile_data->>'stripe_customer_id' AS cid,
                  profile_data->>'email' AS email,
                  profile_data->>'name' AS name,
                  username, hardware_id
             FROM users
            WHERE hardware_id = $1 OR username = $1
            LIMIT 1""",
        client_id,
    )
    if not row:
        return None
    cid = (row["stripe_customer_id"] or row["cid"] or "").strip()
    if cid:
        return cid
    email = (row["email"] or "").strip()
    if not email:
        return None
    try:
        import stripe

        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        if not stripe.api_key:
            return None
        found = stripe.Customer.list(email=email, limit=1)
        if found.data:
            cid = found.data[0].id
        else:
            cust = stripe.Customer.create(
                email=email,
                name=(row["name"] or row["username"] or "")[:80],
                metadata={"collect_later": "true", "username": row["username"] or ""},
            )
            cid = cust.id
        await conn.execute(
            """UPDATE users
                  SET stripe_customer_id = COALESCE(NULLIF(stripe_customer_id, ''), $2)
                WHERE hardware_id = $1 OR username = $1""",
            client_id,
            cid,
        )
        return cid
    except Exception as e:
        logger.warning("collect_later customer create failed: %s", e)
        return None


async def issue_collect_later_invoice(db, session: Dict[str, Any], actor: str = "") -> Optional[str]:
    """Stamp collect_later and open a Stripe send_invoice due on the session day."""
    if not db or not session:
        return None
    sid = str(session.get("session_id") or "")
    amount = int(session.get("price_cents") or 0)
    client_id = str(session.get("client_id") or "")
    start = _parse_dt(session.get("scheduled_start"))
    session["collect_later"] = True
    session["collect_later_by"] = actor or session.get("coach_id") or ""
    if start:
        session["invoice_due_on"] = start.date().isoformat()
        session["invoice_due_unix"] = invoice_due_unix(start)
    if amount <= 0 or not sid:
        return None
    try:
        async with db.acquire() as conn:
            customer = await _resolve_stripe_customer(conn, client_id)
            if not customer:
                logger.warning("collect_later: no Stripe customer for %s", client_id)
                return None
            from app.services.session_invoice_ledger import (
                create_open_session_invoice,
                persist_session_invoice,
            )

            due_unix = int(session.get("invoice_due_unix") or invoice_due_unix(start or datetime.now(timezone.utc)))
            inv = create_open_session_invoice(
                customer_id=customer,
                amount_cents=amount,
                session_id_str=sid,
                description=f"Live coaching session {sid} (collect later)",
                due_date=due_unix,
                extra_metadata={"collect_later": "true"},
            )
            if not inv:
                return None
            row = await conn.fetchrow(
                "SELECT id FROM coaching_sessions WHERE session_id = $1", sid,
            )
            extra = {
                "collect_later": True,
                "collect_later_by": session.get("collect_later_by"),
                "invoice_due_on": session.get("invoice_due_on"),
                "invoice_due_unix": due_unix,
            }
            if row:
                await persist_session_invoice(conn, row["id"], inv, extra=extra)
            session["stripe_invoice_id"] = inv.id
            session["hosted_invoice_url"] = getattr(inv, "hosted_invoice_url", None)
            return inv.id
    except Exception as e:
        logger.warning("issue_collect_later_invoice %s: %s", sid, e)
        return None


async def _send_tpl(email: str, template: str, context: Dict[str, Any]) -> None:
    if not email:
        return
    try:
        from app.services.notifications_service import EmailService

        await EmailService().send_email(email, template, context)
    except Exception as e:
        logger.warning("collect_later email %s: %s", template, e)


async def _customer_has_pm(customer_id: str) -> bool:
    try:
        import stripe

        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        if not stripe.api_key or not customer_id:
            return False
        cards = stripe.PaymentMethod.list(customer=customer_id, type="card", limit=1)
        if cards.data:
            return True
        banks = stripe.PaymentMethod.list(
            customer=customer_id, type="us_bank_account", limit=1,
        )
        return bool(banks.data)
    except Exception:
        return False


async def _pay_invoice(inv_id: str) -> bool:
    if not inv_id or not str(inv_id).startswith("in_"):
        return False
    try:
        import stripe

        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        if not stripe.api_key:
            return False
        inv = stripe.Invoice.pay(inv_id)
        return str(getattr(inv, "status", "") or "").lower() == "paid"
    except Exception as e:
        logger.info("collect_later Invoice.pay %s: %s", inv_id, e)
        return False


async def try_charge_overdue_for_user(db, user_id: str) -> int:
    """Pay open collect-later invoices after a payment method is attached."""
    if not db or not user_id:
        return 0
    paid = 0
    try:
        async with db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT cs.session_id, cs.session_data
                     FROM coaching_sessions cs
                    WHERE cs.client_id = $1
                      AND cs.payment_status = 'pending'
                      AND COALESCE(cs.session_data->>'collect_later','') IN ('true','1','yes')
                      AND COALESCE(cs.session_data->>'stripe_invoice_id','') <> ''""",
                user_id,
            )
            for row in rows:
                data = _session_data(dict(row))
                inv_id = str(data.get("stripe_invoice_id") or "")
                if await _pay_invoice(inv_id):
                    paid += 1
    except Exception as e:
        logger.warning("try_charge_overdue_for_user: %s", e)
    return paid


async def _pause_membership(conn, client_id: str) -> None:
    import stripe

    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    sub_id = None
    try:
        row = await conn.fetchrow(
            """SELECT COALESCE(NULLIF(u.stripe_customer_id, ''),
                               u.profile_data->>'stripe_customer_id') AS cid
                 FROM users u
                WHERE u.hardware_id = $1 OR u.username = $1
                LIMIT 1""",
            client_id,
        )
        cid = (row["cid"] if row else "") or ""
        if cid and stripe.api_key:
            subs = stripe.Subscription.list(customer=cid, status="active", limit=1)
            if subs.data:
                sub = subs.data[0]
                sub_id = sub.id
                stripe.Subscription.modify(
                    sub_id,
                    pause_collection={"behavior": "keep_as_draft"},
                )
    except Exception as e:
        logger.warning("pause_collection %s: %s", client_id, e)
    await conn.execute(
        """INSERT INTO session_billing_holds (user_id, reason, stripe_subscription_id)
           VALUES ($1, 'session_invoice_30d', $2)
           ON CONFLICT (user_id) DO UPDATE SET
             reason = 'session_invoice_30d',
             paused_at = NOW(),
             stripe_subscription_id = COALESCE(EXCLUDED.stripe_subscription_id,
                                               session_billing_holds.stripe_subscription_id),
             released_at = NULL""",
        client_id,
        sub_id,
    )


async def _release_hold_if_clear(conn, client_id: str, notify, email: str, name: str) -> bool:
    open_row = await conn.fetchrow(
        """SELECT 1 FROM coaching_sessions
            WHERE client_id = $1
              AND payment_status = 'pending'
              AND COALESCE(session_data->>'collect_later','') IN ('true','1','yes')
              AND COALESCE(price_cents, 0) > 0
            LIMIT 1""",
        client_id,
    )
    if open_row:
        return False
    hold = await conn.fetchrow(
        """SELECT stripe_subscription_id FROM session_billing_holds
            WHERE user_id = $1 AND released_at IS NULL""",
        client_id,
    )
    if hold and hold["stripe_subscription_id"]:
        try:
            import stripe

            stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
            if stripe.api_key:
                stripe.Subscription.modify(
                    hold["stripe_subscription_id"],
                    pause_collection="",
                )
        except Exception as e:
            logger.warning("unpause subscription %s: %s", client_id, e)
    await conn.execute(
        """UPDATE session_billing_holds SET released_at = NOW()
            WHERE user_id = $1 AND released_at IS NULL""",
        client_id,
    )
    if email:
        await _send_tpl(email, "session_collect_later_cleared", {"name": name})
    return True


async def _paid_followup(conn, invoice: Dict[str, Any]) -> None:
    meta = invoice.get("metadata") or {}
    row = await conn.fetchrow(
        """SELECT client_id FROM coaching_sessions
            WHERE session_id = $1
               OR session_data->>'stripe_invoice_id' = $2
            LIMIT 1""",
        (meta.get("session_id") or "").strip(),
        invoice.get("id") or "",
    )
    if not row:
        return
    client_id = row["client_id"]
    user = await conn.fetchrow(
        """SELECT profile_data->>'email' AS email,
                  profile_data->>'name' AS name
             FROM users
            WHERE hardware_id = $1 OR username = $1 LIMIT 1""",
        client_id,
    )
    email = (user["email"] if user else "") or ""
    name = (user["name"] if user else "") or "there"
    await _release_hold_if_clear(conn, client_id, None, email, name)


async def on_session_invoice_paid(db, invoice: Dict[str, Any]) -> None:
    """After Stripe invoice.paid: release 30-day hold and email if balances are clear."""
    if not db or not invoice:
        return
    try:
        if hasattr(db, "acquire"):
            async with db.acquire() as conn:
                await _paid_followup(conn, invoice)
        else:
            await _paid_followup(db, invoice)
    except Exception as e:
        logger.warning("on_session_invoice_paid: %s", e)


async def run_collect_later_cycle(db_pool, app_state=None) -> int:
    """24h-after-complete notice, 3-day PM nudges, Invoice.pay, 30-day pause."""
    if not db_pool:
        return 0
    acted = 0
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT cs.id, cs.session_id, cs.client_id, cs.coach_id,
                          cs.scheduled_start, cs.scheduled_end, cs.actual_end,
                          cs.status, cs.payment_status, cs.price_cents, cs.session_data,
                          COALESCE(NULLIF(u.stripe_customer_id, ''),
                                   u.profile_data->>'stripe_customer_id') AS stripe_customer_id,
                          u.profile_data->>'email' AS client_email,
                          u.profile_data->>'name' AS client_name,
                          u.hardware_id AS client_hw
                     FROM coaching_sessions cs
                     LEFT JOIN users u ON u.hardware_id = cs.client_id::text
                        OR u.username = cs.client_id::text
                        OR u.id::text = cs.client_id::text
                    WHERE COALESCE(cs.session_data->>'collect_later','') IN ('true','1','yes')
                      AND cs.payment_status = 'pending'
                      AND COALESCE(cs.price_cents, 0) > 0
                      AND UPPER(cs.status) NOT IN
                          ('CANCELLED','RESCHEDULED','CANCELLED_BY_GOOGLE','CANCELED')
                    LIMIT 80"""
            )
            now = datetime.now(timezone.utc)
            for rec in rows:
                row = dict(rec)
                data = _session_data(row)
                inv_id = str(data.get("stripe_invoice_id") or "")
                if not inv_id:
                    await issue_collect_later_invoice(db_pool, {
                        "session_id": row.get("session_id"),
                        "client_id": row.get("client_id"),
                        "coach_id": row.get("coach_id"),
                        "price_cents": row.get("price_cents"),
                        "scheduled_start": row.get("scheduled_start"),
                        "collect_later": True,
                    }, actor=str(row.get("coach_id") or ""))
                    acted += 1
                    continue
                hosted = str(data.get("hosted_invoice_url") or "")
                amount = int(row.get("price_cents") or 0) / 100.0
                email = (row.get("client_email") or "").strip()
                name = (row.get("client_name") or "there").strip() or "there"
                client_id = row.get("client_hw") or row.get("client_id")
                end = _parse_dt(row.get("actual_end")) or _parse_dt(row.get("scheduled_end"))
                due_unix = data.get("invoice_due_unix")
                if not due_unix:
                    start = _parse_dt(row.get("scheduled_start"))
                    due_unix = invoice_due_unix(start, now) if start else None
                paused = bool(data.get("collect_later_paused_at"))

                pay_ctx = {
                    "name": name,
                    "amount": f"{amount:.2f}",
                    "pay_url": hosted or "https://app.sovereignsanctuary.net",
                }
                if inv_id and row.get("stripe_customer_id"):
                    if await _customer_has_pm(row["stripe_customer_id"]):
                        if await _pay_invoice(inv_id):
                            from app.services.session_invoice_ledger import (
                                mark_session_paid_from_invoice,
                            )
                            await mark_session_paid_from_invoice(conn, {
                                "id": inv_id,
                                "amount_paid": int(row.get("price_cents") or 0),
                                "hosted_invoice_url": hosted,
                                "metadata": {
                                    "session_id": row.get("session_id"),
                                    "collect_later": "true",
                                },
                            })
                            await _release_hold_if_clear(
                                conn, str(client_id or ""), None, email, name,
                            )
                            acted += 1
                            continue

                if should_send_complete_notice(end, data.get("collect_later_notice_24h"), now):
                    await _send_tpl(email, "session_collect_later_24h", pay_ctx)
                    data["collect_later_notice_24h"] = now.isoformat()
                    acted += 1
                elif should_send_pm_nudge(
                    data.get("collect_later_last_nudge_at"),
                    bool(data.get("collect_later_notice_24h")),
                    now,
                ):
                    await _send_tpl(email, "session_collect_later_nudge", pay_ctx)
                    data["collect_later_last_nudge_at"] = now.isoformat()
                    acted += 1

                if should_pause_membership(due_unix, paused, now) and client_id:
                    await _pause_membership(conn, str(client_id))
                    data["collect_later_paused_at"] = now.isoformat()
                    await _send_tpl(email, "session_collect_later_paused", pay_ctx)
                    acted += 1

                await conn.execute(
                    """UPDATE coaching_sessions
                          SET session_data = COALESCE(session_data, '{}'::jsonb) || $2::jsonb,
                              updated_at = NOW()
                        WHERE id = $1""",
                    row["id"],
                    json.dumps({
                        k: data[k] for k in (
                            "collect_later_notice_24h",
                            "collect_later_last_nudge_at",
                            "collect_later_paused_at",
                        ) if data.get(k)
                    }),
                )
    except Exception as e:
        logger.warning("run_collect_later_cycle: %s", e)
    return acted
