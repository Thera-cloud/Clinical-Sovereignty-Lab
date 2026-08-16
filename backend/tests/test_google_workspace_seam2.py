"""Seam 2: B1 Google free/busy into LN slots; B2 no tentative Google holds."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.services.coach_slot_engine import compute_available_slots
from app.services.google_calendar_session_sync import (
    _HW_TO_USERNAME_CACHE,
    _get_connection,
    _hardware_id_to_username,
    _oauth_client_for,
    is_pending_google_hold,
    sync_session_to_google,
)

_TZ = ZoneInfo("America/New_York")
_BUSY_START = datetime(2027, 6, 14, 10, 0, tzinfo=_TZ)
_BUSY_END = datetime(2027, 6, 14, 11, 0, tzinfo=_TZ)


class _SlotConn:
    async def fetchval(self, sql, *args):
        if "SELECT id FROM users" in sql:
            return "uuid-coach"
        if "specific_date" in sql:
            return None
        if "SELECT username FROM users" in sql:
            return "CoachN"
        return None

    async def fetch(self, sql, *args):
        if "FROM coach_availability" in sql:
            return [{
                "day_of_week": 0,
                "start_time": "09:00:00",
                "end_time": "12:00:00",
            }]
        if "FROM coaching_sessions" in sql:
            return []
        if "FROM google_external_busy" in sql:
            return [{"start_at": _BUSY_START, "end_at": _BUSY_END}]
        return []


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def acquire(self):
        return _Acquire(_SlotConn())


def test_pending_hold_predicate():
    assert is_pending_google_hold({"status": "pending_approval"}) is True
    assert is_pending_google_hold({"status": "PENDING_APPROVAL"}) is True
    assert is_pending_google_hold({"status": "scheduled"}) is False
    assert is_pending_google_hold({"status": "confirmed"}) is False
    assert is_pending_google_hold(None) is False


@pytest.mark.asyncio
async def test_pending_create_skips_google_connection():
    with patch(
        "app.services.google_calendar_session_sync._get_connection",
        new_callable=AsyncMock,
    ) as get_conn:
        out = await sync_session_to_google(
            MagicMock(),
            "CoachN",
            {"session_id": "SES_P", "status": "pending_approval"},
            action="create",
        )
    assert out == {"status": "skipped", "reason": "pending_no_google_hold"}
    get_conn.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_update_skips_google_connection():
    with patch(
        "app.services.google_calendar_session_sync._get_connection",
        new_callable=AsyncMock,
    ) as get_conn:
        out = await sync_session_to_google(
            MagicMock(),
            "CoachN",
            {"session_id": "SES_P", "status": "pending_approval"},
            action="update",
        )
    assert out["reason"] == "pending_no_google_hold"
    get_conn.assert_not_awaited()


class _FetchPool:
    def __init__(self, handler):
        self._handler = handler

    def acquire(self):
        return _Acquire(_FetchConn(self._handler))


class _FetchConn:
    def __init__(self, handler):
        self._handler = handler

    async def fetchrow(self, sql, *args):
        return self._handler(sql, *args)


@pytest.mark.asyncio
async def test_get_connection_falls_back_to_workspace():
    def handler(sql, *args):
        if "google_calendar_connection" in sql:
            return None
        if "google_workspace_connection" in sql:
            return {
                "user_id": "CoachX",
                "access_token": "enc",
                "refresh_token": "encr",
                "token_expiry": None,
                "target_calendar_id": "primary",
                "sync_enabled": True,
                "token_app": "workspace_ws",
            }
        return None

    row = await _get_connection(_FetchPool(handler), "CoachX")
    assert row["token_app"] == "workspace_ws"
    assert row["_token_table"] == "google_workspace_connection"


@pytest.mark.asyncio
async def test_get_connection_prefers_enabled_183():
    def handler(sql, *args):
        if "google_calendar_connection" in sql:
            return {
                "user_id": "CoachN",
                "access_token": "a",
                "refresh_token": "b",
                "token_expiry": None,
                "target_calendar_id": "primary",
                "sync_enabled": True,
                "token_app": "calendar_183",
            }
        raise AssertionError("workspace lookup should not run when 183 is enabled")

    row = await _get_connection(_FetchPool(handler), "CoachN")
    assert row["token_app"] == "calendar_183"
    assert row["_token_table"] == "google_calendar_connection"


def test_oauth_client_splits_183_and_workspace(monkeypatch):
    import app.services.google_calendar_session_sync as gcss

    monkeypatch.setattr(gcss, "GOOGLE_CLIENT_ID", "cal-id")
    monkeypatch.setattr(gcss, "GOOGLE_CLIENT_SECRET", "cal-sec")
    monkeypatch.setattr(gcss, "GOOGLE_WS_CLIENT_ID", "ws-id")
    monkeypatch.setattr(gcss, "GOOGLE_WS_CLIENT_SECRET", "ws-sec")
    assert _oauth_client_for({"token_app": "calendar_183"}) == ("cal-id", "cal-sec")
    assert _oauth_client_for({"token_app": "workspace_ws"}) == ("ws-id", "ws-sec")


@pytest.mark.asyncio
async def test_username_or_hardware_id_resolves():
    _HW_TO_USERNAME_CACHE.clear()

    def handler(sql, *args):
        assert "username = $1" in sql
        assert args[0] == "CoachN"
        return {"username": "CoachN"}

    assert await _hardware_id_to_username(_FetchPool(handler), "CoachN") == "CoachN"


@pytest.mark.asyncio
async def test_scheduled_create_looks_up_connection():
    with patch(
        "app.services.google_calendar_session_sync._get_connection",
        new_callable=AsyncMock,
        return_value=None,
    ) as get_conn:
        out = await sync_session_to_google(
            MagicMock(),
            "CoachN",
            {"session_id": "SES_OK", "status": "scheduled"},
            action="create",
        )
    assert out is None
    get_conn.assert_awaited_once()


@pytest.mark.asyncio
async def test_freebusy_masks_ln_slots_without_registry_loader():
    engine = await compute_available_slots(
        _Pool(), "COACH_COACHN_ID", "2027-06-14",
    )
    assert engine.get("error") is None
    starts = [s["start"] for s in engine["available_slots"]]
    google_busy = [b for b in engine["booked_slots"] if b.get("source") == "google"]
    assert google_busy
    assert any("T10:00" in s for s in [b["start"] for b in google_busy])
    assert not any("T10:00" in s for s in starts)
    assert any("T09:00" in s for s in starts)
    assert any("T11:00" in s for s in starts)
