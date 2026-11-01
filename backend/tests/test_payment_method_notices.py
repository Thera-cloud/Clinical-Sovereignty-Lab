"""Offline unit tests for card expiry + notice cadence."""

from datetime import datetime, timedelta, timezone

from app.services.payment_method_notices import (
    SETTINGS_HINT,
    card_health,
    should_resend,
)


NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def test_card_valid_through_expiry_month():
    assert card_health(11, 2026, now=NOW) == "expiring"


def test_card_expired_after_month_ends():
    assert card_health(10, 2026, now=NOW) == "expired"


def test_card_ok_when_far_out():
    assert card_health(12, 2029, now=NOW) == "ok"


def test_card_expiring_within_45_days():
    late = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    assert card_health(12, 2026, now=late) == "expiring"


def test_should_resend_seven_days():
    assert should_resend(None, now=NOW) is True
    assert should_resend(NOW - timedelta(days=6), now=NOW) is False
    assert should_resend(NOW - timedelta(days=7), now=NOW) is True


def test_settings_hint_names_payments():
    assert "Settings → Payments" in SETTINGS_HINT
    assert "Update Card" in SETTINGS_HINT
