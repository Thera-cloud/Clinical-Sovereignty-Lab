"""Offline unit tests for chat_load_gate (autonomous learn / chat isolation)."""
from app.websocket.chat_load_gate import (
    chat_busy,
    chat_in_flight,
    chat_in_flight_count,
    chat_turn_begin,
    chat_turn_end,
)


def test_begin_end_balanced():
    # Drain any leftover from other tests
    while chat_in_flight():
        chat_turn_end()
    assert chat_in_flight() is False
    chat_turn_begin()
    assert chat_in_flight() is True
    assert chat_in_flight_count() == 1
    chat_turn_begin()
    assert chat_in_flight_count() == 2
    chat_turn_end()
    assert chat_in_flight_count() == 1
    chat_turn_end()
    assert chat_in_flight() is False


def test_context_manager():
    while chat_in_flight():
        chat_turn_end()
    with chat_busy():
        assert chat_in_flight() is True
    assert chat_in_flight() is False


def test_end_never_goes_negative():
    while chat_in_flight():
        chat_turn_end()
    chat_turn_end()
    chat_turn_end()
    assert chat_in_flight_count() == 0
