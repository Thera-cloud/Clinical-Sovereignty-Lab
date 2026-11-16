"""DOJO map, mentor lens, and new-coach payment-hold eligibility."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.coach_dojo_access import active_dojo_keys, patch_future_sessions
from app.services.coach_payment_hold import eligible
from app.services.dojo_mentor_engine import (
    DojoMentorEngine,
    DojoMentorUnavailable,
    VALID_DOJOS,
)


def test_missing_map_shows_no_dojos():
    assert active_dojo_keys({}) == []
    assert active_dojo_keys({"dojo_subscriptions": {}}) == []


def test_selected_dojos_remain_when_the_map_is_absent():
    assert active_dojo_keys({"selected_dojos": ["judge", "cnc"]}) == ["judge", "cnc"]


def test_cancelled_dojo_stays_until_access_end():
    later = (datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat()
    keys = active_dojo_keys({
        "dojo_subscriptions": {
            "teacher": {"status": "cancelled", "access_end_date": later},
            "mcat": {"status": "expired"},
        }
    })
    assert keys == ["teacher"]


def test_blocked_dojo_hides_while_the_others_stay():
    keys = active_dojo_keys(
        {"dojo_subscriptions": {"therapist": {"status": "active"}, "judge": {"status": "active"}}},
        blocked=["therapist"],
    )
    assert keys == ["judge"]


def test_coach_nate_is_a_mentor_lens_and_empty_does_not_become_therapist():
    assert "coach_nate" in VALID_DOJOS
    engine = DojoMentorEngine(None)
    prompt = engine.build_mentor_system_prompt(["coach_nate"], {}, "coach_client")
    assert "board-certified psychiatrist" not in prompt
    assert "master coach" in prompt
    with pytest.raises(DojoMentorUnavailable):
        engine.build_mentor_system_prompt([], {}, "coach_client")
    with pytest.raises(DojoMentorUnavailable):
        engine.build_mentor_system_prompt(["not_a_dojo"], {}, "coach_client")


def test_hold_eligibility_skips_existing_clients_and_coachn():
    flagged = {"coach_payment_hold_eligible": True}
    assert eligible(flagged, "NewCoach", "COACH", "ACTIVE")
    assert not eligible(flagged, "CoachN", "COACH", "ACTIVE")
    assert not eligible(flagged, "NewCoach", "CLIENT", "ACTIVE")
    assert not eligible(flagged, "NewCoach", "COACH", "PENDING_VERIFICATION")
    assert not eligible({}, "OldCoach", "COACH", "ACTIVE")


def test_future_session_moves_and_a_started_session_stays():
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    sessions = [
        {"session_id": "future", "coach_id": "COACH_A", "status": "scheduled", "scheduled_start": future, "zoom_link": "https://zoom.example/a"},
        {"session_id": "live", "coach_id": "COACH_A", "status": "scheduled", "scheduled_start": past, "actual_start": past},
        {"session_id": "other", "coach_id": "COACH_B", "status": "scheduled", "scheduled_start": future},
    ]
    assert patch_future_sessions(sessions, ["COACH_A"], "COACH_COACHN_ID")
    moved = sessions[0]
    assert moved["coach_id"] == "COACH_COACHN_ID"
    assert moved["zoom_link"] == ""
    assert moved["hold_from"] == "COACH_A"
    assert sessions[1]["coach_id"] == "COACH_A"
    assert sessions[2]["coach_id"] == "COACH_B"
    assert patch_future_sessions(
        sessions, ["COACH_COACHN_ID"], "COACH_A", restore_from="COACH_A",
    )
    assert sessions[0]["coach_id"] == "COACH_A"
    assert "hold_from" not in sessions[0]
