"""Offline guards for fuel slope days_tracked + serve-health MIN_REQUEST_FLOOR.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
JOBS = APP / "jobs"


def _ensure_pkg(name: str, path: Path) -> None:
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]  # type: ignore[attr-defined]
        sys.modules[name] = pkg


def _load(name: str, path: Path):
    _ensure_pkg("app", APP)
    _ensure_pkg("app.jobs", JOBS)
    _ensure_pkg("app.services", APP / "services")
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_serve_health_min_request_floor():
    mon = _load(
        "app.jobs.ln7_serve_health_monitor",
        JOBS / "ln7_serve_health_monitor.py",
    )
    assert mon.MIN_REQUEST_FLOOR >= 30


def test_fuel_gauge_constants():
    fuel = _load("app.jobs.ln7_fuel_gauge", JOBS / "ln7_fuel_gauge.py")
    assert fuel.PRE6_TARGET == 300
    assert fuel.APPROACH_AT == 240
    assert fuel.STALL_DAYS == 10
