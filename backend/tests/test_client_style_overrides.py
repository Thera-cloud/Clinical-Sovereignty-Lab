"""LetsGoLisa client style overrides (Jul 2026 healing-journey upgrade)."""
import importlib.util
import os
import sys

_SERVICES = os.path.join(os.path.dirname(__file__), "..", "app", "services")


def _load(name: str, filename: str):
    path = os.path.join(_SERVICES, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    os.environ["ENABLE_CLIENT_STYLE_OVERRIDES"] = "true"
    spec.loader.exec_module(mod)
    return mod


_mod = _load("client_style_overrides_test", "client_style_overrides.py")
matches_letsgolisa = _mod.matches_letsgolisa
detect_lisa_session_mode = _mod.detect_lisa_session_mode
maybe_bias_mode = _mod.maybe_bias_mode
build_client_style_addendum = _mod.build_client_style_addendum


def test_matches_username_and_hw():
    assert matches_letsgolisa({"username": "LetsGoLisa"})
    assert matches_letsgolisa({"hardware_id": "CLIENT_LETSGOLISA_ID"})
    assert not matches_letsgolisa({"username": "ChloeHart"})


def test_trust_protocol_in_addendum():
    block = build_client_style_addendum(
        {"username": "LetsGoLisa"},
        user_msg="hello",
    )
    assert "Answer → then deepen" in block or "answer then deepen" in block.lower() or "Answer first" in block or "TRUST PROTOCOL" in block
    assert "I sense a feeling" in block
    assert "PANEL" in block and "MARRIAGE" in block and "CRISIS" in block
    assert "spider/jackal" in block or "Serpent" in block
    assert "repair" in block.lower() or "REPAIR" in block


def test_crisis_mode_car_numb_dark():
    assert detect_lisa_session_mode(
        "I am sitting in my car a few miles from home. it's getting dark. I am numb"
    ) == "crisis"
    mode, sigs = maybe_bias_mode(
        "reflective",
        "I am numb and exhausted. sitting in my car",
        {"username": "LetsGoLisa"},
    )
    assert mode == "strategic"
    assert sigs.get("lisa_session_mode") == "crisis"
    block = build_client_style_addendum(
        {"username": "LetsGoLisa"},
        user_msg="sitting in my car numb",
    )
    assert "CRISIS MODE" in block
    assert "No panels" in block or "no panels" in block.lower()


def test_marriage_mode_bill():
    assert detect_lisa_session_mode(
        "I would like a relationship of equals with Bill"
    ) == "marriage"
    mode, sigs = maybe_bias_mode(
        "reflective",
        "Bill expressed regret today for his actions",
        {"username": "LetsGoLisa"},
    )
    assert mode == "strategic"
    assert sigs.get("lisa_session_mode") == "marriage"


def test_panel_mode_names_characters():
    assert detect_lisa_session_mode(
        "(asking about my Sovereign Journey story panel image) Dawnsinger"
    ) == "panel"
    mode, _ = maybe_bias_mode(
        "reflective",
        "What is the name of the character by the campfire?",
        {"username": "LetsGoLisa"},
    )
    assert mode == "direct"


def test_direct_ask_biases_to_direct():
    mode, sigs = maybe_bias_mode(
        "reflective",
        "Little Nate, what is the name of the character by the campfire?",
        {"username": "LetsGoLisa"},
    )
    assert mode == "direct"
    assert sigs.get("lisa_session_mode") == "direct_ask"


def test_repair_biases_to_strategic():
    mode, _ = maybe_bias_mode(
        "reflective",
        "I am finding your communication confusing and frustrating.",
        {"username": "LetsGoLisa"},
    )
    assert mode == "strategic"


def test_no_addendum_for_other_clients():
    assert build_client_style_addendum({"username": "chloster14"}, user_msg="hi") == ""


def test_flag_off_is_noop(monkeypatch):
    monkeypatch.setattr(_mod, "ENABLE_CLIENT_STYLE_OVERRIDES", False)
    mode, sigs = maybe_bias_mode(
        "reflective",
        "what is the name of the character",
        {"username": "LetsGoLisa"},
    )
    assert mode == "reflective"
    assert sigs == {}
    assert build_client_style_addendum({"username": "LetsGoLisa"}, user_msg="hi") == ""


def test_coach_handoff_brief_constant():
    brief = _mod.COACH_HANDOFF_BRIEF_JUL20
    assert "grandfather" in brief.lower() or "CSA" in brief or "abuse" in brief.lower()
    assert "birthday" in brief.lower()
    assert "car" in brief.lower()
    assert "CoachN" in brief
