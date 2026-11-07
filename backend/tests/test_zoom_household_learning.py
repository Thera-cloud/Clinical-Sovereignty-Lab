"""Offline checks for live-session household learning. No database."""

from app.services.zoom_household_learning import (
    canonical_zoom_meeting_id,
    status_after_end,
    status_after_start,
    summary_text_from_webhook,
)


def test_summary_completed_uses_meeting_id_not_object_id():
    payload = {
        "event": "meeting.summary_completed",
        "payload": {
            "object": {
                "uuid": "abc+def==",
                "meeting_id": 93452199625,
                "summary_overview": "The client felt anxious and wants support from the coach.",
                "summary_details": [
                    {"label": "Next", "summary": "Walk the plan with the coach."},
                ],
            }
        },
    }
    assert canonical_zoom_meeting_id(payload) == "93452199625"
    text = summary_text_from_webhook(payload)
    assert "anxious" in text
    assert "Walk the plan" in text
    assert "abc+def" not in text


def test_numeric_object_id_still_wins():
    payload = {"payload": {"object": {"id": "86805531601", "meeting_id": "1"}}}
    assert canonical_zoom_meeting_id(payload) == "86805531601"


def test_paid_session_completes_pending_stays_chargeable():
    assert status_after_start("scheduled") == "active"
    assert status_after_start("no_show") == "active"
    assert status_after_start("active") == "active"
    assert status_after_end("active", "paid") == "completed"
    assert status_after_end("no_show", "paid", has_end=True) == "completed"
    assert status_after_end("no_show", "paid", has_end=False) == "no_show"
    assert status_after_end("scheduled", "pending") == "active"
    assert status_after_end("cancelled", "pending") == "cancelled"
    assert status_after_end("completed", "paid") == "completed"


def test_parse_zoom_time():
    from app.services.zoom_household_learning import parse_zoom_time

    parsed = parse_zoom_time("2026-11-06T17:15:53Z")
    assert parsed is not None
    assert parsed.year == 2026
    assert parse_zoom_time("") is None


def test_uuid_session_extra_serializes():
    import json
    import uuid

    extra = {"family_uuid": uuid.UUID("11111111-1111-1111-1111-111111111111"), "price_cents": 9000}
    raw = json.dumps(extra, default=str)
    assert "11111111-1111-1111-1111-111111111111" in raw
    assert "9000" in raw
