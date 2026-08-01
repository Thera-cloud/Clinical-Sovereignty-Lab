"""Phase E5 — confounded-window detection offline fences (importlib — avoid numpy FPE).

Covers:
  - ln7_change_lease.is_any_loop_active(): cross-loop overlap detection.
  - ln7_canary_promoter.evaluate_canary(): confounded evidence short-circuits
    to hold_shadow and never reaches promote/rollback/activate_revision.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

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


def test_is_any_loop_active_true_when_lease_held():
    lease = _load("app.services.ln7_change_lease", SERVICES / "ln7_change_lease.py")
    with patch.object(lease, "lease_holder", side_effect=lambda loop: "abc" if loop == "hive_burst" else None):
        assert lease.is_any_loop_active(["hive_burst"]) is True
        assert lease.is_any_loop_active(["some_other_loop"]) is False


def test_is_any_loop_active_false_when_no_lease():
    lease = _load("app.services.ln7_change_lease", SERVICES / "ln7_change_lease.py")
    with patch.object(lease, "lease_holder", return_value=None):
        assert lease.is_any_loop_active(["hive_burst"]) is False
        assert lease.is_any_loop_active([]) is False


class _FakeConn:
    """Minimal asyncpg-connection stand-in for evaluate_canary's queries."""

    def __init__(self, canary_row=None):
        self._canary_row = canary_row

    async def fetchrow(self, query, *args):
        if "ln7_canary_state" in query:
            return self._canary_row
        return None

    async def fetch(self, query, *args):
        return []

    async def fetchval(self, query, *args):
        return 0

    async def execute(self, query, *args):
        return None


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


def test_evaluate_canary_holds_on_confounded_window():
    _load("app.services.ln7_bakeoff_engine", SERVICES / "ln7_bakeoff_engine.py")
    _load("app.services.ln7_change_lease", SERVICES / "ln7_change_lease.py")
    _load("app.services.ln7_outcome_envelope", SERVICES / "ln7_outcome_envelope.py")
    promoter = _load("app.services.ln7_canary_promoter", SERVICES / "ln7_canary_promoter.py")

    pool = _FakePool(_FakeConn(canary_row={"incumbent_id": "LN7-baseline"}))

    write_envelope_mock = AsyncMock(return_value="env-1")

    async def _run():
        with patch(
            "app.services.ln7_change_lease.is_any_loop_active", return_value=True
        ), patch(
            "app.services.ln7_outcome_envelope.write_envelope", write_envelope_mock
        ), patch(
            "app.services.ln7_revision.activate_revision",
            AsyncMock(side_effect=AssertionError("must not promote on confounded evidence")),
        ), patch(
            "app.services.ln7_flywheel_pipeline.promote_path_after_gate",
            AsyncMock(side_effect=AssertionError("must not promote on confounded evidence")),
        ):
            return await promoter.evaluate_canary(pool, "LN7-2026-07-31T000000Z", min_tasks=3)

    result = asyncio.run(_run())

    assert result["ok"] is False
    assert result["action"] == "hold_shadow"
    assert result["gate"]["reason"] == "confounded_window"
    assert result["gate"]["ok"] is False
    write_envelope_mock.assert_awaited_once()
    _, kwargs = write_envelope_mock.await_args
    assert kwargs["confounded"] is True
    assert kwargs["loop_name"] == "canary_eval"


def test_evaluate_canary_ignores_confound_when_no_overlap():
    _load("app.services.ln7_bakeoff_engine", SERVICES / "ln7_bakeoff_engine.py")
    _load("app.services.ln7_change_lease", SERVICES / "ln7_change_lease.py")
    promoter = _load("app.services.ln7_canary_promoter", SERVICES / "ln7_canary_promoter.py")

    pool = _FakePool(_FakeConn(canary_row={"incumbent_id": "LN7-baseline"}))

    async def _run():
        with patch("app.services.ln7_change_lease.is_any_loop_active", return_value=False):
            return await promoter.evaluate_canary(pool, "LN7-2026-07-31T000000Z", min_tasks=3)

    result = asyncio.run(_run())

    # No outcomes at all (fake pool returns []) -> insufficient_tasks, NOT confounded_window.
    assert result["gate"]["reason"] != "confounded_window"
