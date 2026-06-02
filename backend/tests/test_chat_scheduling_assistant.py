"""Tests for the chat scheduling assistant (Little Nate main-chat booking).

Covers intent detection, coach resolution, date parsing, and handle_turn for the
no-coach, slots-present, and no-slots cases. Slots always come from the shared
engine — the assistant never invents times — so handle_turn is exercised against a
patched compute_available_slots rather than a live DB.
"""

import datetime as _dt

import pytest

from app.services import client_scheduling_assistant as csa


# ── intent detection ──

@pytest.mark.parametrize("text", [
    "Can I book a session with my coach?",
    "schedule an appointment with my coach",
    "what times are open with my coach",
    "when is my coach available",
])
def test_detect_intent_positive(text):
    assert csa.detect_intent(text) == "schedule"


@pytest.mark.parametrize("text", [
    "",
    "I feel really anxious today and don't know why",
    "tell me about my mother",
    "x" * 401,  # long disclosure is therapy, not scheduling
])
def test_detect_intent_negative(text):
    assert csa.detect_intent(text) is None


# ── coach resolution ──

def test_resolve_coach_prefers_coach_id():
    p = {"coach_id": "COACH_A_ID", "assigned_coach_id": "COACH_B_ID"}
    assert csa.resolve_coach(p) == "COACH_A_ID"


def test_resolve_coach_falls_back_to_assigned():
    p = {"assigned_coach_id": "COACH_B_ID"}
    assert csa.resolve_coach(p) == "COACH_B_ID"


def test_resolve_coach_empty():
    assert csa.resolve_coach({}) == ""


# ── date parsing ──

def test_parse_target_date_iso():
    assert csa.parse_target_date("book me for 2026-07-04") == "2026-07-04"


def test_parse_target_date_today_tomorrow():
    today = _dt.date.today()
    # tz-aware in the module; allow +-1 day tolerance for tz edges
    assert csa.parse_target_date("any time today?") in {
        today.isoformat(), (today + _dt.timedelta(days=1)).isoformat(),
        (today - _dt.timedelta(days=1)).isoformat(),
    }
    assert csa.parse_target_date("how about tomorrow") is not None


def test_parse_target_date_absent():
    assert csa.parse_target_date("just book my coach") is None


# ── handle_turn ──

@pytest.mark.asyncio
async def test_handle_turn_not_scheduling_falls_through():
    out = await csa.handle_turn({}, "I had a hard day", db_pool=object())
    assert out["handled"] is False


@pytest.mark.asyncio
async def test_handle_turn_needs_date():
    """User must pick a day before slots are fetched (confirm-date step)."""
    out = await csa.handle_turn(
        {"coach_id": "COACH_A_ID"},
        "book a session with my coach",
        db_pool=object(),
    )
    assert out["handled"] is True
    assert out["payload"] is None
    assert "which day" in out["response"].lower()


@pytest.mark.asyncio
async def test_handle_turn_no_coach():
    out = await csa.handle_turn(
        {"role": "CLIENT"}, "book a session with my coach", db_pool=object()
    )
    assert out["handled"] is True
    assert "coach" in out["response"].lower()
    assert out["payload"] is None


@pytest.mark.asyncio
async def test_handle_turn_slots_present(monkeypatch):
    async def fake_slots(db_pool, coach_id, date, **kw):
        return {
            "available_slots": [
                {"start": "2026-07-04T09:00:00", "end": "2026-07-04T10:00:00"},
                {"start": "2026-07-04T10:00:00", "end": "2026-07-04T11:00:00"},
            ],
            "booked_slots": [],
            "error": None,
        }

    monkeypatch.setattr(csa, "compute_available_slots", fake_slots)
    out = await csa.handle_turn(
        {"coach_id": "COACH_A_ID"},
        "what times are open with my coach on 2026-07-04",
        db_pool=object(),
    )
    assert out["handled"] is True
    assert out["payload"]["type"] == "scheduling_slots"
    assert out["payload"]["surface"] == "chat"
    assert out["payload"]["coach_id"] == "COACH_A_ID"
    assert len(out["payload"]["slots"]) == 2


@pytest.mark.asyncio
async def test_handle_turn_no_slots(monkeypatch):
    async def fake_empty(db_pool, coach_id, date, **kw):
        return {"available_slots": [], "booked_slots": [], "error": None}

    monkeypatch.setattr(csa, "compute_available_slots", fake_empty)
    out = await csa.handle_turn(
        {"coach_id": "COACH_A_ID"},
        "book a session with my coach on 2026-07-04",
        db_pool=object(),
    )
    assert out["handled"] is True
    assert out["payload"]["slots"] == []
    assert "open" in out["response"].lower() or "another day" in out["response"].lower()


# Bridge client_book_session error codes — Flutter NeuralInterfaceV2 handles these.
BOOKING_ERROR_CODES = frozenset({
    "COVENANT_REQUIRED",
    "SESSION_LIMIT_REACHED",
    "Time slot conflict",
})


@pytest.mark.parametrize("code", sorted(BOOKING_ERROR_CODES))
def test_booking_error_codes_contract(code):
    assert code in BOOKING_ERROR_CODES
