import os
from datetime import datetime, timezone

os.environ.setdefault("SESSION_ACTION_SECRET", "test-calendar-secret")

from app.services.calendar_invite import (
    build_ics,
    build_invite,
    join_from_host_path,
    safe_join_url,
    sign_ics_token,
    verify_ics_token,
)


def test_safe_join_rejects_host_and_zak():
    assert safe_join_url("https://zoom.us/s/96875254329?zak=abc") == ""
    assert safe_join_url("https://zoom.us/j/123?zak=abc") == ""
    assert safe_join_url("https://zoom.us/j/12345678901") == "https://zoom.us/j/12345678901"


def test_join_from_host_path():
    assert join_from_host_path("https://zoom.us/s/96875254329?zak=secret") == "https://zoom.us/j/96875254329"


def test_ics_shape_and_no_zoom_location():
    start = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 14, 22, 50, tzinfo=timezone.utc)
    raw = build_ics(
        session_id="SES_TEST",
        summary="Sanctuary session with CoachN",
        start=start,
        end=end,
        description="notes\nhttps://zoom.us/j/111",
        join_url="https://zoom.us/j/111",
    ).decode()
    assert "BEGIN:VCALENDAR" in raw
    assert "METHOD:PUBLISH" in raw
    assert "UID:sanctuary-SES_TEST@sovereignsanctuary.net" in raw
    assert "DTSTART:20260914T220000Z" in raw
    assert "LOCATION:Sovereign Sanctuary session" in raw
    assert "zoom.us/s/" not in raw
    assert "zak=" not in raw


def test_google_and_outlook_hosts():
    invite = build_invite(
        session_id="SES_TEST",
        coach_name="CoachN",
        scheduled_start="2026-09-14T22:00:00+00:00",
        scheduled_end="2026-09-14T22:50:00+00:00",
        zoom_link="https://zoom.us/s/1?zak=no",
        zoom_host_url="https://zoom.us/s/96875254329?zak=no",
        client_id="CLIENT_X",
    )
    assert invite is not None
    assert "calendar.google.com" in invite.google_url
    assert "outlook.live.com" in invite.outlook_url
    assert invite.join_url == "https://zoom.us/j/96875254329"
    assert "zak=" not in invite.google_url
    assert "zoom.us/s/" not in invite.google_url


def test_ics_token_round_trip():
    token = sign_ics_token(session_id="SES_20260902_350590BF0CA5", client_id="CLIENT_X")
    parsed = verify_ics_token(token)
    assert parsed == {
        "session_id": "SES_20260902_350590BF0CA5",
        "client_id": "CLIENT_X",
    }
    assert verify_ics_token("nope") is None
    assert verify_ics_token(token[:-2] + "ff") is None
