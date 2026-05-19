import importlib.util
import os
import sys


_SERVICES = os.path.join(
    os.path.dirname(__file__), "..", "app", "services"
)


def _load(name: str, filename: str):
    path = os.path.join(_SERVICES, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_ad = _load("little_nate_adaptive_initial_mode", "little_nate_adaptive.py")
SessionState = _ad.SessionState
select_mode = _ad.select_mode


def _state(turn: int) -> SessionState:
    s = SessionState()
    s.turn_count = turn
    return s


def test_turn1_action_request_bootstraps_exploratory():
    s = _state(1)
    mode, signals = select_mode(s, "Can you give me a list of reasons?")
    assert mode == "exploratory"
    assert signals.get("initial_mode_bootstrap") is True
    assert s.current_mode == "exploratory"


def test_turn1_neurodivergent_bootstraps_accommodating():
    s = _state(1)
    mode, signals = select_mode(s, "I have a processing disorder and my thoughts scatter.")
    assert mode == "accommodating"
    assert signals.get("initial_mode_bootstrap") is True
    assert s.current_mode == "accommodating"


def test_turn1_dissatisfaction_bootstraps_strategic():
    s = _state(1)
    mode, signals = select_mode(s, "This feels repetitive and circular.")
    assert mode == "strategic"
    assert signals.get("initial_mode_bootstrap") is True
    assert s.current_mode == "strategic"

