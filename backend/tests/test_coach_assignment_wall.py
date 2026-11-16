"""Coach Command isolation: assigned clients only, plus master → assistant."""

from app.services.coach_client_messenger import coach_can_see_client


def test_coach_sees_only_assigned_client():
    coach = {"role": "COACH", "hardware_id": "COACH_A_ID", "username": "CoachA"}
    mine = {
        "coach_id": "COACH_A_ID",
        "assigned_coach_id": "COACH_A_ID",
        "assigned_coach": "CoachA",
    }
    theirs = {
        "coach_id": "COACH_B_ID",
        "assigned_coach_id": "COACH_B_ID",
        "assigned_coach": "CoachB",
    }
    assert coach_can_see_client(coach, mine)
    assert not coach_can_see_client(coach, theirs)


def test_master_sees_assistant_clients_only():
    master = {"role": "COACH", "hardware_id": "COACH_M_ID", "username": "Master"}
    assistant_client = {
        "coach_id": "COACH_A_ID",
        "assigned_coach_id": "COACH_A_ID",
        "assigned_coach": "Assistant",
    }
    stranger = {"coach_id": "COACH_B_ID", "assigned_coach": "Other"}
    supervised = {"COACH_A_ID", "Assistant"}
    assert coach_can_see_client(master, assistant_client, supervised)
    assert not coach_can_see_client(master, assistant_client)
    assert not coach_can_see_client(master, stranger, supervised)


def test_assistant_does_not_inherit_master_caseload():
    assistant = {"role": "COACH", "hardware_id": "COACH_A_ID", "username": "Assistant"}
    master_client = {
        "coach_id": "COACH_M_ID",
        "assigned_coach_id": "COACH_M_ID",
        "assigned_coach": "Master",
    }
    assert not coach_can_see_client(assistant, master_client)
    assert not coach_can_see_client(assistant, master_client, set())


def test_admin_can_open_any_client():
    assert coach_can_see_client({"role": "ADMIN"}, {"coach_id": "COACH_B_ID"})
