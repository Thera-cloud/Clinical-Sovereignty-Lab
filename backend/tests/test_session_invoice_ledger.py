"""Session invoice ledger + persist must not wipe quoted session prices."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services import pg_data_helpers
from app.services.session_booking_billing import APPLY_CUSTOM_SESSION_RATE_SQL
from app.services.session_booking_billing import INVOICE_TAB_NOTE, SESSION_PAYMENT_POLICY
from app.services.session_invoice_ledger import (
    DUNNING_INTERVAL_DAYS,
    HYDRATE_SESSION_PRICE_SQL,
    merge_invoice_lists,
    session_invoice_visible,
    session_row_to_invoice,
    should_send_dunning,
    sync_stripe_on_session_cancel,
)


def test_upsert_sql_does_not_clobber_price_with_zero():
    src = open(pg_data_helpers.__file__, encoding="utf-8").read()
    assert "NULLIF(EXCLUDED.price_cents, 0)" in src


def test_hydrate_sql_copies_json_price():
    assert "session_data->>'price_cents'" in HYDRATE_SESSION_PRICE_SQL
    assert "payment_status = 'pending'" in HYDRATE_SESSION_PRICE_SQL


def test_apply_custom_rate_sql_pending_live_only():
    assert "custom_session_rate_cents" in APPLY_CUSTOM_SESSION_RATE_SQL
    assert "custom_rate" in APPLY_CUSTOM_SESSION_RATE_SQL
    assert "stripe_payment_intent_id" in APPLY_CUSTOM_SESSION_RATE_SQL
    assert "PENDING_APPROVAL" in APPLY_CUSTOM_SESSION_RATE_SQL


def test_should_send_dunning_every_seven_days():
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    assert should_send_dunning(None, now) is True
    assert should_send_dunning(now - timedelta(days=6), now) is False
    assert should_send_dunning(now - timedelta(days=7), now) is True
    assert DUNNING_INTERVAL_DAYS == 7


def test_session_row_to_invoice_pending_and_paid():
    pending = session_row_to_invoice(
        {
            "session_id": "SES_1",
            "payment_status": "pending",
            "price_cents": 0,
            "session_data": {
                "price_cents": 12500,
                "hosted_invoice_url": "https://pay.stripe.com/x",
            },
            "scheduled_start": datetime(2026, 9, 22, 11, 0, tzinfo=timezone.utc),
        }
    )
    assert pending["status"] == "open"
    assert pending["amount_due"] == 125.0
    assert pending["hosted_url"].startswith("https://")

    paid = session_row_to_invoice(
        {
            "session_id": "SES_2",
            "payment_status": "paid",
            "price_cents": 12500,
            "payment_amount_cents": 12500,
            "stripe_payment_intent_id": "pi_abc",
            "session_data": {"receipt_url": "https://pay.stripe.com/r"},
        }
    )
    assert paid["status"] == "paid"
    assert paid["amount_paid"] == 125.0
    assert paid["kind"] == "session_charge"


def test_merge_invoice_lists_dedupes_session_id():
    stripe = [
        {
            "id": "in_1",
            "session_id": "SES_1",
            "status": "open",
            "created": "2026-09-20",
        }
    ]
    sessions = [
        {
            "id": "SES_1",
            "session_id": "SES_1",
            "status": "open",
            "created": "2026-09-19",
        },
        {
            "id": "pi_2",
            "session_id": "SES_2",
            "status": "paid",
            "created": "2026-09-01",
        },
    ]
    merged = merge_invoice_lists(stripe, sessions, limit=10)
    assert len(merged) == 2
    assert merged[0]["id"] == "in_1"


def test_payment_policy_consent_copy():
    assert "consent to that cancellation by non-payment" in SESSION_PAYMENT_POLICY
    assert "Cancel inside 24 hours: payment is still due" in SESSION_PAYMENT_POLICY
    assert "non-payment is consent to cancel" in INVOICE_TAB_NOTE


def test_cancelled_session_hidden_unless_late_cancel():
    cancelled = {
        "session_id": "SES_CXL",
        "status": "cancelled",
        "payment_status": "pending",
        "price_cents": 12500,
        "session_data": {"stripe_invoice_id": "in_dead"},
    }
    assert session_invoice_visible(cancelled) is False
    cancelled["session_data"]["late_cancel_fee"] = True
    assert session_invoice_visible(cancelled) is True


def test_upcoming_and_used_sessions_visible():
    assert session_invoice_visible(
        {"status": "scheduled", "payment_status": "pending", "price_cents": 9000}
    )
    assert session_invoice_visible(
        {"status": "completed", "payment_status": "unpaid", "price_cents": 12500}
    )


def test_merge_drops_void_and_hidden_session():
    stripe = [
        {"id": "in_void", "status": "void", "session_id": "SES_X", "created": "1"},
        {"id": "in_open", "status": "open", "session_id": "SES_DEAD", "created": "2"},
        {"id": "in_ok", "status": "open", "session_id": "SES_LIVE", "created": "3"},
    ]
    merged = merge_invoice_lists(
        stripe, [], limit=10,
        hide_session_ids={"SES_DEAD"}, hide_invoice_ids={"in_dead"},
    )
    assert [i["id"] for i in merged] == ["in_ok"]


@pytest.mark.asyncio
async def test_sync_late_cancel_keeps_due():
    session = {
        "session_id": "SES_LATE",
        "payment_status": "pending",
        "session_data": {},
    }
    out = await sync_stripe_on_session_cancel(object(), session, keep_due=True)
    assert out == "late_cancel_due"
    assert session["late_cancel_fee"] is True
    assert session["session_data"]["late_cancel_fee"] is True
