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


def test_clinical_population_type_does_not_route_crisis_lines():
    """Sensitive Bridge population_type must not become occupational routing."""
    profile = {
        "profile_data": {
            "population_type": "adult_survivor",
            "population": "general",
        }
    }
    assert _pop.get_population(profile) == "general"
    assert _pop.get_clinical_population_type(profile) == "adult_survivor"
    values = " ".join(r["value"] for r in _reg.get_crisis_resources(profile))
    assert "838255" not in values  # not forced to VCL


def test_same_family_column_or_jsonb():
    a = {"family_id": None, "profile_data": {"family_id": "fam-1"}}
    b = {"family_id": "fam-1", "profile_data": {}}
    c = {"family_id": None, "profile_data": {"family_id": "fam-2"}}
    assert _pop.same_family(a, b) is True
    assert _pop.same_family(a, c) is False


def test_normalize_population():
    ok, err = _pop.normalize_population("Veteran")
    assert ok == "veteran" and err is None
    bad, err2 = _pop.normalize_population("adult_survivor")
    assert bad is None and err2


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


def test_auditor_endpoint_count_is_12():
    import re

    text = (APP / "services" / "high_risk_crisis_auditor.py").read_text()
    pairs = re.findall(r'\("(GET|POST|PUT|DB)",\s*"[^"]+"\)', text)
    assert len(pairs) == 12, pairs
    assert "/api/high-risk-crisis/coach/critical-incident" in text
    assert "family_concern_flags" in text


def test_has_resources_detects_741741_generic():
    profile = {"profile_data": {"population": "general"}}
    text = "If you're in crisis, call or text 988 or text HOME to 741741."
    assert _reg.has_crisis_resources_in_text(text, profile)


def test_family_nondisclosure_in_suffix():
    profile = {"profile_data": {"population": "veteran", "family_concern_consent": True}}
    suffix = _mod.build_population_prompt_suffix(profile, "")
    assert "FAMILY-CONCERN BOUNDARY" in suffix


def test_post_p1_reason_for_violence():
    assert _win.REASON_POST_P1 == "post_p1"
    assert _win.DEFAULT_TTL_DAYS[_win.REASON_POST_P1] == 5
