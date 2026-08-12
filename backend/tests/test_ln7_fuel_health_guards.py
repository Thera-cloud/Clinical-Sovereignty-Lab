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


def test_fuel_gauge_excludes_non_fuel_domain_tags():
    fuel = _load("app.jobs.ln7_fuel_gauge", JOBS / "ln7_fuel_gauge.py")
    assert fuel.is_pre6_fuel_domain("coding", 0) is True
    assert fuel.is_pre6_fuel_domain("general", 0) is True
    assert fuel.is_pre6_fuel_domain("goodhart_shadow", 0) is False
    assert fuel.is_pre6_fuel_domain("goodhart_shadow", 99) is False
    assert fuel.is_pre6_fuel_domain("verify_e2_e4", 0) is False
    assert fuel.is_pre6_fuel_domain("e4_prod", 0) is False
    assert fuel.is_pre6_fuel_domain("governance", 0) is False
    # New train domain only after it actually has ci_pack trainable rows
    assert fuel.is_pre6_fuel_domain("clinical_v2", 0) is False
    assert fuel.is_pre6_fuel_domain("clinical_v2", 3) is True


def test_clear_stall_on_progress_parses_latched_count():
    """Stale latch detail 'coding: 1/300' clears when trainable is higher."""
    import asyncio

    fuel = _load("app.jobs.ln7_fuel_gauge", JOBS / "ln7_fuel_gauge.py")

    class FakeConn:
        def __init__(self):
            self.deleted = False

        async def fetchrow(self, *a, **k):
            return {
                "detail": "coding: 1/300 trainable, +0.0/day (n=7d), ETA ~n/a. Queens"
            }

        async def fetchval(self, sql, *a, **k):
            if "DELETE" in sql:
                self.deleted = True
                return 1
            return None

    conn = FakeConn()

    async def _run():
        # prior flat at 53 but latch still at 1 → clear via latched_n
        assert await fuel._clear_stall_on_progress(conn, "coding", 53, 53) is True
        assert conn.deleted is True
        conn.deleted = False
        # no progress vs latch
        conn_flat = FakeConn()

        async def fetchrow_flat(*a, **k):
            return {"detail": "coding: 53/300 trainable"}

        conn_flat.fetchrow = fetchrow_flat  # type: ignore[method-assign]
        assert await fuel._clear_stall_on_progress(conn_flat, "coding", 53, 53) is False

    asyncio.run(_run())
