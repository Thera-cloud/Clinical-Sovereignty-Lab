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


def test_list_pack_names_includes_index_orphan_micro_ab():
    ci = _load(
        "app.services.ln_sandbox_engineering_ci",
        APP / "services" / "ln_sandbox_engineering_ci.py",
    )
    names = ci.list_pack_names()
    assert "micro_ab_ok_on_fail" in names
    assert "asyncpg_cast" in names


def test_catalog_slugs_unique_and_prefixed():
    cat = _load(
        "app.services.ln7_fuel_pack_catalog",
        APP / "services" / "ln7_fuel_pack_catalog.py",
    )
    ok, dup = cat.catalog_slugs_unique()
    assert ok, dup
    names = cat.catalog_pack_names()
    assert len(names) >= 20
    assert all(n.startswith("catalog_") for n in names)
    assert len(set(names)) == len(names)


def test_catalog_golden_applies_on_tmp(tmp_path):
    cat = _load(
        "app.services.ln7_fuel_pack_catalog",
        APP / "services" / "ln7_fuel_pack_catalog.py",
    )
    ci = _load(
        "app.services.ln_sandbox_engineering_ci",
        APP / "services" / "ln_sandbox_engineering_ci.py",
    )
    from shutil import copytree

    for spec in cat.catalog_specs():
        cat.materialize_catalog_pack(tmp_path, spec)
        name = cat.catalog_pack_name(spec.slug)
        assert (tmp_path / name / "task.json").is_file(), name
        work = tmp_path / f"wd_{name}"
        copytree(tmp_path / name, work)
        broken = ci.run_pytest(work, "tests/test_fix.py")
        assert not broken["passed"], name
        ok, apply_notes = ci.apply_unified_diff(
            work, (work / "golden.patch").read_text(encoding="utf-8")
        )
        assert ok, f"{name}: {apply_notes}"
        fixed = ci.run_pytest(work, "tests/test_fix.py")
        assert fixed["passed"], f"{name}: {fixed.get('log')}"


def test_drip_disabled(monkeypatch):
    drip = _load("app.jobs.ln7_fuel_drip", JOBS / "ln7_fuel_drip.py")
    monkeypatch.setenv("LN7_FUEL_DRIP", "0")
    assert drip.drip_enabled() is False
    monkeypatch.setenv("LN7_FUEL_DRIP", "1")
    assert drip.drip_enabled() is True
    assert 1 <= drip.drip_limit() <= 24


def test_drip_skips_at_target(monkeypatch):
    import asyncio

    drip = _load("app.jobs.ln7_fuel_drip", JOBS / "ln7_fuel_drip.py")
    monkeypatch.setenv("LN7_FUEL_DRIP", "1")

    async def _full(_pool):
        return 300

    drip._coding_trainable = _full  # type: ignore[method-assign]

    async def _run():
        out = await drip.run_fuel_organic_drip(object())
        assert out.get("skipped") == "at_target"

    asyncio.run(_run())
