"""Regression tests: coach-scheduled sessions must not auto-cancel on creation time."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import pg_data_helpers
from app.services.session_payment_agent import (
    SessionPaymentAgent,
    _APPT_TIME,
    _APPT_TIME_BARE,
    _NOT_CANCELLED,
    _NOT_CANCELLED_BARE,
)


class _AsyncCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return False


class _MockPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AsyncCtx(self._conn)


@pytest.mark.asyncio
async def test_upsert_session_pg_syncs_scheduled_at_and_payment_windows():
    conn = AsyncMock()
    pool = _MockPool(conn)
    start = datetime(2026, 5, 22, 17, 0, tzinfo=timezone.utc)

    ok = await pg_data_helpers.upsert_session_pg(
        pool,
        {
            "session_id": "SES_TEST_SCHED_SYNC",
            "client_id": "CLIENT_ZACKS99_ID",
            "coach_id": "COACH_COACHN_ID",
            "scheduled_start": start.isoformat(),
            "scheduled_end": (start + timedelta(minutes=50)).isoformat(),
            "status": "scheduled",
            "payment_status": "pending",
            "price_cents": 0,
        },
    )

    assert ok is True
    conn.execute.assert_awaited_once()
    sql = conn.execute.await_args.args[0]
    assert "scheduled_at" in sql
    assert "payment_due_at" in sql
    assert "cancellation_deadline" in sql
    assert "COALESCE(EXCLUDED.scheduled_start, EXCLUDED.scheduled_at)" in sql

    params = conn.execute.await_args.args[1:]
    assert params[7] == start  # scheduled_start
    assert params[9] == start  # scheduled_at mirrors start
    assert params[10] == start - timedelta(hours=72)
    assert params[11] == start - timedelta(hours=24)


@pytest.mark.asyncio
async def test_payment_agent_overdue_query_uses_appointment_time_and_price_guard():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()

    pool = _MockPool(conn)
    agent = SessionPaymentAgent(db_pool=pool, app_state=None)
    await agent._run_one_cycle()

    overdue_fetch = next(
        (call for call in conn.fetch.await_args_list
         if "COALESCE(scheduled_start, scheduled_at) <=" in call.args[0]),
        None,
    )
    assert overdue_fetch is not None
    sql = overdue_fetch.args[0]
    assert _APPT_TIME_BARE in sql
    assert "COALESCE(price_cents, 0) > 0" in sql
    assert _NOT_CANCELLED_BARE in sql
    assert "scheduled_at <" not in sql.replace(_APPT_TIME_BARE, "")


def test_payment_agent_sql_constants_use_coalesce():
    assert "scheduled_start" in _APPT_TIME
    assert "scheduled_at" in _APPT_TIME
    assert _NOT_CANCELLED == "UPPER(cs.status) != 'CANCELLED'"


@pytest.mark.asyncio
async def test_payment_agent_does_not_cancel_free_coach_booking():
    """Future appt + pending + price_cents=0: overdue SELECT must return no rows."""
    conn = AsyncMock()
    captured = []

    async def _fetch(sql, *args):
        captured.append(sql)
        if "payment_status = 'pending'" in sql and "COALESCE(price_cents, 0) > 0" in sql:
            return []
        return []

    conn.fetch = _fetch
    conn.execute = AsyncMock()

    agent = SessionPaymentAgent(db_pool=_MockPool(conn), app_state=None)
    await agent._run_one_cycle()

    conn.execute.assert_not_awaited()
    assert any("COALESCE(price_cents, 0) > 0" in q for q in captured)


def test_calendar_pg_status_filter_is_case_insensitive():
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "app" / "websocket" / "bridge_handlers_v2.py"
    text = src.read_text(encoding="utf-8")
    assert "LOWER(status) IN ('scheduled', 'active', 'pending_approval')" in text
    assert '.lower() not in ["scheduled", "active", "pending_approval"]' in text
