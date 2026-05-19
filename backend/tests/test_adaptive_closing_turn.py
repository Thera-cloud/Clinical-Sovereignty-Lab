"""Closing-turn mode selection (Lisa transcript 2026-05-19)."""
import importlib.util
import os
import sys

_SERVICES = os.path.join(os.path.dirname(__file__), "..", "app", "services")


def _load(name: str, filename: str):
    path = os.path.join(_SERVICES, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_ad = _load("little_nate_adaptive_closing", "little_nate_adaptive.py")
SessionState = _ad.SessionState
select_mode = _ad.select_mode
build_system_addendum = _ad.build_system_addendum
detect_closing_turn = _ad.detect_closing_turn


def _state(turn: int, mode: str = "exploratory") -> SessionState:
    s = SessionState()
    s.turn_count = turn
    s.current_mode = mode
    return s


def test_detect_closing_nap():
    assert detect_closing_turn("I'm taking a nap")


def test_closing_turn_overrides_exploratory_lock_in():
    s = _state(12, "exploratory")
    mode, signals = select_mode(s, "Practical step to restore resources. Bye for now.")
    assert mode == "reflective"
    assert signals["closing_turn"] is True


def test_closing_addendum_forbids_framings():
    addendum = build_system_addendum(
        "reflective",
        {"closing_turn": True},
        user_msg="bye",
    )
    assert "CLOSING TURN" in addendum
    assert "2-3" in addendum or "Do NOT offer 2-3" in addendum
