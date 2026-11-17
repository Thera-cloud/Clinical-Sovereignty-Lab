"""DOJO map, mentor lens, and new-coach payment-hold eligibility."""

from datetime import datetime, timedelta, timezone

import pytest

import json

from app.services.coach_dojo_access import active_dojo_keys, gate_mentor_start, patch_future_sessions
from app.services import coach_payment_hold as hold
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


def test_mentor_start_keeps_paid_keys_and_rejects_an_unpaid_list():
    profile = {"dojo_subscriptions": {"coach_nate": {"status": "active"}, "judge": {"status": "active"}}}
    allowed, err = gate_mentor_start(profile, ["therapist", "coach_nate"], blocked=["judge"])
    assert allowed == ["coach_nate"]
    assert err == ""
    allowed, err = gate_mentor_start(profile, ["therapist"])
    assert allowed == []
    assert err == "DOJO_NOT_SUBSCRIBED"
    allowed, err = gate_mentor_start({}, [])
    assert err == "DOJO_NOT_SUBSCRIBED"


class _FetchDb:
    def __init__(self):
        self.sql = []

    async def fetch(self, sql, *args):
        self.sql.append(sql)
        if "SELECT coach_username" in sql:
            return [{"coach_username": "NewCoach", "coach_hardware_id": "HW"}]
        return []

    async def execute(self, sql, *args):
        self.sql.append(sql)
        return "UPDATE 1"

    async def fetchval(self, sql, *args):
        return 1

    async def fetchrow(self, sql, *args):
        return None


@pytest.mark.asyncio
async def test_expire_without_coachn_locks_portal_and_does_not_mark_transferred(monkeypatch):
    async def missing(db):
        return None

    monkeypatch.setattr(hold, "_coachn", missing)
    db = _FetchDb()
    await hold._expire_due(db, "NewCoach")
    joined = "\n".join(db.sql)
    assert "status = 'expired'" in joined
    assert "transferred_at" not in joined


@pytest.mark.asyncio
async def test_expire_with_coachn_marks_transferred(monkeypatch):
    calls = []

    async def master(db):
        return {"username": "CoachN", "hardware_id": "HW_N", "email": "m@example.com", "phone": ""}

    async def transfer(db, username, hardware_id):
        calls.append(username)

    monkeypatch.setattr(hold, "_coachn", master)
    monkeypatch.setattr(hold, "_transfer_clients", transfer)
    db = _FetchDb()
    await hold._expire_due(db, "NewCoach")
    assert "transferred_at" in "\n".join(db.sql)
    assert calls == ["NewCoach"]


@pytest.mark.asyncio
async def test_login_flag_and_booking_notice_once(monkeypatch):
    class Db(_FetchDb):
        async def fetch(self, sql, *args):
            return []

        async def fetchrow(self, sql, *args):
            if "FROM users" in sql:
                return {"username": "NewCoach", "hardware_id": "HW"}
            if "coach_payment_holds" in sql:
                return {"status": "open"}
            return None

    sent = []

    async def send(to, subject, text):
        sent.append((to, subject, text))
        return True

    async def master(db):
        return {"username": "CoachN", "hardware_id": "HW_N", "email": "m@example.com", "phone": "+1"}

    monkeypatch.setattr(hold, "_send_email", send)
    monkeypatch.setattr(hold, "_coachn", master)
    hold._BOOKING_NOTICE_KEYS.clear()
    db = Db()
    fields = await hold.fields_for_login(db, {"role": "COACH", "username": "NewCoach"})
    assert fields["coach_payment_required"] is True
    assert await hold.message_locked(db, {"role": "COACH", "username": "NewCoach"}, "login_request") is False
    assert await hold.booking_blocked(db, "HW", "", "Pat", "Tuesday 3pm") is True
    assert await hold.booking_blocked(db, "HW", "", "Pat", "Tuesday 3pm") is True
    assert len(sent) == 1
    assert "Pat" in sent[0][2]


@pytest.mark.asyncio
async def test_failure_notice_emails_before_sms_and_docket_is_master_only(monkeypatch):
    order = []

    async def send(to, subject, text):
        order.append(("email", to, subject, text))
        return True

    def sms(phone, body):
        order.append(("sms", phone, body))

    async def master(db):
        return {"username": "CoachN", "hardware_id": "HW_N", "email": "master@example.com", "phone": "+1"}

    async def docket(db, username, hardware_id):
        return ["Pat — Tuesday"]

    class Db:
        async def execute(self, *args):
            return "UPDATE 1"

    monkeypatch.setattr(hold, "_send_email", send)
    monkeypatch.setattr(hold, "_sms", sms)
    monkeypatch.setattr(hold, "_coachn", master)
    monkeypatch.setattr(hold, "_docket_lines", docket)
    await hold._notify_opened(Db(), {
        "username": "NewCoach",
        "email": "coach@example.com",
        "phone": "+2",
        "hardware_id": "HW",
    }, "in_test")
    kinds = [item[0] for item in order]
    assert kinds.index("sms") > kinds.index("email")
    coach_mail = [item for item in order if item[0] == "email" and item[1] == "coach@example.com"]
    assert coach_mail and "Pat" not in coach_mail[0][3]
    docket_mail = [item for item in order if item[2] == "Assistant coach schedule"]
    assert docket_mail and docket_mail[0][1] == "master@example.com" and "Pat" in docket_mail[0][3]
    assert all("Pat" not in item[2] for item in order if item[0] == "sms")


@pytest.mark.asyncio
async def test_manual_invoice_does_not_open_a_hold():
    class Boom:
        async def fetchrow(self, *args):
            raise AssertionError("manual invoice must not query users")

    await hold.open_hold_from_invoice(Boom(), {"id": "in_manual"}, "user-id")


@pytest.mark.asyncio
async def test_paid_return_patches_sessions_file(tmp_path, monkeypatch):
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    path = tmp_path / "sessions.json"
    path.write_text(json.dumps([{
        "coach_id": "HW_MASTER",
        "hold_from": "newcoach",
        "scheduled_start": future,
        "status": "scheduled",
        "zoom_link": "https://zoom.example/a",
    }]))

    class Db:
        def __init__(self):
            self.cleared = None

        async def fetch(self, sql):
            return [{
                "id": 7,
                "session_sync": "return",
                "coach_username": "newcoach",
                "coach_hardware_id": "HW_NEW",
            }]

        async def execute(self, sql, ids):
            self.cleared = list(ids)

    async def master(db):
        return {"username": "CoachN", "hardware_id": "HW_MASTER", "email": "m@example.com", "phone": ""}

    monkeypatch.setattr(hold, "_coachn", master)
    db = Db()
    await hold.sync_hold_sessions(db, str(path))
    saved = json.loads(path.read_text())
    assert saved[0]["coach_id"] == "HW_NEW"
    assert "hold_from" not in saved[0]
    assert saved[0]["zoom_link"] == "https://zoom.example/a"
    assert db.cleared == [7]
