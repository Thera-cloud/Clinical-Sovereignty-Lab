"""Offline: recreate deleted Zoom meetings and refresh host ZAK."""

from unittest.mock import AsyncMock

import pytest

from app.services.session_zoom_repair import (
    apply_zoom_result,
    user_can_access_session,
)
from app.services.zoom_client import (
    ZoomClient,
    host_start_url,
    parse_zoom_meeting_id,
)


def test_parse_zoom_meeting_id_from_join_and_host():
    assert parse_zoom_meeting_id("https://zoom.us/j/96875254329?pwd=abc") == "96875254329"
    assert parse_zoom_meeting_id("https://us05web.zoom.us/s/96875254329?zak=x") == "96875254329"
    assert parse_zoom_meeting_id("") == ""


def test_host_start_url():
    assert host_start_url("96875254329", "tok") == "https://zoom.us/s/96875254329?zak=tok"
    assert host_start_url("", "tok") == ""


@pytest.mark.asyncio
async def test_ensure_recreates_when_meeting_missing():
    z = ZoomClient("acct", "cid", "csec")
    z.get_meeting = AsyncMock(return_value=None)
    z.create_meeting = AsyncMock(return_value={
        "id": 11122233344,
        "join_url": "https://zoom.us/j/11122233344",
        "start_url": "https://zoom.us/s/11122233344?zak=new",
        "status": "waiting",
    })
    out = await z.ensure_scheduled_meeting(
        meeting_id="96875254329",
        topic="Coaching Session",
        start_time_iso="2026-11-02T23:00:00Z",
        duration_minutes=50,
    )
    assert out["recreated"] is True
    assert out["id"] == "11122233344"
    assert out["start_url"].endswith("zak=new")
    z.create_meeting.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_refreshes_zak_when_meeting_exists():
    z = ZoomClient("acct", "cid", "csec")
    z.get_meeting = AsyncMock(return_value={
        "id": 96875254329,
        "join_url": "https://zoom.us/j/96875254329",
        "start_url": "https://zoom.us/s/96875254329?zak=old",
        "status": "waiting",
    })
    z.get_zak_token = AsyncMock(return_value="freshzak")
    z.create_meeting = AsyncMock()
    out = await z.ensure_scheduled_meeting(
        meeting_id="96875254329",
        topic="Coaching Session",
        start_time_iso="2026-11-02T23:00:00Z",
        duration_minutes=50,
    )
    assert out["recreated"] is False
    assert out["start_url"] == "https://zoom.us/s/96875254329?zak=freshzak"
    z.create_meeting.assert_not_called()


def test_apply_zoom_result_bumps_ics_sequence_on_recreate():
    session = {"session_id": "SES_1", "session_data": {"ics_sequence": 2}}
    rec = apply_zoom_result(session, {
        "recreated": True,
        "id": "111",
        "join_url": "https://zoom.us/j/111?pwd=x",
        "start_url": "https://zoom.us/s/111?zak=z",
    })
    assert rec is True
    assert session["session_data"]["ics_sequence"] == 3
    assert session["zoom_link"].startswith("https://zoom.us/j/111")


def test_family_member_can_access_session():
    session = {"client_id": "CLIENT_A", "coach_id": "COACH_N", "family_id": "FAM_1"}
    assert user_can_access_session(
        {"role": "CLIENT", "hardware_id": "CLIENT_B", "family_id": "FAM_1"},
        session,
    )
    assert not user_can_access_session(
        {"role": "CLIENT", "hardware_id": "CLIENT_C", "family_id": "FAM_OTHER"},
        session,
    )
