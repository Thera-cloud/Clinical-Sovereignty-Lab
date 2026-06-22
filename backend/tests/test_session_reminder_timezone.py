"""Session reminder timezone formatting — Paula 12:00 UTC = 8:00 AM ET."""

from datetime import datetime, timezone

from app.utils.timezone_resolver import (
    DEFAULT_SESSION_TZ,
    format_session_start_for_profile,
)


def test_utc_noon_renders_as_8am_eastern_for_ny_profile():
    scheduled = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    text, tz_name = format_session_start_for_profile(
        scheduled,
        {"timezone": "America/New_York"},
    )
    assert tz_name == "America/New_York"
    assert "8:00 AM" in text
    assert "12:00 PM" not in text


def test_missing_timezone_defaults_to_eastern():
    scheduled = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    text, tz_name = format_session_start_for_profile(scheduled, {})
    assert tz_name == DEFAULT_SESSION_TZ
    assert "8:00 AM" in text


def test_naive_datetime_treated_as_utc():
    scheduled = datetime(2026, 6, 25, 12, 0)
    text, _tz = format_session_start_for_profile(
        scheduled,
        {"timezone": "America/New_York"},
    )
    assert "8:00 AM" in text


def test_invalid_timezone_falls_back_to_default():
    scheduled = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    _text, tz_name = format_session_start_for_profile(
        scheduled,
        {"timezone": "Not/A_Real_Zone"},
    )
    assert tz_name == DEFAULT_SESSION_TZ
