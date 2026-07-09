"""
Crystal confidence shadow-weighting contract test (WIRE_WHAT_EXISTS Commit 4
— STEP 3 crystal_outcome_view + STEP 4 shadow weighting).

Two invariants are enforced here:

  1. STATIC INVARIANT — nothing in db_maintenance_agent.py ever issues an
     UPDATE (or any other mutation) against nate_intelligence_crystals.
     Confidence is proposed only, via INSERT into crystal_confidence_shadow.
     This is asserted by scanning the module's own source text, not by
     mocking — a source-level ban is the strongest guarantee available
     short of a DB trigger.

  2. BEHAVIORAL INVARIANTS — DatabaseMaintenanceAgent._shadow_weighting_pass():
     - Skips crystals below SHADOW_MIN_SAMPLE_SIZE outcome-linked recalls.
     - Caps |proposed_delta| at SHADOW_MAX_ABS_DELTA regardless of how
       extreme avg_c_emo is.
     - Forces proposed_delta to exactly 0.0 for clinical/defense domains
       (SHADOW_FORCED_ZERO_DOMAINS), never letting outcome signal move a
       safety-critical crystal's confidence even in the shadow table.
     - Is gated to run at most once per SHADOW_WEIGHTING_INTERVAL_DAYS using
       the shadow table's own MAX(computed_at) — never in-memory state — so
       a process restart cannot cause it to run more often than intended.
"""
import inspect
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services import db_maintenance_agent as dma_module  # noqa: E402
from app.services.db_maintenance_agent import (  # noqa: E402
    DatabaseMaintenanceAgent,
    SHADOW_MIN_SAMPLE_SIZE,
    SHADOW_MAX_ABS_DELTA,
    SHADOW_DELTA_SCALE,
    SHADOW_FORCED_ZERO_DOMAINS,
    SHADOW_WEIGHTING_INTERVAL_DAYS,
)


def _now():
    return datetime.now(timezone.utc)


class TestNoUpdateOnLiveCrystals(unittest.TestCase):
    """STATIC INVARIANT — source-level ban on mutating nate_intelligence_crystals."""

    def test_module_source_never_updates_nate_intelligence_crystals(self):
        source = inspect.getsource(dma_module)
        # An UPDATE statement targeting the live crystals table, in any
        # whitespace/casing form, must never appear in this module.
        pattern = re.compile(
            r"UPDATE\s+nate_intelligence_crystals", re.IGNORECASE
        )
        matches = pattern.findall(source)
        self.assertEqual(
            matches, [],
            "db_maintenance_agent.py must never UPDATE nate_intelligence_crystals "
            "— confidence changes are proposals only, written to "
            "crystal_confidence_shadow.",
        )

    def test_shadow_weighting_pass_source_only_inserts(self):
        source = inspect.getsource(DatabaseMaintenanceAgent._shadow_weighting_pass)
        self.assertIn("INSERT INTO crystal_confidence_shadow", source)
        # No SQL UPDATE statement anywhere in the method body (docstring prose
        # mentioning "UPDATE" as an English word is fine — only a real SQL
        # UPDATE keyword followed by a table name would match this).
        sql_update_pattern = re.compile(r"UPDATE\s+\w+\s+SET", re.IGNORECASE)
        self.assertEqual(sql_update_pattern.findall(source), [])
        self.assertNotIn("nate_intelligence_crystals SET", source)


class _FakeConn:
    """Minimal asyncpg-connection stand-in dispatched by SQL substring match."""

    def __init__(self, last_computed_at=None, view_rows=None):
        self._last_computed_at = last_computed_at
        self._view_rows = view_rows or []
        self.inserted = []

    async def fetchval(self, query, *args):
        q = " ".join(query.split())
        if "MAX(computed_at) FROM crystal_confidence_shadow" in q:
            return self._last_computed_at
        raise AssertionError(f"Unexpected fetchval query: {q!r}")

    async def fetch(self, query, *args):
        q = " ".join(query.split())
        if "FROM crystal_outcome_view" in q:
            return list(self._view_rows)
        raise AssertionError(f"Unexpected fetch query: {q!r}")

    async def execute(self, query, *args):
        q = " ".join(query.split())
        if "INSERT INTO crystal_confidence_shadow" in q:
            self.inserted.append(args)
            return None
        raise AssertionError(f"Unexpected execute query: {q!r}")


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


def _row(crystal_id, domain, current_confidence, sample_size, avg_c_emo):
    return {
        "crystal_id": crystal_id,
        "domain": domain,
        "current_confidence": current_confidence,
        "sample_size": sample_size,
        "avg_c_emo": avg_c_emo,
    }


def _make_agent(conn):
    return DatabaseMaintenanceAgent(db_pool=_FakePool(conn))


class TestShadowWeightingPass(unittest.IsolatedAsyncioTestCase):
    async def test_no_prior_run_computes_and_inserts(self):
        conn = _FakeConn(
            last_computed_at=None,
            view_rows=[_row(101, "marketing", 0.55, SHADOW_MIN_SAMPLE_SIZE, 0.9)],
        )
        agent = _make_agent(conn)
        inserted = await agent._shadow_weighting_pass()
        self.assertEqual(inserted, 1)
        self.assertEqual(len(conn.inserted), 1)
        args = conn.inserted[0]
        # (crystal_id, domain, current_confidence, delta, sample_size, avg_c_emo, reasoning)
        self.assertEqual(args[0], 101)
        self.assertEqual(args[1], "marketing")
        self.assertGreater(args[3], 0)  # positive avg_c_emo -> positive delta

    async def test_recent_prior_run_skips_entirely(self):
        conn = _FakeConn(
            last_computed_at=_now() - timedelta(days=SHADOW_WEIGHTING_INTERVAL_DAYS - 1),
            view_rows=[_row(101, "marketing", 0.55, SHADOW_MIN_SAMPLE_SIZE, 0.9)],
        )
        agent = _make_agent(conn)
        inserted = await agent._shadow_weighting_pass()
        self.assertEqual(inserted, 0)
        self.assertEqual(conn.inserted, [])

    async def test_stale_prior_run_runs_again(self):
        conn = _FakeConn(
            last_computed_at=_now() - timedelta(days=SHADOW_WEIGHTING_INTERVAL_DAYS + 1),
            view_rows=[_row(101, "marketing", 0.55, SHADOW_MIN_SAMPLE_SIZE, 0.9)],
        )
        agent = _make_agent(conn)
        inserted = await agent._shadow_weighting_pass()
        self.assertEqual(inserted, 1)

    async def test_delta_is_capped_at_max_abs_delta(self):
        # An out-of-[0,1] avg_c_emo (C_emo is not formula-bounded to [0,1] —
        # see nevedal_engine.py) would blow past the cap without clamping.
        conn = _FakeConn(
            view_rows=[_row(202, "coaching", 0.40, SHADOW_MIN_SAMPLE_SIZE, 5.0)],
        )
        agent = _make_agent(conn)
        await agent._shadow_weighting_pass()
        delta = conn.inserted[0][3]
        raw_delta_would_have_been = (5.0 - 0.5) * SHADOW_DELTA_SCALE
        self.assertGreater(raw_delta_would_have_been, SHADOW_MAX_ABS_DELTA)  # proves clamp is exercised
        self.assertLessEqual(abs(delta), SHADOW_MAX_ABS_DELTA)
        self.assertAlmostEqual(delta, SHADOW_MAX_ABS_DELTA, places=6)

    async def test_delta_capped_negative_direction_too(self):
        conn = _FakeConn(
            view_rows=[_row(203, "coaching", 0.40, SHADOW_MIN_SAMPLE_SIZE, -3.0)],
        )
        agent = _make_agent(conn)
        await agent._shadow_weighting_pass()
        delta = conn.inserted[0][3]
        raw_delta_would_have_been = (-3.0 - 0.5) * SHADOW_DELTA_SCALE
        self.assertLess(raw_delta_would_have_been, -SHADOW_MAX_ABS_DELTA)  # proves clamp is exercised
        self.assertLessEqual(abs(delta), SHADOW_MAX_ABS_DELTA)
        self.assertAlmostEqual(delta, -SHADOW_MAX_ABS_DELTA, places=6)

    async def test_clinical_domain_forced_to_zero_delta(self):
        for domain in SHADOW_FORCED_ZERO_DOMAINS:
            conn = _FakeConn(
                view_rows=[_row(301, domain, 0.80, SHADOW_MIN_SAMPLE_SIZE, 1.0)],
            )
            agent = _make_agent(conn)
            inserted = await agent._shadow_weighting_pass()
            self.assertEqual(inserted, 1, f"domain={domain} should still be recorded")
            delta = conn.inserted[0][3]
            self.assertEqual(
                delta, 0.0,
                f"domain={domain} must be forced to exactly 0 delta regardless of "
                f"outcome signal — this is the safety-critical restraint guarantee.",
            )

    async def test_neutral_avg_c_emo_yields_near_zero_delta(self):
        conn = _FakeConn(
            view_rows=[_row(401, "culture", 0.50, SHADOW_MIN_SAMPLE_SIZE, 0.5)],
        )
        agent = _make_agent(conn)
        await agent._shadow_weighting_pass()
        delta = conn.inserted[0][3]
        self.assertAlmostEqual(delta, 0.0, places=6)

    async def test_query_enforces_min_sample_size_via_having(self):
        # The HAVING clause filtering by SHADOW_MIN_SAMPLE_SIZE lives in the SQL
        # text itself (asserted against the fake's dispatch), not in Python —
        # this test just verifies the constant is embedded in the query the
        # agent actually issues.
        captured = {}

        class _CapturingConn(_FakeConn):
            async def fetch(self, query, *args):
                captured["query"] = " ".join(query.split())
                return []

        conn = _CapturingConn()
        agent = _make_agent(conn)
        await agent._shadow_weighting_pass()
        self.assertIn(f">= {SHADOW_MIN_SAMPLE_SIZE}", captured["query"])

    async def test_db_error_is_swallowed_and_returns_zero(self):
        class _ExplodingConn(_FakeConn):
            async def fetchval(self, query, *args):
                raise RuntimeError("connection reset")

        agent = _make_agent(_ExplodingConn())
        inserted = await agent._shadow_weighting_pass()
        self.assertEqual(inserted, 0)


def tearDownModule():
    """Restore a fresh main-thread event loop after IsolatedAsyncioTestCase
    runs — see test_checkin_backoff.py::tearDownModule for the full
    explanation. Prevents this file's async test style from poisoning
    later-collected suites that use the legacy asyncio.get_event_loop()
    auto-create pattern."""
    import asyncio
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


if __name__ == "__main__":
    unittest.main()
