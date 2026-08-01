"""Phase D — flywheel harden: GGUF consecutive-win streak + LN7-v2-Base incumbent
(importlib — avoid numpy FPE, mirrors test_ln7_confounded_window.py's pattern).

Covers:
  - ln7_canary_promoter._extract_win_streak(): safe parse of prior pass_rate_json.
  - ln7_canary_promoter.evaluate_canary(): win_streak increments on pass, resets
    to 0 on fail, is left untouched on confounded_window, and gguf_eligible
    flips True only at >=2 consecutive wins.
  - ln7_canary_promoter.resolve_incumbent_id(): Stage-4 dare_ties merge products
    (harness_config.merge_of present) gate vs LN7-v2-Base, not the fast/deep
    baseline; non-merge revisions are unaffected.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
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


def _promoter():
    _load("app.services.ln7_bakeoff_engine", SERVICES / "ln7_bakeoff_engine.py")
    _load("app.services.ln7_change_lease", SERVICES / "ln7_change_lease.py")
    _load("app.services.ln7_outcome_envelope", SERVICES / "ln7_outcome_envelope.py")
    _load("app.services.ln7_feature_flags", SERVICES / "ln7_feature_flags.py")
    _load("app.services.ln7_flywheel_pipeline", SERVICES / "ln7_flywheel_pipeline.py")
    _load("app.services.little_nate_7", SERVICES / "little_nate_7.py")
    return _load("app.services.ln7_canary_promoter", SERVICES / "ln7_canary_promoter.py")


class _FakeConn:
    """asyncpg-connection stand-in; records every execute() for assertions."""

    def __init__(self, canary_row=None, pass_rows=None, heldout_n=0):
        self._canary_row = canary_row
        self._pass_rows = pass_rows if pass_rows is not None else []
        self._heldout_n = heldout_n
        self.executed = []

    async def fetchrow(self, query, *args):
        if "ln7_canary_state" in query:
            return self._canary_row
        return None

    async def fetch(self, query, *args):
        # Both _passes_for_revision and _forgetting_monitor select from
        # ln7_coding_outcomes; keep it simple with one shared fixture list.
        return self._pass_rows

    async def fetchval(self, query, *args):
        return self._heldout_n

    async def execute(self, query, *args):
        self.executed.append((query, args))
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


def _passing_gate(*_a, **_k):
    return {"ok": True, "reason": "ci_beats_incumbent", "candidate_ci": {"mean": 0.9}}


def _failing_gate(*_a, **_k):
    return {"ok": False, "reason": "ci_not_above_incumbent", "candidate_ci": {"mean": 0.1}}


def _run_evaluate(promoter, pool, revision_id="LN7-cand-1", **kwargs):
    async def _go():
        with patch(
            "app.services.ln7_feature_flags.dual_coo_mechanical_promote",
            AsyncMock(return_value=False),
        ), patch(
            "app.services.ln7_feature_flags.auto_promote_enabled",
            AsyncMock(return_value=False),
        ), patch(
            "app.services.ln7_flywheel_pipeline.promote_path_after_gate",
            AsyncMock(return_value={"activated": False}),
        ), patch(
            "app.services.ln7_change_lease.is_any_loop_active", return_value=False
        ):
            return await promoter.evaluate_canary(pool, revision_id, min_tasks=3, **kwargs)

    return asyncio.run(_go())


# ---------------------------------------------------------------------------
# _extract_win_streak — pure helper
# ---------------------------------------------------------------------------

def test_extract_win_streak_none_row_is_zero():
    promoter = _promoter()
    assert promoter._extract_win_streak(None) == 0


def test_extract_win_streak_missing_key_is_zero():
    promoter = _promoter()
    assert promoter._extract_win_streak({"pass_rate_json": json.dumps({"ok": True})}) == 0


def test_extract_win_streak_parses_string_json():
    promoter = _promoter()
    row = {"pass_rate_json": json.dumps({"win_streak": 3})}
    assert promoter._extract_win_streak(row) == 3


def test_extract_win_streak_parses_dict_directly():
    promoter = _promoter()
    row = {"pass_rate_json": {"win_streak": 2}}
    assert promoter._extract_win_streak(row) == 2


def test_extract_win_streak_corrupt_json_is_zero():
    promoter = _promoter()
    row = {"pass_rate_json": "{not-json"}
    assert promoter._extract_win_streak(row) == 0


# ---------------------------------------------------------------------------
# evaluate_canary — win streak lifecycle
# ---------------------------------------------------------------------------

def test_streak_starts_at_one_on_first_win_not_yet_gguf_eligible():
    promoter = _promoter()
    conn = _FakeConn(canary_row={"incumbent_id": "LN7-baseline", "pass_rate_json": None})
    pool = _FakePool(conn)
    with patch.object(promoter, "statistical_gate", None, create=True):
        with patch(
            "app.services.ln7_bakeoff_engine.statistical_gate", side_effect=_passing_gate
        ):
            result = _run_evaluate(promoter, pool)
    assert result["gate"]["win_streak"] == 1
    assert result["gate"]["gguf_eligible"] is False


def test_streak_reaches_two_becomes_gguf_eligible():
    promoter = _promoter()
    conn = _FakeConn(
        canary_row={
            "incumbent_id": "LN7-baseline",
            "pass_rate_json": json.dumps({"win_streak": 1, "ok": True}),
        }
    )
    pool = _FakePool(conn)
    with patch(
        "app.services.ln7_bakeoff_engine.statistical_gate", side_effect=_passing_gate
    ):
        result = _run_evaluate(promoter, pool)
    assert result["gate"]["win_streak"] == 2
    assert result["gate"]["gguf_eligible"] is True
    # persisted back to ln7_canary_state so the next evaluation reads it
    update_calls = [q for q, _a in conn.executed if "pass_rate_json" in q]
    assert update_calls
    persisted = json.loads([a for q, a in conn.executed if "pass_rate_json" in q][-1][-1])
    assert persisted["win_streak"] == 2


def test_streak_resets_to_zero_on_fail_after_prior_wins():
    promoter = _promoter()
    conn = _FakeConn(
        canary_row={
            "incumbent_id": "LN7-baseline",
            "pass_rate_json": json.dumps({"win_streak": 3, "ok": True}),
        }
    )
    pool = _FakePool(conn)
    with patch(
        "app.services.ln7_bakeoff_engine.statistical_gate", side_effect=_failing_gate
    ):
        result = _run_evaluate(promoter, pool)
    assert result["gate"]["win_streak"] == 0
    assert result["gate"]["gguf_eligible"] is False


def test_confounded_window_leaves_streak_unchanged():
    promoter = _promoter()
    conn = _FakeConn(
        canary_row={
            "incumbent_id": "LN7-baseline",
            "pass_rate_json": json.dumps({"win_streak": 2, "ok": True}),
        }
    )
    pool = _FakePool(conn)
    with patch(
        "app.services.ln7_bakeoff_engine.statistical_gate", side_effect=_passing_gate
    ), patch(
        "app.services.ln7_change_lease.is_any_loop_active", return_value=True
    ), patch(
        "app.services.ln7_outcome_envelope.write_envelope", AsyncMock(return_value="env-1")
    ):
        async def _go():
            return await promoter.evaluate_canary(pool, "LN7-cand-1", min_tasks=3)

        result = asyncio.run(_go())
    assert result["gate"]["reason"] == "confounded_window"
    # Confounded is not a real evaluation — the streak from before carries over.
    assert result["gate"]["win_streak"] == 2
    assert result["gate"]["gguf_eligible"] is True


# ---------------------------------------------------------------------------
# resolve_incumbent_id — LN7-v2-Base for Stage-4 merge products
# ---------------------------------------------------------------------------

def test_is_stage4_merge_product_true_for_merge_of_pair():
    promoter = _promoter()
    rev = {"harness_config_json": json.dumps({"merge_of": ["LN7-A", "LN7-B"]})}
    assert promoter._is_stage4_merge_product(rev) is True


def test_is_stage4_merge_product_false_for_plain_revision():
    promoter = _promoter()
    rev = {"harness_config_json": json.dumps({"tier": "fast"})}
    assert promoter._is_stage4_merge_product(rev) is False


def test_is_stage4_merge_product_false_for_none():
    promoter = _promoter()
    assert promoter._is_stage4_merge_product(None) is False


def test_resolve_incumbent_id_explicit_override_always_wins():
    promoter = _promoter()

    async def _go():
        return await promoter.resolve_incumbent_id(
            None, "LN7-merge-123", incumbent_id="Explicit-Base"
        )

    assert asyncio.run(_go()) == "Explicit-Base"


def test_resolve_incumbent_id_merge_product_defaults_to_v2_base():
    promoter = _promoter()
    rev = {
        "revision_id": "LN7-merge-123",
        "harness_config_json": json.dumps({"merge_of": ["LN7-A", "LN7-B"]}),
        "base_checkpoint": "Qwen2.5-Coder-7B",
        "notes": "dare_ties",
    }

    async def _go():
        with patch(
            "app.services.little_nate_7.load_revision", AsyncMock(return_value=rev)
        ):
            return await promoter.resolve_incumbent_id(object(), "LN7-merge-123")

    assert asyncio.run(_go()) == "LN7-v2-Base"


def test_resolve_incumbent_id_non_merge_revision_unaffected():
    promoter = _promoter()
    rev = {
        "revision_id": "LN7-cand-1",
        "harness_config_json": json.dumps({"tier": "fast"}),
        "base_checkpoint": "Qwen2.5-Coder-7B",
        "notes": "",
    }

    async def _go():
        with patch(
            "app.services.little_nate_7.load_revision", AsyncMock(return_value=rev)
        ):
            return await promoter.resolve_incumbent_id(object(), "LN7-cand-1")

    assert asyncio.run(_go()) == "LN7-fast-baseline"
