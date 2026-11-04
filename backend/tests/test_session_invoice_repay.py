"""Revive stuck session invoices when the saved card changes."""

from types import SimpleNamespace

from app.services.session_invoice_repay import (
    invoice_needs_revive,
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
