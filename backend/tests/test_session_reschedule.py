"""Offline guards for coach Schedule reschedule + past lock."""

from datetime import datetime, timedelta, timezone

from app.services.session_reschedule import (
    build_new_session,
    duration_minutes,
    is_past_locked,
    mark_old_rescheduled,
    reschedule_guard,
)


NOW = datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)


def test_past_locked_after_start():
    assert is_past_locked("2026-09-17T12:00:00+00:00", NOW) is True
    assert is_past_locked("2026-09-21T14:00:00+00:00", NOW) is False


def test_guard_blocks_past_session():
    code, _ = reschedule_guard(
        {"status": "scheduled", "scheduled_start": "2026-09-17T08:00:00+00:00"},
        NOW + timedelta(days=4),
        now=NOW,
    )
    assert code == "past_locked"


def test_guard_allows_future_session():
    code, msg = reschedule_guard(
        {"status": "scheduled", "scheduled_start": "2026-09-21T14:00:00+00:00"},
        NOW + timedelta(days=5),
        now=NOW,
    )
    assert code is None
    assert msg is None


def test_mark_old_clears_zoom_and_sets_status():
    old = {
        "session_id": "SES_OLD",
        "status": "scheduled",
        "scheduled_start": "2026-09-21T14:00:00+00:00",
        "zoom_meeting_id": "123",
        "zoom_link": "https://zoom.us/j/1",
        "session_data": {},
    }
    mark_old_rescheduled(old, new_session_id="SES_NEW", actor="COACH_COACHN_ID", now=NOW)
    assert old["status"] == "rescheduled"
    assert old["zoom_meeting_id"] == ""
    assert old["session_data"]["rescheduled_to"] == "SES_NEW"


def test_new_session_links_from_old():
    old = {
        "session_id": "SES_OLD",
        "client_id": "CLIENT_PAULA182_ID",
        "coach_id": "COACH_COACHN_ID",
        "client_name": "Paula Swain",
        "session_type": "COACH",
        "status": "scheduled",
    }
    new = build_new_session(
        old,
        new_session_id="SES_NEW",
        scheduled_start="2026-09-21T14:00:00+00:00",
        scheduled_end="2026-09-21T14:50:00+00:00",
        actor="COACH_COACHN_ID",
        now=NOW,
    )
    assert new["status"] == "scheduled"
    assert new["rescheduled_from"] == "SES_OLD"
    assert new["client_id"] == "CLIENT_PAULA182_ID"


def test_duration_from_window():
    assert duration_minutes({
        "duration_minutes": 0,
        "scheduled_start": "2026-09-21T14:00:00+00:00",
        "scheduled_end": "2026-09-21T14:50:00+00:00",
    }) == 50


def test_reschedule_email_template_exists():
    from app.services.notifications_service import TEMPLATES, EmailService
    assert "coaching_rescheduled" in TEMPLATES
    assert hasattr(EmailService, "send_coaching_rescheduled")
