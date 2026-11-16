"""Stripe webhook payloads from API 2025-12-15.clover."""

from app.services.stripe_integration import (
    _invoice_subscription_id,
    _stripe_period,
    _table_sub_status,
    _user_sub_status,
)


def test_invoice_subscription_id_reads_parent_details():
    invoice = {
        "parent": {"type": "subscription_details", "subscription_details": {"subscription": "sub_123"}},
    }
    assert _invoice_subscription_id(invoice) == "sub_123"
    assert _invoice_subscription_id({"subscription": "sub_old"}) == "sub_old"
    assert _invoice_subscription_id({}) is None


def test_period_falls_back_to_subscription_item():
    start, end = _stripe_period(
        {"items": {"data": [{"current_period_start": 10, "current_period_end": 20}]}}
    )
    assert (start, end) == (10, 20)
    assert _stripe_period({"current_period_end": 5, "current_period_start": 1}) == (1, 5)


def test_canceled_maps_to_cancelled_user_status():
    assert _user_sub_status("canceled") == "CANCELLED"
    assert _user_sub_status("past_due") == "GRACE_PERIOD"
    assert _user_sub_status("active") == "ACTIVE"
    assert _table_sub_status("canceled") == "CANCELLED"
    assert _table_sub_status("past_due") == "PAST_DUE"


def test_w9_filename_strips_path():
    from app.services.coach_w9_vault import safe_w9_filename

    assert safe_w9_filename("../../etc/passwd") == "passwd"
    assert safe_w9_filename("w9 form.pdf") == "w9_form.pdf"
