"""Seam 1: vault_sync redaction, B4 no client attendees, Meet conferenceData."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.google_calendar_client import _event_url
from app.services.google_calendar_session_sync import (
    _build_payload,
    compose_session_event_payload,
)
from app.services.google_workspace_service import get_google_svc

_SESSION = {
    "session_id": "SES_SEAM1",
    "client_id": "CLIENT_PAULA182_ID",
    "client_name": "Paula Swain",
    "coach_id": "COACH_COACHN_ID",
    "coach_name": "CoachN",
    "session_type": "session",
    "scheduled_start": "2026-08-20T14:00:00+00:00",
    "scheduled_end": "2026-08-20T15:00:00+00:00",
    "zoom_join_url": "https://zoom.us/j/999",
    "consultation_email": "guest@example.com",
}


def test_event_url_sets_conference_data_version():
    url = _event_url("primary", "evt1", conference_data=True)
    assert "conferenceDataVersion=1" in url
    create_url = _event_url("primary", conference_data=True)
    assert "conferenceDataVersion=1" in create_url


def test_vault_sync_false_redacts_title_description_attendees():
    payload = compose_session_event_payload(_SESSION, vault_sync=False)
    assert payload is not None
    assert payload["summary"] == "Session — PS"
    assert not (payload.get("description") or "").strip()
    assert not payload.get("attendees")
    assert "Paula" not in payload["summary"]
    assert "guest@example.com" not in str(payload)
    assert payload["conferenceData"]["createRequest"]["conferenceSolutionKey"]["type"] == (
        "hangoutsMeet"
    )
    req_id = payload["conferenceData"]["createRequest"]["requestId"]
    assert len(req_id) == 36
    assert "Paula" not in req_id


def test_vault_sync_true_keeps_names_but_no_client_attendee():
    payload = compose_session_event_payload(_SESSION, vault_sync=True)
    assert payload is not None
    assert "Paula Swain" in payload["summary"]
    emails = [a["email"] for a in (payload.get("attendees") or [])]
    assert emails == ["guest@example.com"]
    assert "CLIENT_PAULA182_ID" not in emails
    assert payload["conferenceData"]["createRequest"]["conferenceSolutionKey"]["type"] == (
        "hangoutsMeet"
    )
    assert "https://zoom.us/j/999" in (payload.get("description") or "")


def test_build_payload_ignores_client_email_attendee():
    payload = _build_payload(
        _SESSION,
        extra_attendee_email="paula@example.com",
        vault_sync=False,
    )
    assert not payload.get("attendees")
    assert "paula@example.com" not in str(payload)


@pytest.mark.asyncio
async def test_google_svc_upsert_wires_sync(monkeypatch):
    monkeypatch.setenv("ENABLE_WS_CALENDAR_SYNC", "true")
    row = {
        "session_id": "SES_SEAM1",
        "client_id": "CLIENT_PAULA182_ID",
        "coach_id": "COACH_COACHN_ID",
        "client_name": "Paula Swain",
        "session_type": "session",
        "status": "scheduled",
        "scheduled_start": "2026-08-20T14:00:00+00:00",
        "scheduled_end": "2026-08-20T15:00:00+00:00",
        "zoom_link": "https://zoom.us/j/999",
        "zoom_meeting_id": "999",
        "notes": "",
        "google_event_id": None,
        "google_etag": None,
        "google_calendar_id": None,
        "sync_state": "unsynced",
        "consultation_email": None,
        "session_data": {},
    }
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=[row, {"username": "CoachN"}])
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=conn)
    acquire.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = acquire
    svc = get_google_svc(db_pool=pool)
    with patch(
        "app.services.google_calendar_session_sync.sync_session_to_google",
        new_callable=AsyncMock,
        return_value={"status": "ok", "event_id": "gcal_1"},
    ) as sync:
        out = await svc.calendar.upsertSession("COACH_COACHN_ID", "SES_SEAM1")
    assert out["ok"] is True
    assert out["action"] == "create"
    sync.assert_awaited_once()
    args = sync.await_args.args
    assert args[1] == "CoachN"
    assert args[2]["session_id"] == "SES_SEAM1"
    assert sync.await_args.kwargs.get("action") == "create"


@pytest.mark.asyncio
async def test_google_svc_remove_wires_delete(monkeypatch):
    monkeypatch.setenv("ENABLE_WS_CALENDAR_SYNC", "true")
    row = {
        "session_id": "SES_SEAM1",
        "client_id": "CLIENT_X",
        "coach_id": "COACH_COACHN_ID",
        "client_name": "X",
        "session_type": "session",
        "status": "cancelled",
        "scheduled_start": "2026-08-20T14:00:00+00:00",
        "scheduled_end": "2026-08-20T15:00:00+00:00",
        "zoom_link": "",
        "zoom_meeting_id": "",
        "notes": "",
        "google_event_id": "evt_del",
        "google_etag": None,
        "google_calendar_id": "primary",
        "sync_state": "synced",
        "consultation_email": None,
        "session_data": {},
    }
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=[row, {"username": "CoachN"}])
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=conn)
    acquire.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = acquire
    svc = get_google_svc(db_pool=pool)
    with patch(
        "app.services.google_calendar_session_sync.sync_session_to_google",
        new_callable=AsyncMock,
        return_value={"status": "ok"},
    ) as sync:
        out = await svc.calendar.removeSession("COACH_COACHN_ID", "SES_SEAM1")
    assert out["ok"] is True
    assert sync.await_args.kwargs.get("action") == "delete"
