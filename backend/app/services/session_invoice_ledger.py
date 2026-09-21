"""Session + Stripe invoice ledger — hydrate prices, open invoices, 7-day dunning.

Session fees are PaymentIntents (72h before start). Stripe Invoice objects are
subscriptions plus fallback send_invoice when off-session charge fails or a
past session stayed unpaid. Clients see both on GET /api/billing/invoices.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.services.session_booking_billing import effective_price_cents

logger = logging.getLogger("nate.session_invoice_ledger")

DUNNING_INTERVAL_DAYS = 7

HYDRATE_SESSION_PRICE_SQL = """
UPDATE coaching_sessions
   SET price_cents = GREATEST(
           COALESCE(price_cents, 0),
           COALESCE(NULLIF(session_data->>'price_cents', '')::int, 0)
       ),
       updated_at = NOW()
 WHERE payment_status = 'pending'
   AND COALESCE(price_cents, 0) = 0
   AND session_data ? 'price_cents'
   AND (session_data->>'price_cents') ~ '^[0-9]+$'
   AND COALESCE(NULLIF(session_data->>'price_cents', '')::int, 0) > 0
"""


def should_send_dunning(last_reminded_at: Any, now: Optional[datetime] = None) -> bool:
    """True when no reminder yet, or last reminder is ≥ 7 days old."""
    now = now or datetime.now(timezone.utc)
    if last_reminded_at is None:
        return True
    dt = last_reminded_at
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return True
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt) >= timedelta(days=DUNNING_INTERVAL_DAYS)


def session_row_to_invoice(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map a coaching_sessions row to the client invoice list shape."""
    data = row.get("session_data") or {}
    if isinstance(data, str):
        try:
            data = json.loads(data) if data else {}
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    cents = effective_price_cents(row.get("price_cents"), data)
    paid = str(row.get("payment_status") or "").lower() == "paid"
    amount = (row.get("payment_amount_cents") or cents or 0) / 100.0
    created = row.get("scheduled_start") or row.get("created_at")
    if hasattr(created, "isoformat"):
        created = created.isoformat()
    hosted = data.get("hosted_invoice_url") or data.get("receipt_url")
    return {
        "id": data.get("stripe_invoice_id") or row.get("stripe_payment_intent_id")
        or row.get("session_id"),
        "kind": "session_charge" if paid else "session_pending",
        "session_id": row.get("session_id"),
        "amount_due": 0 if paid else amount,
        "amount_paid": amount if paid else 0,
        "currency": "usd",
        "status": "paid" if paid else "open",
        "created": created,
        "pdf_url": data.get("invoice_pdf") or data.get("receipt_url"),
        "hosted_url": hosted,
        "period_start": created,
        "period_end": None,
        "description": f"Coaching session {row.get('session_id') or ''}".strip(),
    }


def merge_invoice_lists(
    stripe_invoices: List[Dict[str, Any]],
    session_invoices: List[Dict[str, Any]],
    limit: int = 40,
) -> List[Dict[str, Any]]:
    """Stripe subscription invoices first, then session rows not already listed."""
    seen = {str(i.get("id") or "") for i in stripe_invoices}
    out = list(stripe_invoices)
    for item in session_invoices:
        iid = str(item.get("id") or "")
        sid = str(item.get("session_id") or "")
        if iid and iid in seen:
            continue
        if sid and any(str(x.get("session_id") or "") == sid for x in out):
            continue
        out.append(item)
        if iid:
            seen.add(iid)
    def _key(inv: Dict[str, Any]):
        return str(inv.get("created") or "")
    out.sort(key=_key, reverse=True)
    return out[:limit]


def _stripe_inv_dict(inv) -> Dict[str, Any]:
    created = getattr(inv, "created", None)
    created_iso = (
        datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
        if created
        else None
    )
    period_start = getattr(inv, "period_start", None)
    period_end = getattr(inv, "period_end", None)
    meta = getattr(inv, "metadata", None) or {}
    if hasattr(meta, "to_dict"):
        meta = meta.to_dict()
    return {
        "id": inv.id,
        "kind": "stripe_invoice",
        "session_id": (meta.get("session_id") if isinstance(meta, dict) else None),
        "amount_due": (getattr(inv, "amount_due", 0) or 0) / 100,
        "amount_paid": (getattr(inv, "amount_paid", 0) or 0) / 100,
        "currency": getattr(inv, "currency", "usd"),
        "status": getattr(inv, "status", None),
        "created": created_iso,
        "pdf_url": getattr(inv, "invoice_pdf", None),
        "hosted_url": getattr(inv, "hosted_invoice_url", None),
        "period_start": (
            datetime.fromtimestamp(period_start, tz=timezone.utc).isoformat()
            if period_start
            else None
        ),
        "period_end": (
            datetime.fromtimestamp(period_end, tz=timezone.utc).isoformat()
            if period_end
            else None
        ),
        "description": getattr(inv, "description", None) or "Stripe invoice",
    }


async def load_session_invoices(conn, hardware_id: str, limit: int = 40) -> List[Dict[str, Any]]:
    if not hardware_id:
        return []
    rows = await conn.fetch(
        """SELECT session_id, payment_status, price_cents, payment_amount_cents,
                  stripe_payment_intent_id, session_data, scheduled_start, created_at
             FROM coaching_sessions
            WHERE client_id = $1
              AND (
                    COALESCE(price_cents, 0) > 0
                 OR COALESCE(NULLIF(session_data->>'price_cents', '')::int, 0) > 0
                 OR stripe_payment_intent_id IS NOT NULL
                 OR COALESCE(session_data->>'stripe_invoice_id', '') <> ''
              )
            ORDER BY COALESCE(scheduled_start, created_at) DESC NULLS LAST
            LIMIT $2""",
        hardware_id,
        limit,
    )
    return [session_row_to_invoice(dict(r)) for r in rows]


def create_open_session_invoice(
    *,
    customer_id: str,
    amount_cents: int,
    session_id_str: str,
    description: str,
    days_until_due: int = DUNNING_INTERVAL_DAYS,
):
    """Draft + finalize a send_invoice Stripe Invoice for an unpaid session."""
    import stripe

    if amount_cents <= 0 or not customer_id:
        return None
    inv = stripe.Invoice.create(
        customer=customer_id,
        collection_method="send_invoice",
        days_until_due=days_until_due,
        auto_advance=False,
        metadata={"type": "session_fee", "session_id": session_id_str},
        description=description[:200],
    )
    stripe.InvoiceItem.create(
        customer=customer_id,
        invoice=inv.id,
        amount=amount_cents,
        currency="usd",
        description=description[:200],
    )
    return stripe.Invoice.finalize_invoice(inv.id)


async def persist_session_invoice(conn, session_uuid, invoice) -> None:
    hosted = getattr(invoice, "hosted_invoice_url", None)
    pdf = getattr(invoice, "invoice_pdf", None)
    payload = {
        "stripe_invoice_id": invoice.id,
        "hosted_invoice_url": hosted,
        "invoice_pdf": pdf,
        "invoice_status": getattr(invoice, "status", None),
    }
    await conn.execute(
        """UPDATE coaching_sessions
              SET session_data = COALESCE(session_data, '{}'::jsonb) || $2::jsonb,
                  updated_at = NOW()
            WHERE id = $1""",
        session_uuid,
        json.dumps(payload),
    )


async def mark_session_paid_from_invoice(db, invoice: Dict[str, Any]) -> bool:
    """invoice.paid webhook: mark coaching_sessions paid without double-charging."""
    if not db or not invoice:
        return False
    meta = invoice.get("metadata") or {}
    session_id = (meta.get("session_id") or "").strip()
    inv_id = invoice.get("id") or ""
    amount = int(invoice.get("amount_paid") or invoice.get("amount_due") or 0)
    if not session_id and not inv_id:
        return False
    try:
        row = await db.fetchrow(
            """SELECT id, session_id, payment_status
                 FROM coaching_sessions
                WHERE session_id = $1
                   OR session_data->>'stripe_invoice_id' = $2
                LIMIT 1""",
            session_id or "",
            inv_id,
        )
        if not row:
            return False
        if str(row["payment_status"] or "").lower() == "paid":
            return True
        hosted = invoice.get("hosted_invoice_url")
        await db.execute(
            """UPDATE coaching_sessions
                  SET payment_status = 'paid',
                      payment_amount_cents = COALESCE(NULLIF($1, 0), payment_amount_cents),
                      session_data = COALESCE(session_data, '{}'::jsonb) || $3::jsonb,
                      updated_at = NOW()
                WHERE id = $2""",
            amount,
            row["id"],
            json.dumps(
                {
                    "billing_obligation": "collected",
                    "stripe_invoice_id": inv_id,
                    "hosted_invoice_url": hosted,
                    "invoice_status": "paid",
                }
            ),
        )
        return True
    except Exception as e:
        logger.warning("mark_session_paid_from_invoice: %s", e)
        return False


async def remind_open_stripe_invoices(db_pool, notify) -> int:
    """Email open Stripe invoices every 7 days to the user email on file."""
    import stripe

    if not db_pool or not stripe.api_key:
        return 0
    sent = 0
    try:
        invoices = stripe.Invoice.list(status="open", limit=100)
    except Exception as e:
        logger.warning("remind_open_stripe_invoices: list failed: %s", e)
        return 0

    now = datetime.now(timezone.utc)
    async with db_pool.acquire() as conn:
        for inv in invoices.auto_paging_iter():
            if (getattr(inv, "amount_due", 0) or 0) <= 0:
                continue
            customer_id = getattr(inv, "customer", None)
            if not customer_id:
                continue
            user = await conn.fetchrow(
                """SELECT username, hardware_id,
                          profile_data->>'email' AS email,
                          profile_data->>'name' AS name
                     FROM users
                    WHERE stripe_customer_id = $1
                       OR profile_data->>'stripe_customer_id' = $1
                    LIMIT 1""",
                str(customer_id),
            )
            if not user or not user["email"]:
                continue
            dunn = await conn.fetchrow(
                """SELECT last_reminded_at FROM stripe_invoice_dunning
                    WHERE stripe_invoice_id = $1""",
                inv.id,
            )
            last = dunn["last_reminded_at"] if dunn else None
            if not should_send_dunning(last, now):
                continue
            hosted = getattr(inv, "hosted_invoice_url", None) or ""
            amount = (getattr(inv, "amount_due", 0) or 0) / 100.0
            name = user["name"] or "there"
            subject = "Payment reminder — unpaid invoice"
            body = (
                f"<p>Hello {name},</p>"
                f"<p>You have an unpaid invoice for <strong>${amount:.2f}</strong>.</p>"
                "<p>This is a reminder only — we will not charge extra. "
                "Pay from Billing → Invoices in the app, or use the Stripe link below.</p>"
                f"<p><a href=\"{hosted}\">Pay invoice</a></p>"
                "<p>We send this reminder every 7 days until the invoice is paid.</p>"
                "<p>Sovereign Sanctuary</p>"
            )
            try:
                if notify and hasattr(notify, "_send_email"):
                    await notify._send_email(user["email"], subject, body)
                await conn.execute(
                    """INSERT INTO stripe_invoice_dunning
                           (stripe_invoice_id, stripe_customer_id, user_id, email,
                            amount_due_cents, last_reminded_at, reminder_count)
                       VALUES ($1, $2, $3, $4, $5, NOW(), 1)
                       ON CONFLICT (stripe_invoice_id) DO UPDATE SET
                            last_reminded_at = NOW(),
                            reminder_count = stripe_invoice_dunning.reminder_count + 1,
                            amount_due_cents = EXCLUDED.amount_due_cents,
                            email = EXCLUDED.email""",
                    inv.id,
                    str(customer_id),
                    user["hardware_id"] or user["username"],
                    user["email"],
                    int(getattr(inv, "amount_due", 0) or 0),
                )
                sent += 1
            except Exception as e:
                logger.warning("remind_open_stripe_invoices: send %s failed: %s", inv.id, e)
    return sent
