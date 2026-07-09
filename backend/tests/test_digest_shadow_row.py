"""
Digest row test (WIRE_WHAT_EXISTS Commit 5 — surface crystal_confidence_shadow
proposals in AgentStatusDigest without ever acting on them).

Verifies `AgentStatusDigest._row_crystal_confidence_shadow()`:
  1. Reports "no proposals" informationally when the shadow table has no
     rows in the last 8 days — never an error, never a WARNING/FAILED.
  2. Summarizes count / nonzero count / max |delta| / timestamp when
     proposals exist.
  3. Degrades to a WARNING (not a crash) if the query itself fails.
  4. Never issues anything but a read (SELECT) against the shadow table —
     this row builder has no business writing to anything.
"""
import inspect
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.agent_status_digest import AgentStatusDigest  # noqa: E402


def _now():
    return datetime.now(timezone.utc)


class _FakeConn:
    def __init__(self, summary_row=None, raise_error=False):
        self._summary_row = summary_row
        self._raise_error = raise_error

    async def fetchrow(self, query, *args):
        if self._raise_error:
            raise RuntimeError("connection reset")
        q = " ".join(query.split())
        assert "FROM crystal_confidence_shadow" in q
        assert "SELECT" in q.upper()
        return self._summary_row


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


class _FakeRow(dict):
    """dict subclass so asyncpg-style row["col"] access works in the source."""


def _make_digest(conn):
    return AgentStatusDigest(app_state=object(), db_pool=_FakePool(conn))


class TestCrystalConfidenceShadowRow(unittest.IsolatedAsyncioTestCase):
    async def test_no_recent_proposals_is_informational_not_a_failure(self):
        conn = _FakeConn(summary_row=_FakeRow(
            proposal_count=0, last_computed_at=None, nonzero_count=0, max_abs_delta=None
        ))
        digest = _make_digest(conn)
        status, name, detail = await digest._row_crystal_confidence_shadow()
        self.assertEqual(status, "INFO")
        self.assertIn("No proposals", detail)

    async def test_none_row_is_informational_not_a_failure(self):
        conn = _FakeConn(summary_row=None)
        digest = _make_digest(conn)
        status, name, detail = await digest._row_crystal_confidence_shadow()
        self.assertEqual(status, "INFO")

    async def test_recent_proposals_summarized(self):
        ts = _now() - timedelta(hours=3)
        conn = _FakeConn(summary_row=_FakeRow(
            proposal_count=12, last_computed_at=ts, nonzero_count=9, max_abs_delta=0.02
        ))
        digest = _make_digest(conn)
        status, name, detail = await digest._row_crystal_confidence_shadow()
        self.assertEqual(status, "INFO")
        self.assertIn("12", detail)
        self.assertIn("9", detail)
        self.assertIn("0.0200", detail)
        self.assertIn("never applied", detail.lower())

    async def test_query_failure_degrades_to_warning_not_crash(self):
        conn = _FakeConn(raise_error=True)
        digest = _make_digest(conn)
        status, name, detail = await digest._row_crystal_confidence_shadow()
        self.assertEqual(status, "WARNING")
        self.assertIn("Query failed", detail)

    def test_row_builder_source_has_no_write_statements(self):
        source = inspect.getsource(AgentStatusDigest._row_crystal_confidence_shadow)
        for verb in ("INSERT INTO", "UPDATE ", "DELETE FROM"):
            self.assertNotIn(verb, source.upper())


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
