"""Session invoice ledger + persist must not wipe quoted session prices."""

from datetime import datetime, timedelta, timezone

from app.services import pg_data_helpers
from app.services.session_booking_billing import APPLY_CUSTOM_SESSION_RATE_SQL
from app.services.session_invoice_ledger import (
    DUNNING_INTERVAL_DAYS,
    HYDRATE_SESSION_PRICE_SQL,
    merge_invoice_lists,
    session_row_to_invoice,
    should_send_dunning,
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
