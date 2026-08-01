"""Phase E6 — weekly digest offline fences (importlib — avoid numpy FPE).

Covers:
  - ln7_weekly_digest.iso_week(): stable ISO year-week bucketing.
  - ln7_weekly_digest.build_digest_text(): pure formatter, no DB/IO — covers
    empty-window and populated-window cases, and that it surfaces E2/E4/E5/E7/E8
    metrics without needing a live outcome_envelope table.
  - ln7_weekly_digest.run_weekly_digest_cycle(): report-only — never touches
    ceo_inbox, degrades gracefully per-query (e.g. missing `sig` column on a
    pre-migration-315 DB does not blank out totals/confounded stats), dedups
    by ISO week via skyeye_activity, and no-db returns ok=False without raising.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

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
    if name in sys.modules and getattr(sys.modules[name], "__file__", None) == str(path):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _digest_mod():
    return _load("app.jobs.ln7_weekly_digest", JOBS / "ln7_weekly_digest.py")


def test_iso_week_format():
    d = _digest_mod()
    # 2026-08-03 is a Monday in ISO week 32 of 2026.
    now = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
    assert d.iso_week(now) == "2026-W32"


def test_build_digest_text_empty_window():
    d = _digest_mod()
    body = d.build_digest_text(
        loop_counts=[],
        confounded_total=0,
        total_events=0,
        sig_present=0,
        attribution_present=0,
        suppress_active=[],
        anomaly_counts=[],
        window_start=datetime(2026, 7, 27, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )
    assert "report only" in body
    assert "No events recorded in window." in body
    assert "(none)" in body


def test_build_digest_text_populated_window_surfaces_all_phase_e_metrics():
    d = _digest_mod()
    body = d.build_digest_text(
        loop_counts=[
            {"loop_name": "ln7", "event_kind": "coding_outcome", "n": 10, "confounded_n": 2, "cost_usd": 1.5},
            {"loop_name": "marketing", "event_kind": "growth_claim", "n": 5, "confounded_n": 0, "cost_usd": 0.0},
        ],
        confounded_total=2,
        total_events=15,
        sig_present=12,
        attribution_present=9,
        suppress_active=[{"pattern_key": "foo:bar", "until_ts": "2026-09-01", "reason": "flaky"}],
        anomaly_counts=[{"kind": "confound_spike", "n": 3}],
        window_start=datetime(2026, 7, 27, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )
    assert "Total outcome_envelope events: 15" in body
    assert "Confounded (E5): 2 (13.3%)" in body
    assert "Signed rows present (E4" in body
    assert "attribution (E2)" in body
    assert "ln7 / coding_outcome: 10" in body
    assert "marketing / growth_claim: 5" in body
    assert "Active reverse-suppress patterns (E8): 1" in body
    assert "foo:bar until 2026-09-01" in body
    assert "confound_spike: 3" in body


class _FakeConn:
    def __init__(self, *, already_sent: bool = False, sig_column_missing: bool = False):
        self.already_sent = already_sent
        self.sig_column_missing = sig_column_missing
        self.executed: List[Any] = []

    async def fetchval(self, query, *args):
        if "ln7_weekly_digest_sent" in query:
            return 1 if self.already_sent else None
        if "sig IS NOT NULL" in query:
            if self.sig_column_missing:
                raise Exception('column "sig" of relation "outcome_envelope" does not exist')
            return 4
        return None

    async def fetchrow(self, query, *args):
        if "attribution_json" in query:
            return {"total": 20, "confounded_n": 3, "attr_n": 15}
        return None

    async def fetch(self, query, *args):
        if "GROUP BY 1, 2" in query:
            return [
                {
                    "loop_name": "ln7",
                    "event_kind": "coding_outcome",
                    "n": 20,
                    "confounded_n": 3,
                    "cost_usd": 2.0,
                }
            ]
        if "ln7_suppress_patterns" in query:
            return [{"pattern_key": "p1", "until_ts": "2026-09-01", "reason": "r"}]
        if "flywheel_anomaly" in query:
            return [{"kind": "confound_spike", "n": 1}]
        return []

    async def execute(self, query, *args):
        self.executed.append((query, args))


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


class _FakeNotifier:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.sent: List[Any] = []

    async def _send_email(self, to, subject, body, *args, **kwargs):
        if self.fail:
            raise RuntimeError("smtp down")
        self.sent.append((to, subject, body))


def test_run_weekly_digest_cycle_no_db_returns_ok_false():
    d = _digest_mod()
    result = asyncio.run(d.run_weekly_digest_cycle(None))
    assert result == {"ok": False, "error": "no_db"}


def test_run_weekly_digest_cycle_skips_when_already_sent_this_week():
    d = _digest_mod()
    conn = _FakeConn(already_sent=True)
    pool = _FakePool(conn)
    result = asyncio.run(d.run_weekly_digest_cycle(pool))
    assert result["ok"] is True
    assert result["skipped"] == "already_sent"
    assert conn.executed == []  # never marks-sent again, never emails


def test_run_weekly_digest_cycle_emails_and_marks_sent():
    d = _digest_mod()
    conn = _FakeConn(already_sent=False)
    pool = _FakePool(conn)
    notifier = _FakeNotifier()
    result = asyncio.run(d.run_weekly_digest_cycle(pool, notifier))
    assert result["ok"] is True
    assert result["emailed"] is True
    assert result["events"] == 20
    assert len(notifier.sent) == 1
    to, subject, body = notifier.sent[0]
    assert to == d.DIGEST_EMAIL
    assert "LN7 Flywheel Weekly Digest" in subject
    assert any("ln7_weekly_digest_sent" in q for q, _ in conn.executed)


def test_run_weekly_digest_cycle_degrades_when_sig_column_missing():
    """Pre-migration-315 DB: sig coverage query fails, but totals/confounded
    stats (from a separate query) must still populate — E6 must not go blind
    on E4 rollout races."""
    d = _digest_mod()
    conn = _FakeConn(already_sent=False, sig_column_missing=True)
    pool = _FakePool(conn)
    result = asyncio.run(d.run_weekly_digest_cycle(pool))
    assert result["ok"] is True
    assert result["events"] == 20  # totals query unaffected by sig query failure


def test_run_weekly_digest_cycle_email_failure_still_marks_sent_and_does_not_raise():
    d = _digest_mod()
    conn = _FakeConn(already_sent=False)
    pool = _FakePool(conn)
    notifier = _FakeNotifier(fail=True)
    result = asyncio.run(d.run_weekly_digest_cycle(pool, notifier))
    assert result["ok"] is True
    assert result["emailed"] is False
    assert any("ln7_weekly_digest_sent" in q for q, _ in conn.executed)
