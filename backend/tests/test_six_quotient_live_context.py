"""Offline seams for six_quotient_live_context (importlib — avoid numpy crash)."""

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


_mod = _load(
    "app.services.six_quotient_live_context",
    APP / "services" / "six_quotient_live_context.py",
)


def test_format_addendum_includes_ceo_focus_and_red_gap():
    text = _mod._format_addendum(
        {"theta_by_section": {"AQ": 0.4, "SQ": -1.0}},
        {
            "focus_quotient": "AQ",
            "focus_capability": "crisis safety / lethality witnessing",
        },
        {"quotients": {"AQ": {"risk": "RED"}, "SQ": {"risk": "YELLOW"}}},
    )
    assert "CEO-approved focus" in text
    assert "AQ" in text
    assert "SIX-QUOTIENT DEVELOPMENT CUES" in text


def test_format_addendum_empty_without_signals():
    text = _mod._format_addendum(
        {"theta_by_section": {"AQ": 0.5, "EQ": 0.5}},
        {},
        {"quotients": {"AQ": {"risk": "GREEN"}}},
    )
    assert text == ""


def test_focus_is_smoke_rejects_lab_stamps():
    assert _mod._focus_is_smoke(
        {
            "approved_by": "smoke_d11",
            "source_run_id": "smoke-d11",
            "focus_quotient": "AQ",
        }
    )
    assert _mod._focus_is_smoke({})
    assert not _mod._focus_is_smoke(
        {
            "approved_by": "DrNevedal1",
            "source_run_id": "run-abc",
            "focus_quotient": "AQ",
        }
    )
