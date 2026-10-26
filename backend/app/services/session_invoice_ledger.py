"""Session + Stripe invoice ledger — hydrate prices, open invoices, 7-day dunning.

Session fees are PaymentIntents (72h before start). Stripe Invoice objects are
subscriptions plus fallback send_invoice when off-session charge fails or a
past session stayed unpaid. Clients see both on GET /api/billing/invoices.
Cancelled sessions are hidden and their open Stripe invoices are voided unless
the client cancelled inside 24 hours (late_cancel_fee — payment still due).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.session_booking_billing import effective_price_cents

logger = logging.getLogger("nate.session_invoice_ledger")

DUNNING_INTERVAL_DAYS = 7
_DEAD_STATUSES = frozenset(
    {"cancelled", "canceled", "cancelled_by_google", "rescheduled"}
)
_ACTIVE_STATUSES = frozenset(
    {"scheduled", "confirmed", "active", "pending_approval", "booked"}
)
_USED_STATUSES = frozenset({"completed", "complete", "no_show"})
_VOID_STATUSES = frozenset({"void", "voided", "uncollectible"})


def _session_data(row: Any) -> Dict[str, Any]:
    data = {}
    if isinstance(row, dict):
        data = row.get("session_data") or {}
    if isinstance(data, str):
        try:
            data = json.loads(data) if data else {}
        except Exception:
            data = {}
    return data if isinstance(data, dict) else {}


def late_cancel_due(row: Dict[str, Any]) -> bool:
    data = _session_data(row)
    flag = data.get("late_cancel_fee", row.get("late_cancel_fee"))
    return flag is True or str(flag or "").lower() in ("true", "1", "yes")


def session_invoice_visible(row: Dict[str, Any]) -> bool:
    """Upcoming, used, or late-cancel-still-due. Cancelled-and-voided stay off Pay now."""
    status = str(row.get("status") or "").lower()
    pay = str(row.get("payment_status") or "").lower()
    data = _session_data(row)
    ref_only = data.get("calendar_reference_only")
    if ref_only is True or str(ref_only or "").lower() in ("true", "1", "yes"):
        if status not in _USED_STATUSES:
            return False
    if status in _ACTIVE_STATUSES:
        return True
    if status in _USED_STATUSES:
        return True
    if status in _DEAD_STATUSES:
        return late_cancel_due(row) and pay in ("pending", "unpaid", "paid")
    return False

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
    data = _session_data(row)
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
    hide_session_ids: Optional[Set[str]] = None,
    hide_invoice_ids: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Stripe subscription invoices first, then session rows not already listed."""
    hide_sids = hide_session_ids or set()
    hide_invs = hide_invoice_ids or set()

    def _drop(inv: Dict[str, Any]) -> bool:
        st = str(inv.get("status") or "").lower()
        if st in _VOID_STATUSES:
            return True
        if str(inv.get("id") or "") in hide_invs:
            return True
        sid = str(inv.get("session_id") or "")
        return bool(sid and sid in hide_sids)

    kept = [i for i in stripe_invoices if not _drop(i)]
    seen = {str(i.get("id") or "") for i in kept}
    out = list(kept)
    for item in session_invoices:
        if _drop(item):
            continue
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


async def load_session_invoice_bundle(
    conn, hardware_id: str, limit: int = 40,
) -> Tuple[List[Dict[str, Any]], Set[str], Set[str]]:
    """Visible invoices plus cancelled Stripe/session ids to drop from Pay now."""
    empty: Tuple[List[Dict[str, Any]], Set[str], Set[str]] = ([], set(), set())
    if not hardware_id:
        return empty
    rows = await conn.fetch(
        """SELECT session_id, status, payment_status, price_cents, payment_amount_cents,
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
        max(int(limit or 40) * 3, 40),
    )
    visible: List[Dict[str, Any]] = []
    hide_sids: Set[str] = set()
    hide_invs: Set[str] = set()
    for rec in rows:
        row = dict(rec)
        sid = str(row.get("session_id") or "")
        inv_id = str(_session_data(row).get("stripe_invoice_id") or "")
        if session_invoice_visible(row):
            visible.append(session_row_to_invoice(row))
            if len(visible) >= limit:
                break
        else:
            if sid:
                hide_sids.add(sid)
            if inv_id:
                hide_invs.add(inv_id)
    return visible, hide_sids, hide_invs


async def load_session_invoices(conn, hardware_id: str, limit: int = 40) -> List[Dict[str, Any]]:
    items, _, _ = await load_session_invoice_bundle(conn, hardware_id, limit)
    return items


async def void_open_session_invoice(conn, session: Dict[str, Any]) -> str:
    """Void an open Stripe send_invoice tied to a cancelled session. No-op if paid."""
    data = _session_data(session)
    inv_id = str(data.get("stripe_invoice_id") or "").strip()
    sid = session.get("session_id")
    if not inv_id:
        pay = str(session.get("payment_status") or "").lower()
        if pay in ("pending", "unpaid") and sid:
            try:
                await conn.execute(
                    """UPDATE coaching_sessions
                          SET payment_status = 'cancelled',
                              session_data = COALESCE(session_data, '{}'::jsonb)
                                || '{"invoice_status":"void"}'::jsonb,
                              updated_at = NOW()
                        WHERE session_id = $1
                          AND LOWER(COALESCE(payment_status,'')) IN ('pending','unpaid')""",
                    sid,
                )
            except Exception:
                pass
        return "no_invoice"
    try:
        import stripe

        if not getattr(stripe, "api_key", None):
            stripe.api_key = __import__("os").getenv("STRIPE_SECRET_KEY", "")
        inv = stripe.Invoice.retrieve(inv_id)
        status = str(getattr(inv, "status", "") or "").lower()
        if status in ("open", "draft"):
            stripe.Invoice.void_invoice(inv_id)
            status = "void"
        elif status in _VOID_STATUSES:
            status = "void"
        elif status == "paid":
            return "paid"
        data["invoice_status"] = status or "void"
        if isinstance(session, dict):
            session["session_data"] = data
            if str(session.get("payment_status") or "").lower() in ("pending", "unpaid"):
                session["payment_status"] = "cancelled"
        if sid:
            await conn.execute(
                """UPDATE coaching_sessions
                      SET payment_status = CASE
                            WHEN LOWER(COALESCE(payment_status,'')) IN ('pending','unpaid')
                            THEN 'cancelled' ELSE payment_status END,
                          session_data = COALESCE(session_data, '{}'::jsonb)
                            || $2::jsonb,
                          updated_at = NOW()
                    WHERE session_id = $1""",
                sid,
                json.dumps({"invoice_status": "void", "stripe_invoice_id": inv_id}),
            )
        return "voided"
    except Exception as e:
        logger.warning("void_open_session_invoice %s: %s", inv_id, e)
        return "error"


async def sync_stripe_on_session_cancel(
    db_pool, session: Dict[str, Any], *, keep_due: bool = False,
) -> str:
    """Late client cancel keeps the invoice; every other cancel voids it."""
    data = _session_data(session)
    if keep_due:
        data["late_cancel_fee"] = True
        session["session_data"] = data
        session["late_cancel_fee"] = True
        return "late_cancel_due"
    if not db_pool or not hasattr(db_pool, "acquire"):
        pay = str(session.get("payment_status") or "").lower()
        if pay in ("pending", "unpaid"):
            session["payment_status"] = "cancelled"
        data["invoice_status"] = "void"
        session["session_data"] = data
        return "skipped_no_pool"
    try:
        async with db_pool.acquire() as conn:
            return await void_open_session_invoice(conn, session)
    except Exception as e:
        logger.warning("sync_stripe_on_session_cancel: %s", e)
        return "error"


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
            sess = await conn.fetchrow(
                """SELECT session_id, status, payment_status, session_data
                     FROM coaching_sessions
                    WHERE session_data->>'stripe_invoice_id' = $1
                    LIMIT 1""",
                inv.id,
            )
            if sess and not session_invoice_visible(dict(sess)):
                try:
                    await void_open_session_invoice(conn, dict(sess))
                except Exception:
                    pass
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
