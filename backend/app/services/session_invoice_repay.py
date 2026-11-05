"""Revive stuck session invoices and charge a newly saved payment method.

send_invoice invoices keep the first PaymentIntent. After a decline Stripe
cancels that PI (`previously_declined_do_not_retry`) and the hosted page
tells the client to contact the business — even after they add a new card.
Void + recreate, attach the current default PM, then Invoice.pay.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.session_invoice_repay")

BLOCKED_OUTCOMES = frozenset({"previously_declined_do_not_retry"})
DEAD_PI = frozenset({"canceled", "cancelled", "requires_payment_method"})
DEAD_INV = frozenset({"void", "voided", "uncollectible"})


def _obj_get(obj: Any, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_id(raw: Any) -> str:
    if not raw:
        return ""
    if isinstance(raw, str):
        return raw
    return str(getattr(raw, "id", "") or "")


def pi_status(inv: Any) -> str:
    pi = _obj_get(inv, "payment_intent")
    if not pi:
        return ""
    if isinstance(pi, str):
        return ""
    return str(_obj_get(pi, "status") or "").lower()


def charge_outcome_reason(charge: Any) -> str:
    if not charge or isinstance(charge, str):
        return ""
    outcome = _obj_get(charge, "outcome") or {}
    if not isinstance(outcome, dict):
        outcome = {
            "reason": getattr(outcome, "reason", None),
            "type": getattr(outcome, "type", None),
        }
    return str(outcome.get("reason") or "").lower()


def last_charged_pm_id(inv: Any) -> str:
    charge = _obj_get(inv, "charge")
    if charge and not isinstance(charge, str):
        pm = _obj_get(charge, "payment_method")
        pid = _as_id(pm)
        if pid:
            return pid
    pi = _obj_get(inv, "payment_intent")
    if pi and not isinstance(pi, str):
        return _as_id(_obj_get(pi, "payment_method"))
    return _as_id(_obj_get(inv, "default_payment_method"))


def invoice_needs_revive(inv: Any) -> bool:
    """True when the hosted page / PI can no longer collect payment."""
    status = str(_obj_get(inv, "status") or "").lower()
    if status == "paid":
        return False
    if status in DEAD_INV:
        return True
    if pi_status(inv) in DEAD_PI:
        return True
    charge = _obj_get(inv, "charge")
    if charge and not isinstance(charge, str):
        if str(_obj_get(charge, "status") or "").lower() == "failed":
            if charge_outcome_reason(charge) in BLOCKED_OUTCOMES:
                return True
            if str(_obj_get(charge, "failure_code") or "").lower() == "card_declined":
                return True
    return False


def should_skip_auto_pay(inv: Any, current_pm: str) -> bool:
    """Do not Invoice.pay the same declined PM. A new PM must be charged."""
    pm = (current_pm or "").strip()
    if not pm:
        return True
    last = last_charged_pm_id(inv)
    if last and last == pm and invoice_needs_revive(inv):
        return True
    return False


def _ensure_stripe():
    import stripe

    if not getattr(stripe, "api_key", None):
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    return stripe


def retrieve_invoice(invoice_id: str):
    stripe = _ensure_stripe()
    return stripe.Invoice.retrieve(
        invoice_id,
        expand=["payment_intent", "charge", "charge.outcome"],
    )


def customer_default_pm(customer_id: str) -> str:
    if not customer_id:
        return ""
    stripe = _ensure_stripe()
    cu = stripe.Customer.retrieve(customer_id)
    inv = _obj_get(cu, "invoice_settings")
    raw = None
    if isinstance(inv, dict):
        raw = inv.get("default_payment_method")
    elif inv is not None:
        raw = getattr(inv, "default_payment_method", None)
    pid = _as_id(raw)
    if pid:
        return pid
    cards = stripe.PaymentMethod.list(customer=customer_id, type="card", limit=1)
    data = getattr(cards, "data", None) or []
    return _as_id(data[0]) if data else ""


async def _persist_invoice(db, invoice, extra: Optional[Dict[str, Any]] = None) -> None:
    if not db:
        return
    meta = _obj_get(invoice, "metadata") or {}
    if hasattr(meta, "to_dict"):
        meta = meta.to_dict()
    sid = str((meta or {}).get("session_id") or "")
    from app.services.session_invoice_ledger import persist_session_invoice

    async def _run(conn):
        row = None
        if sid:
            row = await conn.fetchrow(
                "SELECT id FROM coaching_sessions WHERE session_id = $1", sid,
            )
        if not row:
            inv_id = _as_id(invoice)
            row = await conn.fetchrow(
                """SELECT id FROM coaching_sessions
                    WHERE session_data->>'stripe_invoice_id' = $1 LIMIT 1""",
                inv_id,
            )
        if row:
            await persist_session_invoice(conn, row["id"], invoice, extra=extra)

    if hasattr(db, "acquire"):
        async with db.acquire() as conn:
            await _run(conn)
    else:
        await _run(db)


async def _session_already_collected(db, invoice) -> Optional[str]:
    """Reason string when the invoice's session is already paid via another
    PaymentIntent, else None. DB unavailable → None (invoice path keeps its
    own Stripe-side 'paid' idempotency)."""
    if not db:
        return None
    meta = _obj_get(invoice, "metadata") or {}
    if hasattr(meta, "to_dict"):
        meta = meta.to_dict()
    sid = str((meta or {}).get("session_id") or "")
    if not sid:
        return None
    this_pi = _as_id(_obj_get(invoice, "payment_intent"))
    from app.services.session_charge_guard import session_collected_elsewhere

    async def _run(conn):
        return await session_collected_elsewhere(conn, sid, this_pi)

    try:
        if hasattr(db, "acquire"):
            async with db.acquire() as conn:
                return await _run(conn)
        return await _run(db)
    except Exception as e:
        logger.warning("_session_already_collected %s: %s", sid, e)
        return None


async def _mark_paid(db, invoice) -> None:
    if not db:
        return
    from app.services.session_invoice_ledger import mark_session_paid_from_invoice

    payload = invoice.to_dict() if hasattr(invoice, "to_dict") else {
        "id": _as_id(invoice),
        "amount_paid": _obj_get(invoice, "amount_paid") or 0,
        "hosted_invoice_url": _obj_get(invoice, "hosted_invoice_url"),
        "metadata": dict(_obj_get(invoice, "metadata") or {}),
        "status": _obj_get(invoice, "status"),
    }

    async def _run(conn):
        await mark_session_paid_from_invoice(conn, payload)
        try:
            from app.services.session_collect_later import on_session_invoice_paid
            await on_session_invoice_paid(conn, payload)
        except Exception as e:
            logger.warning("on_session_invoice_paid: %s", e)

    if hasattr(db, "acquire"):
        async with db.acquire() as conn:
            await _run(conn)
    else:
        await _run(db)


def _recreate_invoice(old) -> Any:
    stripe = _ensure_stripe()
    customer = _as_id(_obj_get(old, "customer"))
    amount = int(_obj_get(old, "amount_due") or _obj_get(old, "total") or 0)
    meta = _obj_get(old, "metadata") or {}
    if hasattr(meta, "to_dict"):
        meta = meta.to_dict()
    meta = dict(meta or {})
    sid = str(meta.get("session_id") or "")
    desc = str(_obj_get(old, "description") or f"Session {sid}")[:200]
    status = str(_obj_get(old, "status") or "").lower()
    old_id = _as_id(old)
    if old_id and status in ("open", "draft"):
        try:
            stripe.Invoice.void_invoice(old_id)
        except Exception as e:
            logger.info("void before recreate %s: %s", old_id, e)
    from app.services.session_invoice_ledger import create_open_session_invoice
    from app.services.session_collect_later import invoice_due_unix
    from datetime import datetime, timezone

    extra = {k: v for k, v in meta.items() if k != "type"}
    extra["revived_from"] = old_id
    created = create_open_session_invoice(
        customer_id=customer,
        amount_cents=amount,
        session_id_str=sid or old_id,
        description=desc,
        due_date=invoice_due_unix(datetime.now(timezone.utc)),
        extra_metadata=extra,
    )
    if not created:
        raise RuntimeError("create_open_session_invoice returned none")
    return created


async def pay_or_revive_open_invoice(
    db,
    *,
    invoice_id: str,
    payment_method_id: Optional[str] = None,
    charge: bool = True,
) -> Dict[str, Any]:
    """Attach current PM, recreate if the PI is dead, optionally off-session pay."""
    out: Dict[str, Any] = {
        "invoice_id": invoice_id,
        "paid": False,
        "revived": False,
        "hosted_url": None,
        "error": None,
        "skipped_same_declined_pm": False,
    }
    if not invoice_id or not str(invoice_id).startswith("in_"):
        out["error"] = "invoice_id required"
        return out
    stripe = _ensure_stripe()
    if not stripe.api_key:
        out["error"] = "stripe unavailable"
        return out
    try:
        inv = retrieve_invoice(invoice_id)
    except Exception as e:
        out["error"] = str(e)[:180]
        return out

    status = str(_obj_get(inv, "status") or "").lower()
    out["hosted_url"] = _obj_get(inv, "hosted_invoice_url")
    if status == "paid":
        out["paid"] = True
        await _mark_paid(db, inv)
        return out

    pm = (payment_method_id or "").strip()
    if not pm:
        pm = customer_default_pm(_as_id(_obj_get(inv, "customer")))

    skip_charge = charge and should_skip_auto_pay(inv, pm)
    if skip_charge:
        out["skipped_same_declined_pm"] = True
        charge = False

    if invoice_needs_revive(inv):
        try:
            inv = _recreate_invoice(inv)
            out["revived"] = True
            out["invoice_id"] = _as_id(inv)
            await _persist_invoice(db, inv, extra={"invoice_revived": True})
        except Exception as e:
            out["error"] = f"revive failed: {e}"[:180]
            logger.warning("pay_or_revive recreate %s: %s", invoice_id, e)
            return out

    if pm:
        try:
            stripe.Invoice.modify(_as_id(inv), default_payment_method=pm)
        except Exception as e:
            logger.info("Invoice.modify default PM %s: %s", _as_id(inv), e)

    # Double-collection guard: if the linked session was already paid by a
    # different PaymentIntent (card charge), never auto-pay this invoice too.
    if charge and pm:
        blocked = await _session_already_collected(db, inv)
        if blocked:
            out["error"] = f"double collection blocked: {blocked}"[:180]
            out["double_collection_blocked"] = True
            logger.error("pay_or_revive %s: %s — NOT charging", _as_id(inv), blocked)
            charge = False

    if charge and pm:
        try:
            try:
                inv = stripe.Invoice.pay(
                    _as_id(inv), payment_method=pm, off_session=True,
                )
            except TypeError:
                inv = stripe.Invoice.pay(_as_id(inv), payment_method=pm)
        except Exception as e:
            out["error"] = str(e)[:180]
            logger.info("Invoice.pay %s: %s", _as_id(inv), e)
            try:
                inv = retrieve_invoice(_as_id(inv))
            except Exception:
                pass

    status = str(_obj_get(inv, "status") or "").lower()
    out["hosted_url"] = _obj_get(inv, "hosted_invoice_url")
    out["paid"] = status == "paid"
    if out["paid"]:
        await _mark_paid(db, inv)
        out["error"] = None
    elif out["revived"] and out["hosted_url"]:
        try:
            stripe.Invoice.send_invoice(_as_id(inv))
        except Exception as e:
            logger.info("send_invoice %s: %s", _as_id(inv), e)
    return out


def is_session_invoice(inv) -> bool:
    """True for coaching-session invoices — never membership/subscription invoices."""
    meta = _obj_get(inv, "metadata") or {}
    if hasattr(meta, "to_dict"):
        meta = meta.to_dict()
    meta = dict(meta or {})
    if str(meta.get("type") or "") == "session_fee":
        return True
    if str(meta.get("collect_later") or "").lower() in ("true", "1", "yes"):
        return True
    return str(meta.get("session_id") or "").startswith("SES_")


async def heal_open_session_invoices(db) -> int:
    """30-min safety net: revive+charge open session invoices when a usable default PM exists."""
    if not db:
        return 0
    stripe = _ensure_stripe()
    if not stripe.api_key:
        return 0
    paid = 0
    try:
        for inv in stripe.Invoice.list(status="open", limit=40).auto_paging_iter():
            if not is_session_invoice(inv):
                continue
            result = await pay_or_revive_open_invoice(db, invoice_id=inv.id, charge=True)
            if result.get("paid"):
                paid += 1
    except Exception as e:
        logger.warning("heal_open_session_invoices: %s", e)
    return paid


async def try_charge_overdue_for_user(db, user_id: str) -> int:
    """After a card is saved/starred: revive stuck invoices and charge the new PM."""
    if not db or not user_id:
        return 0
    paid = 0
    try:
        stripe = _ensure_stripe()
        if not stripe.api_key:
            return 0
        async with db.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT hardware_id, username,
                          COALESCE(NULLIF(stripe_customer_id, ''),
                                   profile_data->>'stripe_customer_id') AS cid
                     FROM users
                    WHERE hardware_id = $1 OR username = $1 OR id::text = $1
                    LIMIT 1""",
                user_id,
            )
        if not row or not row["cid"]:
            return 0
        pm = customer_default_pm(row["cid"])
        if not pm:
            return 0
        invoices = stripe.Invoice.list(customer=row["cid"], status="open", limit=20)
        for inv in invoices.data:
            result = await pay_or_revive_open_invoice(
                db, invoice_id=inv.id, payment_method_id=pm, charge=True,
            )
            if result.get("paid"):
                paid += 1
    except Exception as e:
        logger.warning("try_charge_overdue_for_user: %s", e)
    return paid
