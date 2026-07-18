"""Offline unit tests for high-risk occupational crisis engine.

Loads modules via importlib to avoid app.services.__init__ → numpy crash on macOS.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"


def _load(name: str, path: Path):
    if "app" not in sys.modules:
        sys.modules["app"] = types.ModuleType("app")
    if "app.services" not in sys.modules:
        pkg = types.ModuleType("app.services")
        pkg.__path__ = [str(APP / "services")]  # type: ignore[attr-defined]
        sys.modules["app.services"] = pkg
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_pop = _load("app.services.population_profile", APP / "services" / "population_profile.py")
_reg = _load(
    "app.services.crisis_resource_registry",
    APP / "services" / "crisis_resource_registry.py",
)
_win = _load(
    "app.services.checkin_risk_windows",
    APP / "services" / "checkin_risk_windows.py",
)
_mod = _load(
    "app.services.population_prompt_modifiers",
    APP / "services" / "population_prompt_modifiers.py",
)


def test_veteran_resources_prefer_vcl():
    profile = {"profile_data": {"population": "veteran"}}
    resources = _reg.get_crisis_resources(profile)
    values = " ".join(r["value"] for r in resources)
    assert "press 1" in values or "838255" in values
    copy = _reg.crisis_tier_copy(profile)
    assert "Veterans Crisis Line" in copy or "838255" in copy


def test_le_resources_include_copline():
    profile = {"profile_data": {"population": "first_responder_le"}}
    blob = str(_reg.get_crisis_resources(profile))
    assert "267-5463" in blob or "Copline" in blob


def test_general_still_has_988_and_741741():
    profile = {"profile_data": {"population": "general"}}
    values = " ".join(r["value"] for r in _reg.get_crisis_resources(profile))
    assert "988" in values
    assert "741741" in values


def test_population_shield_defaults_for_veteran():
    profile = {"profile_data": {"population": "veteran"}}
    assert _pop.get_population(profile) == "veteran"
    assert _pop.is_population_shielded(profile) is True


def test_ws_payload_shape():
    profile = {"profile_data": {"population": "veteran"}}
    payload = _reg.ws_crisis_resources_payload(profile, turn_id="t1")
    assert payload["type"] == "crisis_resources"
    assert payload["turn_id"] == "t1"
    assert payload["resources"]


def test_has_resources_detects_vcl():
    profile = {"profile_data": {"population": "veteran"}}
    text = "Call the Veterans Crisis Line — 988, press 1 or text 838255."
    assert _reg.has_crisis_resources_in_text(text, profile)


def test_peer_voice_block_for_veteran():
    profile = {"profile_data": {"population": "veteran"}}
    block = _mod.peer_culture_voice_block(profile)
    assert "service" in block.lower()
    suffix = _mod.build_population_prompt_suffix(profile, "rough night")
    assert "PEER-CULTURE" in suffix or "CONFIDENTIALITY" in suffix


def test_checkin_risk_window_constants():
    assert _win.DEFAULT_CADENCE_HOURS[_win.REASON_POST_P0] == 24
