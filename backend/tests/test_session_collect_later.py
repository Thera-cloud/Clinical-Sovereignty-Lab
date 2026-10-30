"""Collect-later override: due date, skip auto-cancel, 24h/3-day/30-day cadence."""

from datetime import datetime, timedelta, timezone

from app.services.session_collect_later import (
    collect_later_sql_skip,
    invoice_due_unix,
    is_collect_later,
    should_pause_membership,
    should_send_complete_notice,
    should_send_pm_nudge,
)
from app.services.session_invoice_ledger import session_invoice_visible, session_row_to_invoice
from app.services.session_payment_agent import SessionPaymentAgent
from app.services.session_booking_billing import INVOICE_TAB_NOTE


def test_is_collect_later_flag():
    assert is_collect_later({"collect_later": True})
    assert is_collect_later({"collect_later": "true"})
    assert not is_collect_later({"collect_later": False})
    assert not is_collect_later({})


def test_invoice_due_unix_session_day_not_past():
    now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    start = datetime(2026, 11, 4, 16, 0, tzinfo=timezone.utc)
    due = invoice_due_unix(start, now)
    due_dt = datetime.fromtimestamp(due, tz=timezone.utc)
    assert due_dt.date() == start.date()
    same_day = datetime(2026, 10, 30, 18, 0, tzinfo=timezone.utc)
    due_today = invoice_due_unix(same_day, now)
    assert due_today > int(now.timestamp())


def test_complete_notice_after_24h():
    end = datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)
    now = end + timedelta(hours=23)
    assert should_send_complete_notice(end, None, now) is False
    assert should_send_complete_notice(end, None, end + timedelta(hours=24)) is True
    assert should_send_complete_notice(end, now.isoformat(), end + timedelta(days=2)) is False


def test_nudge_every_three_days():
    now = datetime(2026, 10, 30, tzinfo=timezone.utc)
    assert should_send_pm_nudge(None, True, now) is True
    assert should_send_pm_nudge(now - timedelta(days=2), True, now) is False
    assert should_send_pm_nudge(now - timedelta(days=3), True, now) is True
    assert should_send_pm_nudge(None, False, now) is False


def test_pause_after_30_days_due():
    now = datetime(2026, 11, 30, tzinfo=timezone.utc)
    due = int(datetime(2026, 10, 30, 23, 59, tzinfo=timezone.utc).timestamp())
    assert should_pause_membership(due, False, now) is True
    assert should_pause_membership(due, True, now) is False
    early = int(datetime(2026, 11, 20, tzinfo=timezone.utc).timestamp())
    assert should_pause_membership(early, False, now) is False


def test_overdue_sql_skips_collect_later():
    src = open(SessionPaymentAgent._run_one_cycle.__code__.co_filename, encoding="utf-8").read()
    assert "collect_later" in src
    assert collect_later_sql_skip() in src or "session_data->>'collect_later'" in src


def test_collect_later_completed_invoice_visible():
    row = {
        "status": "completed",
        "payment_status": "pending",
        "price_cents": 12500,
        "session_data": {"collect_later": True, "stripe_invoice_id": "in_cl"},
        "scheduled_start": datetime(2026, 10, 1, tzinfo=timezone.utc),
        "session_id": "SES_CL",
    }
    assert session_invoice_visible(row) is True
    inv = session_row_to_invoice(row)
    assert inv["collect_later"] is True
    assert inv["past_due"] is True
    assert "Past-due" in inv["description"]


def test_invoice_tab_note_mentions_collect_later():
    assert "non-payment is consent to cancel" in INVOICE_TAB_NOTE
    assert "Collect later" in INVOICE_TAB_NOTE or "collect later" in INVOICE_TAB_NOTE.lower()
