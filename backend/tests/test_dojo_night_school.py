"""Night School entitlement and the two drill kinds. No network."""

from app.services.dojo_night_school import drill_preface, prepare_turn, stamp_active_dojos


def _coach(subs=None, selected=None):
    profile = {"role": "COACH", "username": "newcoach"}
    if subs is not None:
        profile["dojo_subscriptions"] = subs
    if selected is not None:
        profile["selected_dojos"] = selected
    return profile


def test_missing_map_keeps_selected_dojos():
    profile = _coach(selected=["teacher"])
    stamp_active_dojos(profile)
    assert profile["active_dojos"] == ["teacher"]


def test_expired_map_does_not_fall_back_to_selected():
    profile = _coach(
        subs={"therapist": {"status": "expired"}},
        selected=["judge", "therapist"],
    )
    stamp_active_dojos(profile, [])
    assert profile["active_dojos"] == []


def test_hold_block_removes_only_that_key():
    profile = _coach(subs={
        "therapist": {"status": "active"},
        "judge": {"status": "active"},
    })
    stamp_active_dojos(profile, ["judge"])
    assert profile["active_dojos"] == ["therapist"]


def test_admin_sees_every_night_school_mode():
    profile = {"role": "ADMIN"}
    stamp_active_dojos(profile)
    assert "judge" in profile["active_dojos"]
    assert "coach_nate" in profile["active_dojos"]


def test_unpaid_practice_is_rejected():
    result = prepare_turn(_coach(subs={"teacher": {"status": "active"}}), [], "judge", "practice", "Argue this.")
    assert result["error"] == "DOJO_NOT_SUBSCRIBED"


def test_practice_uses_the_supervisor_and_simulation_stays_a_drill():
    paid = _coach(subs={"therapist": {"status": "active"}})
    practice = prepare_turn(paid, [], "therapist", "practice", "What question should I ask?", "HOSTILE")
    simulation = prepare_turn(paid, [], "therapist", "simulation", "I don't trust you.", "HOSTILE")
    assert practice["error"] == ""
    assert practice["user_text"].startswith("[DOJO PRACTICE]")
    assert "Clinical Supervisor" in drill_preface(practice["user_text"])
    assert simulation["user_text"].startswith("[DOJO SIMULATION]")
    assert "Night School simulation" in drill_preface(simulation["user_text"])


def test_client_judge_needs_the_lawyer_flag():
    client = {"role": "CLIENT", "judge_dojo_access": False}
    assert prepare_turn(client, [], "judge", "practice", "Objection.")["error"] == "DOJO_NOT_SUBSCRIBED"
    client["judge_dojo_access"] = True
    assert prepare_turn(client, [], "judge", "simulation", "Objection.")["error"] == ""


def test_coach_nate_simulation_is_rejected():
    profile = _coach(subs={"coach_nate": {"status": "active"}})
    assert prepare_turn(profile, [], "coach_nate", "simulation", "Hello.")["error"] == "DOJO_NOT_SUBSCRIBED"
    practice = prepare_turn(profile, [], "coach_nate", "practice", "How was my question?")
    assert practice["error"] == ""
    assert "coaching skill" in drill_preface(practice["user_text"])
