"""Unit tests for session financial obligation + fee helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.session_financial_records import (
    platform_fee_cents_from_session,
    record_approval_obligation,
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


def test_platform_fee_from_session_data():
    row = {"session_data": {"platform_fee": 52.5}}
    assert platform_fee_cents_from_session(row, 17500) == 5250


def test_platform_fee_fallback_30_pct():
    assert platform_fee_cents_from_session({"session_data": {}}, 10000) == 3000


@pytest.mark.asyncio
async def test_record_approval_obligation_writes_event():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        side_effect=[
            # client PM lookup
            {
                "stripe_customer_id": "cus_x",
                "pd_cid": "cus_x",
                "default_pm": "pm_abc",
            },
            # session row
            {"id": "uuid-1", "session_data": {}},
        ]
    )
    conn.fetchval = AsyncMock(return_value=None)
    conn.execute = AsyncMock()
    pool = _MockPool(conn)

    ok = await record_approval_obligation(
        pool,
        {
            "session_id": "SES_TEST",
            "client_id": "CLIENT_X",
            "coach_id": "COACH_Y",
            "client_name": "Test",
            "coach_fee": 175,
            "platform_fee": 52.5,
            "coach_payout": 122.5,
            "price_cents": 17500,
            "approved_at": "2026-08-07T19:11:35",
        },
        approved_by="CoachN",
    )
    assert ok is True
    assert conn.execute.await_count >= 2
    # second execute is obligation_created insert
    insert_sql = conn.execute.await_args_list[-1].args[0]
    assert "obligation_created" in insert_sql
