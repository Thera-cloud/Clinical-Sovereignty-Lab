"""Offline Extra-fail pack: Zoom PATCH, zoom COALESCE, voice keys, signup ledger-first, billing 38."""

from unittest.mock import AsyncMock

import pytest

from app.services.billing_auditor import TAB_ENDPOINTS
from app.services.voice_billing import next_voice_extend_idempotency_key
from app.services.zoom_client import ZoomClient, zoom_start_differs


def test_zoom_start_differs_minute_utc():
    assert zoom_start_differs("2026-11-02T23:00:00Z", "2026-11-02T23:00:00+00:00") is False
    assert zoom_start_differs("2026-11-02T23:00:00Z", "2026-11-02T23:30:00Z") is True
    assert zoom_start_differs("", "2026-11-02T23:00:00Z") is True
    assert zoom_start_differs("2026-11-02T23:00:00Z", "") is False


@pytest.mark.asyncio
async def test_ensure_patches_when_start_differs():
    z = ZoomClient("acct", "cid", "csec")
    z.get_meeting = AsyncMock(return_value={
        "id": 96875254329,
        "join_url": "https://zoom.us/j/96875254329",
        "start_url": "https://zoom.us/s/96875254329?zak=old",
        "status": "waiting",
        "start_time": "2026-11-02T23:00:00Z",
    })
    z.update_meeting = AsyncMock(return_value={"start_time": "2026-11-02T23:30:00Z"})
    z.get_zak_token = AsyncMock(return_value="freshzak")
    z.create_meeting = AsyncMock()
    out = await z.ensure_scheduled_meeting(
        meeting_id="96875254329",
        topic="Coaching Session",
        start_time_iso="2026-11-02T23:30:00Z",
        duration_minutes=50,
        allow_time_patch=True,
    )
    z.update_meeting.assert_awaited_once()
    z.create_meeting.assert_not_called()
    assert out["recreated"] is False
    assert out["start_url"].endswith("zak=freshzak")


@pytest.mark.asyncio
async def test_ensure_skips_patch_when_shared_meeting():
    z = ZoomClient("acct", "cid", "csec")
    z.get_meeting = AsyncMock(return_value={
        "id": 1,
        "join_url": "https://zoom.us/j/1",
        "start_url": "https://zoom.us/s/1?zak=old",
        "status": "waiting",
        "start_time": "2026-11-02T23:00:00Z",
    })
    z.update_meeting = AsyncMock()
    z.get_zak_token = AsyncMock(return_value="freshzak")
    out = await z.ensure_scheduled_meeting(
        meeting_id="1",
        topic="Coaching Session",
        start_time_iso="2026-11-02T23:30:00Z",
        duration_minutes=50,
        allow_time_patch=False,
    )
    z.update_meeting.assert_not_called()
    assert out["recreated"] is False


@pytest.mark.asyncio
async def test_ensure_recreates_when_patch_says_deleted():
    z = ZoomClient("acct", "cid", "csec")
    z.get_meeting = AsyncMock(return_value={
        "id": 9,
        "join_url": "https://zoom.us/j/9",
        "start_url": "https://zoom.us/s/9",
        "status": "waiting",
        "start_time": "2026-11-02T23:00:00Z",
    })
    z.update_meeting = AsyncMock(return_value={"code": 3001, "deleted": True})
    z.create_meeting = AsyncMock(return_value={
        "id": 111,
        "join_url": "https://zoom.us/j/111",
        "start_url": "https://zoom.us/s/111?zak=new",
        "status": "waiting",
    })
    out = await z.ensure_scheduled_meeting(
        meeting_id="9",
        topic="Coaching Session",
        start_time_iso="2026-11-02T23:30:00Z",
        duration_minutes=50,
    )
    assert out["recreated"] is True
    assert out["id"] == "111"


def test_zoom_link_coalesce_in_upsert_sql():
    from app.services import pg_data_helpers as pg
    src = open(pg.__file__).read()
    assert "COALESCE(NULLIF(EXCLUDED.zoom_link, ''), coaching_sessions.zoom_link)" in src
    assert "COALESCE(NULLIF(EXCLUDED.zoom_meeting_id, ''), coaching_sessions.zoom_meeting_id)" in src
    assert "COALESCE(NULLIF(EXCLUDED.zoom_host_url, ''), coaching_sessions.zoom_host_url)" in src


def test_voice_extend_idempotency_increments_per_block():
    a = next_voice_extend_idempotency_key("SES_1", 0)
    b = next_voice_extend_idempotency_key("SES_1", 1)
    assert a == "voice-ext-SES_1-1"
    assert b == "voice-ext-SES_1-2"
    assert a != b


def test_billing_auditor_has_41_checks():
    total = sum(len(t["endpoints"]) for t in TAB_ENDPOINTS)
    assert total == 41
    db = [ep for t in TAB_ENDPOINTS for ep in t["endpoints"] if ep[0] == "DB"]
    assert ("DB", "unpaid_48h_queryable") in db
    assert ("DB", "charge_verify_fail_queryable") in db
    assert ("DB", "unconfirmed_in_window_queryable") in db
    assert ("DB", "paid_missing_zoom") in db
    assert ("DB", "occupancy_overlap") in db
    assert ("DB", "paid_not_scheduled") in db


def test_signup_sharing_inserts_pending_before_transfer():
    from app.services import signup_sharing_agent as ssa
    src = open(ssa.__file__).read()
    assert "if existing and str(existing[\"status\"] or \"\") == \"completed\":" in src
    assert "None, \"pending\", source_note" in src or "None, 'pending'" in src
    assert 'idempotency_key=f"share-{code_id}-{entity_id}-{period_start}"' in src
    assert "SET stripe_transfer_id = $1, status = 'completed'" in src


def test_recording_status_reads_pg_first():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app" / "routers" / "sessions.py").read_text()
    fn = src.split("async def get_recording_status", 1)[1].split("\nasync def ", 1)[0]
    assert "load_sessions_pg" in fn
    assert "session_id=session_id" in fn


@pytest.mark.asyncio
async def test_confirm_session_for_user_matches_login_alias():
    from app.services.session_confirm import confirm_session_for_user

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "id": "uuid-1",
        "session_id": "SES_X",
        "client_id": "CLIENT_HW",
        "coach_id": "COACH_X",
        "client_name": "A",
        "client_confirmed_at": None,
        "status": "scheduled",
        "scheduled_at": "2026-11-10T15:00:00+00:00",
        "coach_email": "c@x",
        "coach_name": "C",
    })
    conn.fetch = AsyncMock(return_value=[{"hardware_id": "CLIENT_HW", "username": "alice"}])
    conn.execute = AsyncMock()
    out = await confirm_session_for_user(conn, "SES_X", username="alice", hardware_id="")
    assert out["ok"] is True
    conn.execute.assert_awaited()


@pytest.mark.asyncio
async def test_confirm_session_for_user_rejects_other_client():
    from app.services.session_confirm import confirm_session_for_user

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "id": "uuid-1",
        "session_id": "SES_X",
        "client_id": "OTHER",
        "coach_id": "COACH_X",
        "client_name": "A",
        "client_confirmed_at": None,
        "status": "scheduled",
        "scheduled_at": "",
        "coach_email": "",
        "coach_name": "",
    })
    conn.fetch = AsyncMock(return_value=[{"hardware_id": "ME", "username": "me"}])
    conn.execute = AsyncMock()
    out = await confirm_session_for_user(conn, "SES_X", username="me", hardware_id="ME")
    assert out["ok"] is False
    conn.execute.assert_not_called()


def test_billing_auditor_does_not_probe_public_confirm_get():
    paths = [ep[1] for t in TAB_ENDPOINTS for ep in t["endpoints"]]
    assert "/api/billing/session-confirm" not in paths
    assert "/api/billing/sessions/confirm" not in paths


def test_classroom_family_id_copies_from_session():
    from app.services import pg_data_helpers as pg
    src = open(pg.__file__).read()
    assert "SELECT family_id FROM coaching_sessions WHERE session_id = $1" in src
