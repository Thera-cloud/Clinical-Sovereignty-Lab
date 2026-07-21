"""Offline seams for SixQuotientSelfDevelopmentAgent.

Loads via importlib to avoid app.services.__init__ → numpy crash on macOS.
"""

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


_mod = _load(
    "app.services.six_quotient_self_development_agent",
    APP / "services" / "six_quotient_self_development_agent.py",
)
SixQuotientSelfDevelopmentAgent = _mod.SixQuotientSelfDevelopmentAgent
_DEFAULT_FOCUS = _mod._DEFAULT_FOCUS


def test_rank_weaknesses_prefers_red_then_low_theta():
    agent = SixQuotientSelfDevelopmentAgent(db_pool=None)
    ability = {
        "theta": 0.1,
        "theta_by_section": {
            "IQ": 0.5,
            "EQ": 0.4,
            "MQ": 0.3,
            "SQ": -1.2,
            "CQ": 0.2,
            "AQ": 0.1,
        },
    }
    gap = {
        "quotients": {
            "SQ": {"pct": 40.0, "risk": "RED"},
            "AQ": {"pct": 80.0, "risk": "GREEN"},
        }
    }
    ranked = agent._rank_weaknesses(ability, gap)
    assert ranked[0]["quotient"] == "SQ"
    assert "rupture" in ranked[0]["capability"].lower() or "SQ" in _DEFAULT_FOCUS["SQ"]


def test_run_once_no_db_returns_error():
    agent = SixQuotientSelfDevelopmentAgent(db_pool=None)
    out = asyncio.run(agent.run_once(enqueue=False, persist_drafts=False))
    assert out.get("ok") is False
    assert out.get("error") == "no_db_pool"
