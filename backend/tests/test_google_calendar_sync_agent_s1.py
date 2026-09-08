"""S1: GCal pull parse (ISO str → datetime) + clone skip. Offline, no PG."""

from datetime import datetime, timezone, timedelta

import pytest

from app.services.google_calendar_sync_agent import (
    GoogleCalendarSyncAgent,
    parse_gcal_datetime,
)


def test_parse_offset_iso_cindy_repro():
    dt = parse_gcal_datetime("2026-09-07T19:00:00-04:00")
    assert isinstance(dt, datetime)
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timedelta(hours=-4)
    assert dt.year == 2026 and dt.month == 9 and dt.day == 7
    assert dt.hour == 19


def test_parse_zulu_and_space_and_passthrough():
    z = parse_gcal_datetime("2026-09-07T23:00:00Z")
    assert z.tzinfo is not None
    assert z.utcoffset() == timedelta(0)
    space = parse_gcal_datetime("2026-09-07 23:00:00+00:00")
    assert space.hour == 23
    already = datetime(2026, 9, 7, 19, 0, tzinfo=timezone.utc)
    assert parse_gcal_datetime(already) is already
    naive = parse_gcal_datetime(datetime(2026, 9, 7, 19, 0))
    assert naive.tzinfo is timezone.utc


def test_parse_rejects_empty():
    assert parse_gcal_datetime(None) is None
    assert parse_gcal_datetime("") is None
    assert parse_gcal_datetime("not-a-date") is None


class _FakeConn:
    def __init__(self):
        self.execute_args = None

    async def fetchrow(self, *_a, **_k):
        return {"session_id": "SES_S1", "status": "scheduled", "google_etag": "old"}

    async def execute(self, _sql, *args):
        self.execute_args = args


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_a):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


@pytest.mark.asyncio
async def test_apply_event_binds_datetime_not_str():
    conn = _FakeConn()
    agent = GoogleCalendarSyncAgent(db_pool=_FakePool(conn))
    ev = {
        "id": "gcal-1",
        "etag": "new",
        "status": "confirmed",
        "start": {"dateTime": "2026-09-07T19:00:00-04:00"},
        "end": {"dateTime": "2026-09-07T20:00:00-04:00"},
        "extendedProperties": {"private": {"sanctuary_session_id": "SES_S1"}},
    }
    ok = await agent._apply_event("COACH_AUDIT", ev, "primary")
    assert ok is True
    start_dt, end_dt, etag, session_id = conn.execute_args
    assert isinstance(start_dt, datetime) and not isinstance(start_dt, str)
    assert isinstance(end_dt, datetime) and not isinstance(end_dt, str)
    assert start_dt.utcoffset() == timedelta(hours=-4)
    assert etag == "new" and session_id == "SES_S1"


@pytest.mark.asyncio
async def test_clone_skip_does_not_start_loop(monkeypatch):
    monkeypatch.setenv("IS_CLONE", "true")
    agent = GoogleCalendarSyncAgent(db_pool=object())
    await agent.start()
    assert agent._running is False
    assert agent._task is None
