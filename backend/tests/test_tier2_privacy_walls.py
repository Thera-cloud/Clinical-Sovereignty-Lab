"""Offline privacy walls for Tier 2 kickoff (LIVE_CONTEXT + crystal member filter)."""

from __future__ import annotations

import asyncio
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


_live = _load(
    "app.services.six_quotient_live_context",
    APP / "services" / "six_quotient_live_context.py",
)
_tier2 = _load(
    "app.services.tier2_cross_domain_battery",
    APP / "services" / "tier2_cross_domain_battery.py",
)


def test_live_context_empty_on_family_and_voice(monkeypatch):
    monkeypatch.setenv("ENABLE_SIX_QUOTIENT_LIVE_CONTEXT", "true")

    async def _check(surface: str) -> str:
        return await _live.get_live_addendum(object(), surface=surface)

    assert asyncio.run(_check("family_sanctuary")) == ""
    assert asyncio.run(_check("voice_call")) == ""
    assert asyncio.run(_check("group_coaching")) == ""
    assert asyncio.run(_check("dojo")) == ""


def test_live_context_allowlist_includes_therapy():
    assert "bridge_chat" in _live._LIVE_CONTEXT_SURFACES
    assert "therapy" in _live._LIVE_CONTEXT_SURFACES
    assert _tier2.assert_live_context_allowed("bridge_chat")
    assert not _tier2.assert_live_context_allowed("family_sanctuary")


def test_member_a_cannot_see_member_b_user_crystals():
    crystals = [
        {"user_id": "uuid-a", "crystal_text": "A secret"},
        {"user_id": "uuid-b", "crystal_text": "B secret"},
        {"user_id": "uuid-a", "crystal_text": "A other"},
    ]
    only_a = _tier2.filter_crystals_for_member(crystals, "uuid-a")
    assert len(only_a) == 2
    assert all(c["user_id"] == "uuid-a" for c in only_a)
    assert _tier2.filter_crystals_for_member(crystals, "uuid-b")[0]["crystal_text"] == "B secret"


def test_design_pack_skeleton_not_certification():
    pack = _tier2.design_pack_skeleton()
    assert pack["certification"] is False
    assert set(pack["domains"]) == {"therapy", "family", "dojo", "voice", "ops"}
    assert pack["privacy"]["no_cross_member_user_crystal_recall"] is True
