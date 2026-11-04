"""Revive stuck session invoices when the saved card changes."""

from types import SimpleNamespace

from app.services.session_invoice_repay import (
    invoice_needs_revive,
    is_session_invoice,
    last_charged_pm_id,
    should_skip_auto_pay,
)
from app.services.session_payment_agent import SessionPaymentAgent


def _stuck_invoice(pm="pm_old"):
    return SimpleNamespace(
        status="open",
        payment_intent=SimpleNamespace(status="canceled", payment_method=pm),
        charge=SimpleNamespace(
            status="failed",
            payment_method=pm,
            failure_code="card_declined",
            outcome={"reason": "previously_declined_do_not_retry", "type": "blocked"},
        ),
        default_payment_method=None,
        hosted_invoice_url="https://invoice.stripe.com/i/old",
    )


def test_needs_revive_canceled_pi():
    inv = _stuck_invoice()
    assert invoice_needs_revive(inv) is True
    assert last_charged_pm_id(inv) == "pm_old"


def test_skip_same_declined_pm_not_new_card():
    inv = _stuck_invoice("pm_8921")
    assert should_skip_auto_pay(inv, "pm_8921") is True
    assert should_skip_auto_pay(inv, "pm_6398") is False
    assert should_skip_auto_pay(inv, "") is True


def test_paid_invoice_does_not_revive():
    inv = SimpleNamespace(
        status="paid",
        payment_intent=SimpleNamespace(status="succeeded"),
        charge=None,
        default_payment_method="pm_ok",
    )
    assert invoice_needs_revive(inv) is False
    assert should_skip_auto_pay(inv, "pm_ok") is False


def test_72h_charge_query_skips_collect_later():
    src = open(SessionPaymentAgent._run_one_cycle.__code__.co_filename, encoding="utf-8").read()
    assert "session_data->>'collect_later'" in src
    assert "charge_blocked_pm" in src
    assert "heal_open_session_invoices" in src


def test_is_session_invoice_not_subscription():
    assert is_session_invoice(SimpleNamespace(metadata={"type": "session_fee"})) is True
    assert is_session_invoice(SimpleNamespace(metadata={"session_id": "SES_1"})) is True
    assert is_session_invoice(SimpleNamespace(metadata={"collect_later": "true"})) is True
    assert is_session_invoice(SimpleNamespace(metadata={"type": "subscription"})) is False


def test_admin_retry_and_portal_webhook_use_revive():
    from pathlib import Path
    root = Path(SessionPaymentAgent._run_one_cycle.__code__.co_filename).parents[1]
    admin = (root / "routers" / "admin.py").read_text(encoding="utf-8")
    stripe_src = (root / "services" / "stripe_integration.py").read_text(encoding="utf-8")
    assert "pay_or_revive_open_invoice" in admin
    assert "_stripe.Invoice.pay(invoice.id)" not in admin
    assert "setup_intent.succeeded" in stripe_src
