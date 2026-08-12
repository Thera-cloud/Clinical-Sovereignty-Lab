"""Offline unit tests: live session date preferred over SES_* booking stamp."""

from datetime import datetime, timezone

from app.services.zoom_transcript_context import (
    resolve_live_session_display,
    session_id_calendar_label,
)


def test_session_id_calendar_label_booking_stamp():
    assert session_id_calendar_label("SES_20260807_9BF92B") == "Aug 07, 2026"


def test_live_date_beats_session_id_booking_stamp():
    live = datetime(2026, 8, 12, 11, 0, tzinfo=timezone.utc)
    out = resolve_live_session_display(
        actual_start=live,
        scheduled_start=live,
        session_id="SES_20260807_9BF92B",
    )
    assert out["live_label"] == "Aug 12, 2026"
    assert out["booking_label"] == "Aug 07, 2026"
    assert out["date_slug"] == "2026-08-12"
    assert "Aug 12, 2026" in (out["display_label"] or "")
    assert "booked" in (out["display_label"] or "").lower()
    assert not (out["display_label"] or "").startswith("Aug 07")


def test_metadata_live_session_date_used_when_no_actual():
    out = resolve_live_session_display(
        session_id="SES_20260807_9BF92B",
        metadata={"live_session_date": "2026-08-12"},
        archive_created_at=datetime(2026, 8, 12, 12, 12, tzinfo=timezone.utc),
    )
    assert out["live_label"] == "Aug 12, 2026"
    assert out["date_slug"] == "2026-08-12"
