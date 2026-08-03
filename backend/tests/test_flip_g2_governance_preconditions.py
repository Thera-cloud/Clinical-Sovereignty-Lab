"""Entry 24/27 machine-checked preconditions for flip_g2_governance.py.

Pre-registered flip conditions must live in the repo as machine-checkable
preconditions, enforced by the flip script itself -- not just recorded in
docs a future session has to remember to re-check. This is the offline
test coverage for check_g2_preconditions() and its wiring into the
forward-flip path (--revert stays exempt, unchanged from Entry 24).
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
SERVICES = APP / "services"
SCRIPT_PATH = BACKEND / "scripts" / "flip_g2_governance.py"


def _run_async(coro):
    # NOTE: intentionally NOT asyncio.run() -- on Py3.9 that calls
    # events.set_event_loop(None) on exit, which breaks every later
    # test file in the same session that relies on the legacy
    # asyncio.get_event_loop().run_until_complete() pattern (e.g.
    # test_family_system_field.py, test_growth_ops_closure.py — see
    # test_dual_coo_heldout_weld_check.py's identical helper/comment).
    return asyncio.get_event_loop().run_until_complete(coro)


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


def _script():
    _load("app.services.dual_coo_checklist", SERVICES / "dual_coo_checklist.py")
    _load("app.services.ln7_frozen_config", SERVICES / "ln7_frozen_config.py")
    _load("app.services.ln7_feature_flags", SERVICES / "ln7_feature_flags.py")
    return _load("flip_g2_governance_script", SCRIPT_PATH)


class _FakeConn:
    def __init__(self, count: int):
        self._count = count

    async def fetchrow(self, query, *args):
        return {"n": self._count}


class _FakeAcquireCtx:
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
        return _FakeAcquireCtx(self._conn)


def test_independent_reviewer_precondition_true_on_real_dual_coo_checklist():
    """The real, current dual_coo_checklist.py after this session's Entry
    27 build must pass this check -- proves the precondition function
    isn't just theoretically correct, it agrees with the actual repo
    state."""
    script = _script()
    out = _run_async(script.check_g2_preconditions(None))
    assert out["independent_reviewer_wired"] is True


def test_domain_exclusion_precondition_now_true_after_build():
    """Entry 24/27's 3rd named prerequisite: is_domain_excluded() +
    EXCLUDED_DOMAINS={'clinical','defense'} now wired into
    evaluate_evidence_independent() (dual_coo_checklist.py), checked
    unconditionally before the per-item loop. This must now report True --
    a test that still expected False would be asserting a since-fixed gap
    still exists."""
    script = _script()
    out = _run_async(script.check_g2_preconditions(None))
    assert out["domain_exclusion_wired"] is True


def test_fallback_drill_precondition_true_when_recent_row_exists():
    script = _script()
    pool = _FakePool(_FakeConn(count=1))
    out = _run_async(script.check_g2_preconditions(pool))
    assert out["fallback_drill_exercised"] is True


def test_fallback_drill_precondition_false_when_zero_rows():
    script = _script()
    pool = _FakePool(_FakeConn(count=0))
    out = _run_async(script.check_g2_preconditions(pool))
    assert out["fallback_drill_exercised"] is False


def test_fallback_drill_precondition_false_without_db_pool():
    script = _script()
    out = _run_async(script.check_g2_preconditions(None))
    assert out["fallback_drill_exercised"] is False


def test_all_ok_requires_every_precondition_true():
    """Even with 2 of 3 satisfied (independent reviewer + domain
    exclusion, both now real), all_ok must stay False while the drill
    evidence is missing -- proves this is a real AND-gate, not
    majority-rules. (Domain exclusion landed this session -- see
    test_domain_exclusion_precondition_now_true_after_build -- so the
    'missing one' for this test is now the drill evidence instead.)"""
    script = _script()
    pool = _FakePool(_FakeConn(count=0))  # no recent drill row
    out = _run_async(script.check_g2_preconditions(pool))
    assert out["independent_reviewer_wired"] is True
    assert out["domain_exclusion_wired"] is True
    assert out["fallback_drill_exercised"] is False
    assert out["all_ok"] is False  # the one missing precondition still blocks


def test_all_ok_true_when_all_three_preconditions_genuinely_met():
    """Positive control: with a real drill row present too, all three are
    now true and all_ok flips to True -- proving this isn't hard-coded
    False, it genuinely tracks the three prerequisites."""
    script = _script()
    pool = _FakePool(_FakeConn(count=1))
    out = _run_async(script.check_g2_preconditions(pool))
    assert out["independent_reviewer_wired"] is True
    assert out["domain_exclusion_wired"] is True
    assert out["fallback_drill_exercised"] is True
    assert out["all_ok"] is True


def test_precondition_check_never_raises_on_query_failure():
    script = _script()

    class _BoomConn:
        async def fetchrow(self, *a, **k):
            raise RuntimeError("connection reset")

    pool = _FakePool(_BoomConn())
    out = _run_async(script.check_g2_preconditions(pool))
    assert out["fallback_drill_exercised"] is False
    assert "fallback_drill_exercised_error" in out


@pytest.mark.asyncio
async def test_main_refuses_flip_when_preconditions_unmet(monkeypatch):
    """Real integration test against _main(): a green fence alone must NOT
    be sufficient to flip -- this was exactly the gap Entry 21-23 (this
    same night) demonstrated wasn't good enough."""
    script = _script()

    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(sys, "argv", ["flip_g2_governance.py", "--reason", "test"])

    fake_pool = MagicMock()
    fake_pool.close = AsyncMock()

    async def _fake_create_pool(*a, **k):
        return fake_pool

    monkeypatch.setattr("asyncpg.create_pool", _fake_create_pool)
    monkeypatch.setattr(
        script,
        "boot_fence_check" if hasattr(script, "boot_fence_check") else "_never_used",
        AsyncMock(return_value={"ok": True, "mismatches": []}),
        raising=False,
    )
    # boot_fence_check is imported lazily inside _main() from
    # app.services.ln7_frozen_config -- patch it at that source.
    monkeypatch.setattr(
        "app.services.ln7_frozen_config.boot_fence_check",
        AsyncMock(return_value={"ok": True, "mismatches": []}),
    )
    monkeypatch.setattr(
        "app.services.ln7_feature_flags.flag_enabled",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        script,
        "check_g2_preconditions",
        AsyncMock(
            return_value={
                "independent_reviewer_wired": True,
                "fallback_drill_exercised": False,  # the one missing piece
                "domain_exclusion_wired": False,
                "all_ok": False,
            }
        ),
    )

    rc = await script._main()
    assert rc == 2  # refused


@pytest.mark.asyncio
async def test_main_skip_preconditions_still_gates_on_fence(monkeypatch):
    """--skip-preconditions bypasses ONLY the Entry 24/27 checks, never the
    Step 0 fence -- the two gates are independent."""
    script = _script()

    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(
        sys, "argv", ["flip_g2_governance.py", "--skip-preconditions", "--dry-run"]
    )

    fake_pool = MagicMock()
    fake_pool.close = AsyncMock()

    async def _fake_create_pool(*a, **k):
        return fake_pool

    monkeypatch.setattr("asyncpg.create_pool", _fake_create_pool)
    monkeypatch.setattr(
        "app.services.ln7_frozen_config.boot_fence_check",
        AsyncMock(return_value={"ok": False, "mismatches": ["x"]}),
    )

    rc = await script._main()
    assert rc == 2  # fence still blocks even with --skip-preconditions
