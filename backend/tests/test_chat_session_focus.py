"""Main chat holds one live session and asks when the day is ambiguous."""

from datetime import date

from app.services.chat_session_focus import choose_session, parse_day


_SESSIONS = [
    {"session_id": "s-new", "label": "Sep 20, 2026", "date_slug": "2026-09-20"},
    {"session_id": "s-old", "label": "Sep 02, 2026", "date_slug": "2026-09-02"},
]


def test_named_day_binds_that_session():
    choice = choose_session(None, _SESSIONS, "Can we talk about the session on September 2?")
    assert choice["move"] == "bind"
    assert choice["session_id"] == "s-old"


def test_two_sessions_ask_before_summarizing():
    choice = choose_session(None, _SESSIONS, "I want to discuss that session")
    assert choice["move"] == "clarify"
    assert len(choice["options"]) == 2


def test_last_session_is_the_newest():
    choice = choose_session(None, _SESSIONS, "What happened in our last session?")
    assert choice["session_id"] == "s-new"


def test_held_session_stays_until_they_leave():
    held = {"session_id": "s-old", "label": "Sep 02, 2026", "date_slug": "2026-09-02"}
    stay = choose_session(held, _SESSIONS, "What did I say about work?")
    assert stay["session_id"] == "s-old"
    left = choose_session(held, _SESSIONS, "Anyway let's talk about something else")
    assert left["move"] == "leave"


def test_parse_day_rolls_a_future_month_back_a_year():
    assert parse_day("March 3", today=date(2026, 9, 25)) == date(2026, 3, 3)
