"""Offline unit tests — battery + human-gold crystal quarantine (Tier-1 D.14b).

Uses importlib load to avoid app.services.__init__ → numpy FPE on some macOS hosts.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"


def _load_quarantine():
    if "app" not in sys.modules:
        sys.modules["app"] = types.ModuleType("app")
    if "app.services" not in sys.modules:
        pkg = types.ModuleType("app.services")
        pkg.__path__ = [str(APP / "services")]  # type: ignore[attr-defined]
        sys.modules["app.services"] = pkg
    name = "app.services.six_quotient_battery_quarantine"
    path = APP / "services" / "six_quotient_battery_quarantine.py"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _quarantine_on(monkeypatch):
    monkeypatch.setenv("SIX_QUOTIENT_BATTERY_QUARANTINE", "true")
    q = _load_quarantine()
    if hasattr(q, "_gold_stem_fingerprints"):
        q._gold_stem_fingerprints.cache_clear()


def test_block_battery_origin_surface():
    q = _load_quarantine()
    assert q.should_block_crystallize(
        origin_surface="six_quotient_battery",
        user_text="hello",
        nate_response="hi",
    )


def test_block_marker_in_text():
    q = _load_quarantine()
    assert q.should_block_crystallize(
        origin_surface="bridge_chat",
        user_text="[SIX_QUOTIENT_BATTERY] AQ-1",
        nate_response="ok",
    )


def test_allow_normal_chat():
    q = _load_quarantine()
    assert not q.should_block_crystallize(
        origin_surface="bridge_chat",
        user_text="I feel anxious about work today",
        nate_response="That sounds heavy — what's the part that won't let go?",
    )


def test_filter_contaminated_rows():
    q = _load_quarantine()
    rows = [
        {"crystal_text": "normal clinical insight about grief"},
        {
            "crystal_text": "x",
            "metadata": {"origin_surface": "six_quotient_nightly"},
        },
        {"crystal_text": "contains six_quotient_battery marker"},
        {
            "crystal_text": "BATTERY-VALIDATED WEAKNESS — IQ QUOTIENT (run x)",
            "metadata": {"source": "six_quotient_battery", "quotient": "IQ"},
        },
        {
            "crystal_text": "lesson text",
            "origin_surface": "six_quotient_battery",
            "metadata": {},
        },
    ]
    out = q.filter_crystals(rows)
    assert len(out) == 1
    assert "grief" in out[0]["crystal_text"]


def test_growth_engine_row_contaminated():
    q = _load_quarantine()
    assert q.crystal_row_is_battery_contaminated(
        {
            "crystal_text": "BATTERY-VALIDATED WEAKNESS — AQ",
            "metadata": {"source": "six_quotient_battery"},
        }
    )


def test_quarantine_can_disable(monkeypatch):
    monkeypatch.setenv("SIX_QUOTIENT_BATTERY_QUARANTINE", "false")
    q = _load_quarantine()
    assert not q.should_block_crystallize(
        origin_surface="six_quotient_battery",
        user_text="x",
        nate_response="y",
    )


def test_block_human_gold_stem_fingerprint():
    """Gold that leaks into memory stops being gold (Claude Fable gap 1)."""
    q = _load_quarantine()
    q._gold_stem_fingerprints.cache_clear()
    fps = q._gold_stem_fingerprints()
    assert len(fps) >= 20
    sample = next(iter(fps))
    assert q.should_block_crystallize(
        origin_surface="bridge_chat",
        user_text=sample + " …and I need you to hear this.",
        nate_response="I'm with you.",
    )


def test_gold_origin_surface_blocked():
    q = _load_quarantine()
    assert q.should_block_crystallize(
        origin_surface="six_quotient_human_gold",
        user_text="ordinary text",
        nate_response="ordinary reply",
    )


def test_block_gold_admin_run_id():
    q = _load_quarantine()
    assert q.should_block_crystallize(
        origin_surface="bridge_chat",
        user_text="ordinary client disclosure about work stress",
        nate_response="I'm with you.",
        gold_admin_run_id="gold_admin_20260721_nate",
    )


def test_block_gold_admin_marker_in_text():
    q = _load_quarantine()
    assert q.should_block_crystallize(
        origin_surface="bridge_chat",
        user_text="gold_admin_run: gold_admin_20260721_nate continuing",
        nate_response="ok",
    )
