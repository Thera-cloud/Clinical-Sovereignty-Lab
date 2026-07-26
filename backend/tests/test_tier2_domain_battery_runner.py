"""Offline tests for Tier 2 pack scoring helpers."""

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
    "app.services.tier2_cross_domain_battery",
    APP / "services" / "tier2_cross_domain_battery.py",
)


def test_domains_five():
    assert set(_mod.TIER2_DOMAINS) == {"therapy", "family", "dojo", "voice", "ops"}


def test_pack_skeleton_v1():
    sk = _mod.design_pack_skeleton()
    assert sk["version"] == "tier2_pack_v1"
    assert sk["certification"] is False


def test_filter_member_wall():
    assert len(_mod.filter_crystals_for_member(
        [{"user_id": "1"}, {"user_id": "2"}], "1"
    )) == 1
