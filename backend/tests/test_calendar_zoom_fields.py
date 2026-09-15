"""Offline: Schedule calendar must surface Zoom host URL from the PG column."""

from app.websocket.bridge_handlers_v2 import calendar_zoom_fields, overlay_calendar_zoom


def test_calendar_zoom_fields_prefers_column_over_empty_session_data():
    z = calendar_zoom_fields({
        "zoom_link": "https://zoom.us/j/99793663383?pwd=abc",
        "zoom_host_url": "https://zoom.us/s/99793663383?zak=host",
        "zoom_meeting_id": "99793663383",
        "session_data": {},
    })
    assert z["zoom_host_url"].startswith("https://zoom.us/s/")
    assert z["zoom_link"].startswith("https://zoom.us/j/")
    assert z["zoom_meeting_id"] == "99793663383"


def test_calendar_zoom_fields_falls_back_to_session_data():
    z = calendar_zoom_fields({
        "zoom_link": "",
        "zoom_host_url": "",
        "zoom_meeting_id": "",
        "session_data": {
            "zoom_link": "https://zoom.us/j/1",
            "zoom_host_url": "https://zoom.us/s/1",
            "zoom_meeting_id": "1",
        },
    })
    assert z["zoom_host_url"] == "https://zoom.us/s/1"


def test_overlay_calendar_zoom_fills_empty_json_row():
    schedule = [{
        "session_id": "SES_20260915_C94FF3",
        "zoom_link": "https://zoom.us/j/99793663383",
        "zoom_host_url": "",
        "zoom_meeting_id": "",
    }]
    overlay_calendar_zoom(schedule, "SES_20260915_C94FF3", {
        "zoom_link": "https://zoom.us/j/99793663383",
        "zoom_host_url": "https://zoom.us/s/99793663383?zak=host",
        "zoom_meeting_id": "99793663383",
    })
    assert schedule[0]["zoom_host_url"].startswith("https://zoom.us/s/")
    assert schedule[0]["zoom_meeting_id"] == "99793663383"
