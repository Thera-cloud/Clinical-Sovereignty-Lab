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


_ad = _load("little_nate_adaptive_boundary", "little_nate_adaptive.py")
SessionState = _ad.SessionState
prepare_response = _ad.prepare_response


def test_pharma_followup_stays_boundary_primed():
    s = SessionState()
    p1 = prepare_response(s, "Are those safe together?", profile={})
    assert p1["signals"].get("clinical_boundary_pharma_interaction") is True
    assert "CLINICAL BOUNDARY PERSISTENCE" in p1["system_addendum"]

    p2 = prepare_response(s, "What about with alcohol?", profile={})
    assert p2["signals"].get("clinical_boundary_pharma_interaction") is True
    assert "repeat a clear decline + redirect every turn" in p2["system_addendum"]


def test_criteria_match_adds_no_reframe_guard():
    s = SessionState()
    p = prepare_response(s, "Do I meet the criteria?", profile={})
    assert p["signals"].get("clinical_boundary_diagnostic_match") is True
    assert "Do NOT substitute alternate diagnostic framings" in p["system_addendum"]


def test_sleep_soft_wording_detected_as_boundary_topic():
    s = SessionState()
    p = prepare_response(s, "What works for sleep when I can't shut my brain off?", profile={})
    assert p["signals"].get("clinical_boundary_sleep_aid") is True
