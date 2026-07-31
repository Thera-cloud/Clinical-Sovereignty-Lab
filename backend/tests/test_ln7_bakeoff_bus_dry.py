"""Step 7 acceptance — ln7_bakeoff bus dry path ($0, gold fixture).

Loads via importlib to avoid app.services.__init__ → numpy macOS FPE.
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
SERVICES = APP / "services"


def _ensure_pkg(name: str, path: Path) -> None:
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]  # type: ignore[attr-defined]
        sys.modules[name] = pkg


def _load(name: str, path: Path):
    _ensure_pkg("app", APP)
    _ensure_pkg("app.services", SERVICES)
    if name in sys.modules and getattr(sys.modules[name], "__file__", None) == str(path):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.asyncio
async def test_ln7_bakeoff_bus_dry_acceptance(monkeypatch):
    monkeypatch.setenv("LN7_BAKEOFF_DRY", "1")
    _load("app.services.ln7_decoupled_bakeoff", SERVICES / "ln7_decoupled_bakeoff.py")
    bus = _load("app.services.ln7_bakeoff_bus", SERVICES / "ln7_bakeoff_bus.py")

    out = await bus.handle_ln7_bakeoff(
        None,
        payload={"attempt_label": "Attempt6Dry", "human_smoke_gate": True},
    )
    assert out.get("ok") is True
    assert out.get("mode") == "dry"
    assert out.get("winner") == "LN7-2026-07-30T190327Z"
    assert out.get("mean_a") == pytest.approx(0.292, abs=1e-3)
    assert out.get("mean_b") == pytest.approx(0.167, abs=1e-3)
    assert out.get("anchor_score") == pytest.approx(1.0, abs=1e-4)
    assert isinstance(out.get("smoke_preview"), list)


@pytest.mark.asyncio
async def test_paid_gate_blocks_live(monkeypatch):
    monkeypatch.setenv("LN7_BAKEOFF_DRY", "0")
    monkeypatch.delenv("LN7_BURST_ALLOW_PAID", raising=False)
    bus = _load("app.services.ln7_bakeoff_bus", SERVICES / "ln7_bakeoff_bus.py")

    out = await bus.handle_ln7_bakeoff(
        None, payload={"arm_a_rev": "a", "arm_b_rev": "b"}
    )
    assert out.get("ok") is False
    assert out.get("error") == "paid_gate_closed"
