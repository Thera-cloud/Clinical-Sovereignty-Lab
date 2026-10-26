"""Offline tests for next-day session ops reconcile + GCal cancel match."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.session_ops_reconcile_agent import (
    SessionOpsReconcileAgent,
    classify_session,
)


NOW = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)
FUTURE = NOW + timedelta(hours=20)


def test_classify_dead_with_gcal_deletes():
    actions = classify_session(
        {
            "status": "cancelled",
            "scheduled_start": FUTURE.isoformat(),
            "google_event_id": "g1",
            "sync_state": "synced",
        },
        NOW,
    )
    assert "delete_gcal" in actions
    assert "notify" in actions


def test_classify_hidden_future_cancels():
    actions = classify_session(
        {
            "status": "completed",
            "scheduled_start": FUTURE.isoformat(),
            "session_data": {"schedule_link_hidden": True},
            "google_event_id": "g2",
            "sync_state": "synced",
        },
        NOW,
    )
    assert "cancel_hidden_future" in actions
    assert "delete_gcal" in actions


def test_classify_unpaid_inside_24h():
    actions = classify_session(
        {
            "status": "scheduled",
            "scheduled_start": FUTURE.isoformat(),
            "payment_status": "pending",
            "price_cents": 12500,
        },
        NOW,
    )
    assert "unpaid_risk" in actions


def test_classify_paid_billable():
    actions = classify_session(
        {
            "status": "scheduled",
            "scheduled_start": FUTURE.isoformat(),
            "payment_status": "paid",
            "price_cents": 12500,
        },
        NOW,
    )
    assert actions == ["billable"]


def test_classify_cancelled_pending_voids_orphan_invoice():
    actions = classify_session(
        {
            "status": "cancelled",
            "scheduled_start": FUTURE.isoformat(),
            "payment_status": "pending",
            "price_cents": 12500,
            "session_data": {"stripe_invoice_id": "in_west", "invoice_status": "open"},
            "sync_state": "deleted",
        },
        NOW,
    )
    assert "void_orphan_invoice" in actions
    assert "billing_mismatch" in actions


def test_classify_late_cancel_keeps_invoice():
    actions = classify_session(
        {
            "status": "cancelled",
            "scheduled_start": FUTURE.isoformat(),
            "payment_status": "pending",
            "session_data": {"late_cancel_fee": True, "stripe_invoice_id": "in_keep"},
            "sync_state": "deleted",
        },
        NOW,
    )
    assert "void_orphan_invoice" not in actions


def test_classify_paid_beyond_36h_is_not_billable_flag():
    later = NOW + timedelta(days=4)
    actions = classify_session(
        {
            "status": "scheduled",
            "scheduled_start": later.isoformat(),
            "payment_status": "paid",
            "price_cents": 12500,
        },
        NOW,
    )
    assert "billable" not in actions


def test_classify_hidden_four_days_out_still_cancels():
    later = NOW + timedelta(days=4)
    actions = classify_session(
        {
            "status": "completed",
            "scheduled_start": later.isoformat(),
            "session_data": {"schedule_link_hidden": True},
            "google_event_id": "g-west",
            "sync_state": "synced",
        },
        NOW,
    )
    assert "cancel_hidden_future" in actions
    assert "delete_gcal" in actions


def test_classify_past_active_is_noop():
    actions = classify_session(
        {
            "status": "scheduled",
            "scheduled_start": (NOW - timedelta(hours=2)).isoformat(),
            "google_event_id": "g3",
        },
        NOW,
    )
    assert actions == []


def test_classify_skips_notify_when_already_sent():
    actions = classify_session(
        {
            "status": "cancelled",
            "scheduled_start": FUTURE.isoformat(),
            "session_data": {"cancel_notify_sent": True},
            "sync_state": "deleted",
        },
        NOW,
    )
    assert "notify" not in actions
    assert "delete_gcal" not in actions


@pytest.mark.asyncio
async def test_clone_and_flag_skip(monkeypatch):
    monkeypatch.setenv("IS_CLONE", "true")
    agent = SessionOpsReconcileAgent(db_pool=object())
    await agent.start()
    assert agent._running is False
    monkeypatch.delenv("IS_CLONE", raising=False)
    monkeypatch.setenv("ENABLE_SESSION_OPS_RECONCILE", "false")
    agent2 = SessionOpsReconcileAgent(db_pool=object())
    await agent2.start()
    assert agent2._running is False


@pytest.mark.asyncio
async def test_apply_event_matches_google_event_id_without_private_props():
    from app.services.google_calendar_sync_agent import GoogleCalendarSyncAgent

    class _Conn:
        def __init__(self):
            self.sql = ""
            self.args = None

        async def fetchrow(self, sql, *args):
            self.sql = sql
            return {
                "session_id": "SES_WEST",
                "status": "scheduled",
                "google_etag": "old",
            }

        async def execute(self, sql, *args):
            self.args = (sql, args)

    class _Acquire:
        def __init__(self, conn):
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, *_a):
            return False

    class _Pool:
        def __init__(self, conn):
            self._conn = conn

        def acquire(self):
            return _Acquire(self._conn)

    conn = _Conn()
    agent = GoogleCalendarSyncAgent(db_pool=_Pool(conn))
    ev = {"id": "gcal-west", "etag": "new", "status": "cancelled"}
    ok = await agent._apply_event("COACH_COACHN_ID", ev, "primary")
    assert ok is True
    assert "google_event_id" in conn.sql
    assert conn.args[1][1] == "SES_WEST"
    assert "cancelled_by_google" in conn.args[0]


def test_hide_schedule_link_future_uses_cancel():
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "app" / "routers" / "sessions.py"
    text = src.read_text(encoding="utf-8")
    start = text.index("async def hide_schedule_link(")
    end = text.index("async def cancel_session(")
    chunk = text[start:end]
    assert "apply_coach_session_cancel" in chunk
    assert 'action="delete"' in chunk
