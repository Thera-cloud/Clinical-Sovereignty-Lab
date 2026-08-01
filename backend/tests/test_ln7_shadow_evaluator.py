"""R3 — shadow evaluators (weld ossification without self-edit).

Covers app.services.ln7_shadow_evaluator:
  - _overlay_json: non-mutating deep merge.
  - shadow_drift_bands: only ALLOWED_SHADOW_TARGETS honored, everything else skipped.
  - _verdict: per-metric trip computation.
  - run_shadow_sample: logs both live+shadow verdicts to outcome_envelope,
    never mutates frozen-config, skips envelope write when no active variant.
  - run_monthly_divergence_check: insufficient-sample skip, under-threshold
    no-op, over-threshold drafts a (dry-run) PR + fires the anomaly.

Loaded via importlib file path (not `import app...`) — importing the
`app.services` package pulls in nevedal_engine.py -> numpy, which SIGFPEs
on some macOS hosts during package __init__ (see
backend/scripts/run_ci_tests.sh's Sovereign Standard gate loader for the
same workaround).

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


def _sev():
    return _load("app.services.ln7_shadow_evaluator", SERVICES / "ln7_shadow_evaluator.py")


def _preload_lazy_deps():
    """ln7_shadow_evaluator.py imports its cross-module deps *inside* each
    function body (not at module top level), so they are not attributes of
    the ``sev`` module object — they must be patched at their true dotted
    path (e.g. ``app.services.ln7_frozen_config.load_json``). Pre-load each
    dependency module under its real dotted name so ``unittest.mock.patch``
    (string form) can resolve it through the fake ``app``/``app.services``
    namespace packages registered by ``_load``."""
    _load("app.services.ln7_frozen_config", SERVICES / "ln7_frozen_config.py")
    _load("app.services.goodhart_drift_sentinel", SERVICES / "goodhart_drift_sentinel.py")
    _load("app.services.ln7_outcome_envelope", SERVICES / "ln7_outcome_envelope.py")
    _load("app.services.sovereign_weld_bot", SERVICES / "sovereign_weld_bot.py")
    _load("app.services.flywheel_anomaly", SERVICES / "flywheel_anomaly.py")


def _run(coro):
    # A prior-collected suite in the same pytest session may have used
    # unittest.IsolatedAsyncioTestCase (which calls
    # asyncio.set_event_loop(None) on teardown) or asyncio.run() (Py3.9
    # closes+clears the loop on exit), either of which disables
    # get_event_loop()'s auto-create fallback for the rest of the session.
    # Fall back to a fresh loop rather than depending on suite ordering.
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# --------------------------------------------------------------------------
# _overlay_json
# --------------------------------------------------------------------------

def test_overlay_json_merges_without_mutating_base():
    sev = _sev()
    base = {"drift_bands": {"a": {"max_abs_delta": 0.25}, "b": {"max_abs_delta": 0.3}}}
    overlay = {"drift_bands": {"a": {"max_abs_delta": 0.15}}}
    out = sev._overlay_json(base, overlay)
    assert out["drift_bands"]["a"]["max_abs_delta"] == 0.15
    assert out["drift_bands"]["b"]["max_abs_delta"] == 0.3
    # base untouched
    assert base["drift_bands"]["a"]["max_abs_delta"] == 0.25


def test_overlay_json_leaf_overlay_replaces_non_dict():
    sev = _sev()
    base = {"x": 1, "y": {"z": 2}}
    overlay = {"x": 99, "y": "scalar_wins"}
    out = sev._overlay_json(base, overlay)
    assert out["x"] == 99
    assert out["y"] == "scalar_wins"


# --------------------------------------------------------------------------
# shadow_drift_bands — allowlist enforcement
# --------------------------------------------------------------------------

def test_shadow_drift_bands_none_when_no_variants():
    sev = _sev()
    with patch.object(sev, "load_shadow_params", return_value={"variants": []}):
        assert sev.shadow_drift_bands({"drift_bands": {}}) is None


def test_shadow_drift_bands_skips_disallowed_target():
    sev = _sev()
    params = {"variants": [{"id": "x", "target": "adversarial_heldout", "overlay": {}}]}
    with patch.object(sev, "load_shadow_params", return_value=params):
        assert sev.shadow_drift_bands({"drift_bands": {}}) is None


def test_shadow_drift_bands_applies_allowed_goodhart_overlay():
    sev = _sev()
    params = {
        "variants": [
            {
                "id": "tighter",
                "target": "goodhart_probes",
                "overlay": {"drift_bands": {"metric_a": {"max_abs_delta": 0.10}}},
            }
        ]
    }
    live_probes = {"drift_bands": {"metric_a": {"max_abs_delta": 0.25}, "metric_b": {"max_abs_delta": 0.3}}}
    with patch.object(sev, "load_shadow_params", return_value=params):
        bands = sev.shadow_drift_bands(live_probes)
    assert bands["metric_a"]["max_abs_delta"] == 0.10
    assert bands["metric_b"]["max_abs_delta"] == 0.3


# --------------------------------------------------------------------------
# _verdict
# --------------------------------------------------------------------------

def test_verdict_trips_when_delta_exceeds_band():
    sev = _sev()
    bands = {"m": {"max_abs_delta": 0.1}}
    ref = {"m": 0.5}
    live = {"m": 0.8}
    v = sev._verdict(bands, ref, live)
    assert v["tripped"] is True
    assert v["drifts"][0]["delta"] == pytest.approx(0.3)


def test_verdict_clean_when_within_band():
    sev = _sev()
    bands = {"m": {"max_abs_delta": 0.5}}
    ref = {"m": 0.5}
    live = {"m": 0.6}
    v = sev._verdict(bands, ref, live)
    assert v["tripped"] is False


# --------------------------------------------------------------------------
# run_shadow_sample
# --------------------------------------------------------------------------

def test_run_shadow_sample_skips_envelope_write_when_no_active_variant():
    sev = _sev()
    _preload_lazy_deps()
    with patch("app.services.ln7_frozen_config.load_json", return_value={"drift_bands": {}, "metrics": {}}), \
         patch("app.services.goodhart_drift_sentinel.measure_live_metrics", return_value={}), \
         patch.object(sev, "shadow_drift_bands", return_value=None), \
         patch("app.services.ln7_outcome_envelope.write_envelope", new=AsyncMock()) as mock_write:
        out = _run(sev.run_shadow_sample(db_pool=object()))
    assert out["skipped_shadow"] is True
    assert out["shadow_verdict"] is None
    mock_write.assert_not_awaited()


def test_run_shadow_sample_logs_divergence_to_envelope():
    sev = _sev()
    _preload_lazy_deps()

    def _fake_load_json(name, default=None):
        if name == "goodhart_probes.json":
            return {"drift_bands": {"m": {"max_abs_delta": 0.5}}}
        if name == "goodhart_reference.json":
            return {"metrics": {"m": 0.5}}
        return default

    with patch("app.services.ln7_frozen_config.load_json", side_effect=_fake_load_json), \
         patch("app.services.goodhart_drift_sentinel.measure_live_metrics", return_value={"m": 0.6}), \
         patch.object(
             sev,
             "shadow_drift_bands",
             return_value={"m": {"max_abs_delta": 0.05}},  # tighter -> shadow trips, live doesn't
         ), \
         patch("app.services.ln7_outcome_envelope.write_envelope", new=AsyncMock(return_value="env-id")) as mock_write:
        out = _run(sev.run_shadow_sample(db_pool=object()))

    assert out["live_verdict"]["tripped"] is False
    assert out["shadow_verdict"]["tripped"] is True
    assert out["diverged"] is True
    mock_write.assert_awaited_once()
    _, kwargs = mock_write.call_args
    assert kwargs["loop_name"] == "shadow_eval"
    assert kwargs["event_kind"] == "weekly_sample"
    assert kwargs["shadow_outcome"]["diverged"] is True


def test_run_shadow_sample_never_mutates_frozen_config_json():
    """No path in run_shadow_sample writes to frozen-config; the only I/O is
    a read (load_json, mocked here) and an envelope write (mocked)."""
    sev = _sev()
    _preload_lazy_deps()
    calls = []

    def _fake_load_json(name, default=None):
        calls.append(name)
        return default or {}

    with patch("app.services.ln7_frozen_config.load_json", side_effect=_fake_load_json), \
         patch("app.services.goodhart_drift_sentinel.measure_live_metrics", return_value={}), \
         patch.object(sev, "shadow_drift_bands", return_value=None), \
         patch("app.services.ln7_outcome_envelope.write_envelope", new=AsyncMock()):
        _run(sev.run_shadow_sample(db_pool=object()))
    # only reads — no write_text / Path.write anywhere in the call chain
    assert "goodhart_probes.json" in calls
    assert "goodhart_reference.json" in calls


# --------------------------------------------------------------------------
# run_monthly_divergence_check
# --------------------------------------------------------------------------

class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, query, *args):
        return self._rows


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, rows):
        self._conn = _FakeConn(rows)

    def acquire(self):
        return _FakeAcquire(self._conn)


def test_monthly_divergence_no_db_pool_returns_error():
    sev = _sev()
    out = _run(sev.run_monthly_divergence_check(db_pool=None))
    assert out["ok"] is False
    assert out["error"] == "no_db_pool"


def test_monthly_divergence_skips_when_insufficient_samples():
    sev = _sev()
    rows = [{"shadow_outcome": {"diverged": True}}]  # below default min_samples
    pool = _FakePool(rows)
    with patch.object(sev, "load_shadow_params", return_value={"divergence_threshold": 0.2, "min_samples": 4}):
        out = _run(sev.run_monthly_divergence_check(db_pool=pool))
    assert out["ok"] is True
    assert out["skipped"] is True
    assert out["reason"] == "insufficient_samples"


def test_monthly_divergence_below_threshold_no_pr():
    sev = _sev()
    rows = [{"shadow_outcome": {"diverged": False}} for _ in range(8)] + [
        {"shadow_outcome": {"diverged": True}}
    ]
    pool = _FakePool(rows)
    with patch.object(sev, "load_shadow_params", return_value={"divergence_threshold": 0.5, "min_samples": 4}):
        out = _run(sev.run_monthly_divergence_check(db_pool=pool))
    assert out["ok"] is True
    assert out["pr_opened"] is False
    assert out["divergence_rate"] == pytest.approx(1 / 9)


def test_monthly_divergence_over_threshold_opens_draft_pr_and_notifies_anomaly():
    sev = _sev()
    _preload_lazy_deps()
    rows = [{"shadow_outcome": {"diverged": True}} for _ in range(4)] + [
        {"shadow_outcome": {"diverged": False}}
    ]  # 4/5 = 80% diverged
    pool = _FakePool(rows)

    fake_pr_result = {"ok": True, "dry_run": True, "branch": "b", "title": "t"}
    with patch.object(sev, "load_shadow_params", return_value={"divergence_threshold": 0.2, "min_samples": 4}), \
         patch("app.services.ln7_frozen_config.load_json", return_value={"drift_bands": {}, "version": 1}), \
         patch.object(sev, "shadow_drift_bands", return_value={"m": {"max_abs_delta": 0.1}}), \
         patch("app.services.sovereign_weld_bot.open_shadow_eval_pr", return_value=fake_pr_result) as mock_pr, \
         patch("app.services.flywheel_anomaly.notify_flywheel_anomaly", new=AsyncMock()) as mock_notify:
        out = _run(sev.run_monthly_divergence_check(db_pool=pool))

    assert out["divergence_rate"] == pytest.approx(0.8)
    mock_pr.assert_called_once()
    pr_kwargs = mock_pr.call_args.kwargs
    assert pr_kwargs["branch"].startswith("sovereign-weld-bot/shadow-divergence-")
    assert "frozen-config/goodhart_probes.json" in pr_kwargs["files"]
    # dry_run PR result means pr_opened stays False (never merges, never
    # silently "opened" unless SOVEREIGN_WELD_BOT_DRY_RUN=0 is explicitly set)
    assert out["pr_opened"] is False
    mock_notify.assert_awaited_once()
    anomaly_args = mock_notify.call_args.args
    assert anomaly_args[0] == "shadow_eval_divergence"


def test_monthly_divergence_query_failure_returns_error():
    sev = _sev()

    class _BoomPool:
        def acquire(self):
            raise RuntimeError("db down")

    with patch.object(sev, "load_shadow_params", return_value={"divergence_threshold": 0.2, "min_samples": 4}):
        out = _run(sev.run_monthly_divergence_check(db_pool=_BoomPool()))
    assert out["ok"] is False
    assert "error" in out


# --------------------------------------------------------------------------
# ALLOWED_SHADOW_TARGETS — absolute R3 boundary
# --------------------------------------------------------------------------

def test_allowed_shadow_targets_excludes_heldout_and_adversarial():
    sev = _sev()
    assert "adversarial_heldout" not in sev.ALLOWED_SHADOW_TARGETS
    assert "ln7_heldout_packs" not in sev.ALLOWED_SHADOW_TARGETS
    assert "dual_coo_checklist" not in sev.ALLOWED_SHADOW_TARGETS
    assert sev.ALLOWED_SHADOW_TARGETS == frozenset({"goodhart_probes"})


# --------------------------------------------------------------------------
# ShadowEvaluatorAgent — start/stop lifecycle (no real sleep/DB)
# --------------------------------------------------------------------------

def test_shadow_evaluator_agent_start_stop_lifecycle():
    """start() launches the background task (which immediately blocks on its
    initial startup sleep — see _run_loop); stop() must cancel it cleanly
    without raising and flip _running to False. This is the same shape as
    FallbackDrillAgent's lifecycle (ln7_fallback_drill.py)."""
    sev = _sev()

    async def _go():
        agent = sev.ShadowEvaluatorAgent(db_pool=None, sample_interval_s=3600, divergence_interval_s=7200)
        await agent.start()
        assert agent._task is not None
        assert not agent._task.done()
        await agent.stop()
        assert agent._running is False
        assert agent._task.done()

    _run(_go())


def test_shadow_evaluator_agent_divergence_ratio_computed_from_intervals():
    sev = _sev()
    agent = sev.ShadowEvaluatorAgent(db_pool=None, sample_interval_s=3600, divergence_interval_s=7200)
    assert agent._divergence_ratio == 2  # 7200 / 3600
    assert agent.sample_interval == 3600
    assert agent.divergence_interval == 7200


def test_shadow_evaluator_agent_enforces_minimum_intervals():
    sev = _sev()
    agent = sev.ShadowEvaluatorAgent(db_pool=None, sample_interval_s=1, divergence_interval_s=1)
    assert agent.sample_interval == 3600
    assert agent.divergence_interval == 3600
