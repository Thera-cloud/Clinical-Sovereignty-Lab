"""Unit tests for phi_audit (Slice 6a).

Covers: flag gating, fail-soft on missing db_pool / bad input, fields
coercion, role normalization, and correction rows.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("ENABLE_PHI_READ_LOG", "0")

from app.services import phi_audit  # noqa: E402


def _make_pool() -> tuple[MagicMock, AsyncMock]:
    """Build a fake asyncpg pool. Returns (pool, conn)."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")

    class _AcquireCtx:
        async def __aenter__(self_inner):
            return conn

        async def __aexit__(self_inner, *a):
            return None

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx())
    return pool, conn


class TestFlag(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("ENABLE_PHI_READ_LOG", None)

    def test_flag_off_by_default(self):
        os.environ.pop("ENABLE_PHI_READ_LOG", None)
        self.assertFalse(phi_audit.is_enabled())

    def test_flag_on_variants(self):
        for v in ("1", "true", "TRUE", "yes", "on"):
            os.environ["ENABLE_PHI_READ_LOG"] = v
            self.assertTrue(phi_audit.is_enabled(), f"failed for {v!r}")

    def test_flag_off_variants(self):
        for v in ("0", "false", "no", "off", ""):
            os.environ["ENABLE_PHI_READ_LOG"] = v
            self.assertFalse(phi_audit.is_enabled(), f"failed for {v!r}")


class TestFieldsCoercion(unittest.TestCase):
    def test_none_returns_empty(self):
        self.assertEqual(phi_audit._coerce_fields(None), [])

    def test_empty_iterable(self):
        self.assertEqual(phi_audit._coerce_fields([]), [])

    def test_drops_none_and_blank(self):
        out = phi_audit._coerce_fields(["a", None, "", "  ", "b"])
        self.assertEqual(out, ["a", "b"])

    def test_coerces_non_strings(self):
        out = phi_audit._coerce_fields(["x", 42, True])
        self.assertEqual(out, ["x", "42", "True"])

    def test_caps_at_64(self):
        out = phi_audit._coerce_fields([f"f{i}" for i in range(200)])
        self.assertEqual(len(out), 64)


class TestLogPhiRead(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("ENABLE_PHI_READ_LOG", None)

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)

    def test_flag_off_returns_false(self):
        os.environ["ENABLE_PHI_READ_LOG"] = "0"
        pool, conn = _make_pool()
        ok = self._run(phi_audit.log_phi_read(
            pool,
            actor_username="alice", actor_role="COACH",
            resource="sensitive_profile", endpoint="/api/x",
        ))
        self.assertFalse(ok)
        conn.execute.assert_not_awaited()

    def test_missing_db_pool_returns_false(self):
        os.environ["ENABLE_PHI_READ_LOG"] = "1"
        ok = self._run(phi_audit.log_phi_read(
            None,
            actor_username="alice", actor_role="COACH",
            resource="sensitive_profile", endpoint="/api/x",
        ))
        self.assertFalse(ok)

    def test_missing_required_field_returns_false(self):
        os.environ["ENABLE_PHI_READ_LOG"] = "1"
        pool, conn = _make_pool()
        ok = self._run(phi_audit.log_phi_read(
            pool,
            actor_username="", actor_role="COACH",
            resource="sensitive_profile", endpoint="/api/x",
        ))
        self.assertFalse(ok)
        conn.execute.assert_not_awaited()

    def test_happy_path_inserts_row(self):
        os.environ["ENABLE_PHI_READ_LOG"] = "1"
        pool, conn = _make_pool()
        ok = self._run(phi_audit.log_phi_read(
            pool,
            actor_username="coachn", actor_role="COACH",
            resource="sensitive_profile", endpoint="/api/coach/client/alice",
            subject_username="alice",
            fields=["trauma_history", "medications"],
            mfa_verified=True,
        ))
        self.assertTrue(ok)
        conn.execute.assert_awaited_once()
        # Verify the SQL and a couple of key params.
        call = conn.execute.await_args
        sql = call.args[0]
        self.assertIn("INSERT INTO phi_read_log", sql)
        # Positional args (after sql) — role should be uppercased, mfa True.
        args = call.args[1:]
        # actor_username at index 1
        self.assertEqual(args[1], "coachn")
        # actor_role at index 2
        self.assertEqual(args[2], "COACH")
        # subject_username at index 4
        self.assertEqual(args[4], "alice")
        # resource at index 5
        self.assertEqual(args[5], "sensitive_profile")

    def test_role_lowercase_is_normalized(self):
        os.environ["ENABLE_PHI_READ_LOG"] = "1"
        pool, conn = _make_pool()
        ok = self._run(phi_audit.log_phi_read(
            pool,
            actor_username="coachn", actor_role="coach",
            resource="sensitive_profile", endpoint="/x",
        ))
        self.assertTrue(ok)
        args = conn.execute.await_args.args[1:]
        self.assertEqual(args[2], "COACH")

    def test_unknown_role_becomes_system(self):
        os.environ["ENABLE_PHI_READ_LOG"] = "1"
        pool, conn = _make_pool()
        ok = self._run(phi_audit.log_phi_read(
            pool,
            actor_username="bot", actor_role="AGENT",
            resource="sensitive_profile", endpoint="/x",
        ))
        self.assertTrue(ok)
        args = conn.execute.await_args.args[1:]
        self.assertEqual(args[2], "SYSTEM")

    def test_db_error_returns_false_not_raise(self):
        os.environ["ENABLE_PHI_READ_LOG"] = "1"
        pool, conn = _make_pool()
        conn.execute.side_effect = RuntimeError("db down")
        ok = self._run(phi_audit.log_phi_read(
            pool,
            actor_username="coachn", actor_role="COACH",
            resource="sensitive_profile", endpoint="/x",
        ))
        self.assertFalse(ok)


class TestCorrection(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("ENABLE_PHI_READ_LOG", None)

    def _run(self, coro):
        return asyncio.run(coro)

    def test_correction_requires_flag(self):
        os.environ["ENABLE_PHI_READ_LOG"] = "0"
        pool, conn = _make_pool()
        ok = self._run(phi_audit.log_correction(
            pool, original_id=1, actor_username="admin", actor_role="ADMIN",
            note="wrong subject", resource="sensitive_profile", endpoint="/x",
        ))
        self.assertFalse(ok)
        conn.execute.assert_not_awaited()

    def test_correction_requires_note(self):
        os.environ["ENABLE_PHI_READ_LOG"] = "1"
        pool, conn = _make_pool()
        ok = self._run(phi_audit.log_correction(
            pool, original_id=1, actor_username="admin", actor_role="ADMIN",
            note="", resource="sensitive_profile", endpoint="/x",
        ))
        self.assertFalse(ok)

    def test_correction_happy_path(self):
        os.environ["ENABLE_PHI_READ_LOG"] = "1"
        pool, conn = _make_pool()
        ok = self._run(phi_audit.log_correction(
            pool, original_id=42, actor_username="admin", actor_role="ADMIN",
            note="wrong subject; actual subject was bob",
            resource="sensitive_profile", endpoint="/api/coach/client/alice",
            subject_username="bob",
        ))
        self.assertTrue(ok)
        conn.execute.assert_awaited_once()
        args = conn.execute.await_args.args[1:]
        # original_id at index 5 (actor, role, resource, endpoint, subject, id, note)
        self.assertEqual(args[5], 42)

    def test_correction_note_truncated(self):
        os.environ["ENABLE_PHI_READ_LOG"] = "1"
        pool, conn = _make_pool()
        long_note = "x" * 5000
        ok = self._run(phi_audit.log_correction(
            pool, original_id=1, actor_username="admin", actor_role="ADMIN",
            note=long_note, resource="r", endpoint="/e",
        ))
        self.assertTrue(ok)
        args = conn.execute.await_args.args[1:]
        self.assertEqual(len(args[6]), 2000)


if __name__ == "__main__":
    unittest.main()
