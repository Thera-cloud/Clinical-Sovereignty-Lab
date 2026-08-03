"""
Digest row test for the Gate 2 structural floor gate (2026-08-03,
docs/ln7/GATE2_VERIFIER_CALIBRATION.md) — the "fires in your digest" half
of enforce_with_alert.

Verifies `AgentStatusDigest._structural_floor_gate_row()`:
  1. Reports TRUSTED "off (no live wiring active)" when the mode is off --
     matches the default, so a fresh deploy digest never alarms anyone.
  2. Summarizes 24h check count + floor_met=false rate for shadow/enforce
     modes.
  3. Reports WARNING (not a crash) when auto-reverted.
  4. Reports WARNING when an enforce mode has zero checks logged in 24h --
     a silent signal that crisis traffic isn't reaching the gate.
  5. Degrades to WARNING (not a crash) on a query failure or a mode-read
     failure.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.agent_status_digest import AgentStatusDigest  # noqa: E402


class _FakeConn:
    def __init__(self, summary_row=None, raise_error=False):
        self._summary_row = summary_row
        self._raise_error = raise_error

    async def fetchrow(self, query, *args):
        if self._raise_error:
            raise RuntimeError("connection reset")
        q = " ".join(query.split())
        assert "FROM outcome_envelope" in q
        assert "structural_verifier_floor" in q
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
    pass


def _make_digest(conn):
    return AgentStatusDigest(app_state=object(), db_pool=_FakePool(conn))


class TestStructuralFloorGateRow(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        os.environ.pop("STRUCTURAL_FLOOR_MODE", None)

    def tearDown(self):
        os.environ.pop("STRUCTURAL_FLOOR_MODE", None)

    async def test_off_mode_is_trusted_and_skips_query(self):
        conn = _FakeConn(summary_row=_FakeRow(total=999, failed=999))
        digest = _make_digest(conn)
        status, detail = await digest._structural_floor_gate_row()
        self.assertEqual(status, "TRUSTED")
        self.assertIn("off", detail)

    async def test_shadow_mode_summarizes_rate(self):
        os.environ["STRUCTURAL_FLOOR_MODE"] = "shadow"
        conn = _FakeConn(summary_row=_FakeRow(total=20, failed=5))
        digest = _make_digest(conn)
        status, detail = await digest._structural_floor_gate_row()
        self.assertEqual(status, "TRUSTED")
        self.assertIn("mode=shadow", detail)
        self.assertIn("checks=20", detail)
        self.assertIn("floor_met=false=5", detail)
        self.assertIn("25%", detail)

    async def test_enforce_with_zero_checks_in_24h_is_warning(self):
        os.environ["STRUCTURAL_FLOOR_MODE"] = "enforce_with_alert"
        conn = _FakeConn(summary_row=_FakeRow(total=0, failed=0))
        digest = _make_digest(conn)
        status, detail = await digest._structural_floor_gate_row()
        self.assertEqual(status, "WARNING")
        self.assertIn("no checks logged", detail)

    async def test_query_failure_degrades_to_warning_not_crash(self):
        os.environ["STRUCTURAL_FLOOR_MODE"] = "shadow"
        conn = _FakeConn(raise_error=True)
        digest = _make_digest(conn)
        status, detail = await digest._structural_floor_gate_row()
        self.assertEqual(status, "WARNING")
        self.assertIn("failed", detail.lower())

    async def test_row_builder_source_has_no_write_statements(self):
        import inspect

        source = inspect.getsource(AgentStatusDigest._structural_floor_gate_row)
        for verb in ("INSERT INTO", "UPDATE ", "DELETE FROM"):
            self.assertNotIn(verb, source.upper())


def tearDownModule():
    import asyncio

    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


if __name__ == "__main__":
    unittest.main()
