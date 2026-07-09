"""
Check-in outcome backoff contract test (WIRE_WHAT_EXISTS Commit 3 — STEP 2).

Verifies `NateCheckInAgent._outcome_backoff()`:

  1. Reads `nate_checkins` (keyed by `username`) and `nate_nudges` (keyed by
     `users.id` UUID) through exactly one explicit `users` SELECT — never by
     comparing a username string to a UUID column directly (the audited
     KEY_MISMATCH seam). Test `test_mixed_key_seam_nudge_open_resets_streak`
     exercises this with a REAL mixed-key pair (checkin row keyed by
     username, nudge row keyed by the resolved UUID for that same person).
  2. Is restraint-only: the multiplier floor is 1.0 (never < 1.0), and it
     only escalates to a stretch multiplier or channel restriction as
     *consecutive ignored* outreach count grows — never the reverse.
  3. A response (checkin.status != 'sent') OR an opened paired nudge resets
     the consecutive-ignored streak to 0.
  4. `_handle_client`'s existing snooze/suspension gate (`_should_suspend_outreach`)
     still short-circuits BEFORE backoff is ever computed — Commit 3 must not
     change that precedence.
"""
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.nate_checkin_agent import (  # noqa: E402
    NateCheckInAgent,
    BACKOFF_STRETCH_THRESHOLD,
    BACKOFF_INAPP_ONLY_THRESHOLD,
    BACKOFF_STRETCH_MULTIPLIER,
)


def _now():
    return datetime.now(timezone.utc)


class _FakeConn:
    """Minimal asyncpg-connection stand-in dispatched by SQL substring match."""

    def __init__(self, users=None, checkins=None, nudges=None):
        self.users = users or []
        self.checkins = checkins or []
        self.nudges = nudges or []

    async def fetchval(self, query, *args):
        q = " ".join(query.split())
        if "SELECT id FROM users WHERE username" in q:
            (username,) = args
            for u in self.users:
                if u["username"] == username:
                    return u["id"]
            return None
        if "SELECT opened_at FROM nate_nudges" in q:
            user_id, nudge_type, created_at, window_minutes = args
            window = timedelta(minutes=int(window_minutes))
            candidates = [
                n for n in self.nudges
                if n["user_id"] == user_id and n["nudge_type"] == nudge_type
                and created_at <= n["scheduled_at"] <= created_at + window
            ]
            candidates.sort(key=lambda n: n["scheduled_at"])
            return candidates[0]["opened_at"] if candidates else None
        raise AssertionError(f"Unexpected fetchval query: {q!r}")

    async def fetch(self, query, *args):
        q = " ".join(query.split())
        if "SELECT checkin_type, status, created_at" in q and "FROM nate_checkins" in q:
            username, limit = args
            rows = [c for c in self.checkins if c["user_id"] == username]
            rows.sort(key=lambda c: c["created_at"], reverse=True)
            return list(rows[: int(limit)])
        raise AssertionError(f"Unexpected fetch query: {q!r}")

    async def execute(self, query, *args):
        return None


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


def _make_agent(conn):
    return NateCheckInAgent(db_pool=_FakePool(conn), notification_system=None)


class TestOutcomeBackoff(unittest.IsolatedAsyncioTestCase):
    async def test_zero_ignored_is_no_backoff(self):
        conn = _FakeConn(users=[{"username": "alice", "id": uuid.uuid4()}], checkins=[])
        agent = _make_agent(conn)
        result = await agent._outcome_backoff("alice")
        self.assertEqual(result["consecutive_ignored"], 0)
        self.assertEqual(result["multiplier"], 1.0)
        self.assertFalse(result["channel_restricted"])

    async def test_below_stretch_threshold_no_backoff(self):
        assert BACKOFF_STRETCH_THRESHOLD >= 2
        now = _now()
        conn = _FakeConn(
            users=[{"username": "bob", "id": uuid.uuid4()}],
            checkins=[
                {"user_id": "bob", "checkin_type": "client_72h", "status": "sent",
                 "created_at": now - timedelta(days=3)},
            ],
        )
        agent = _make_agent(conn)
        result = await agent._outcome_backoff("bob")
        self.assertEqual(result["consecutive_ignored"], 1)
        self.assertEqual(result["multiplier"], 1.0)
        self.assertFalse(result["channel_restricted"])

    async def test_reaching_stretch_threshold_doubles_multiplier(self):
        now = _now()
        checkins = [
            {"user_id": "carol", "checkin_type": "client_72h", "status": "sent",
             "created_at": now - timedelta(days=i)}
            for i in range(1, BACKOFF_STRETCH_THRESHOLD + 1)
        ]
        conn = _FakeConn(users=[{"username": "carol", "id": uuid.uuid4()}], checkins=checkins)
        agent = _make_agent(conn)
        result = await agent._outcome_backoff("carol")
        self.assertEqual(result["consecutive_ignored"], BACKOFF_STRETCH_THRESHOLD)
        self.assertEqual(result["multiplier"], BACKOFF_STRETCH_MULTIPLIER)
        self.assertFalse(result["channel_restricted"])

    async def test_reaching_inapp_only_threshold_restricts_channel(self):
        now = _now()
        checkins = [
            {"user_id": "dave", "checkin_type": "client_72h", "status": "sent",
             "created_at": now - timedelta(days=i)}
            for i in range(1, BACKOFF_INAPP_ONLY_THRESHOLD + 1)
        ]
        conn = _FakeConn(users=[{"username": "dave", "id": uuid.uuid4()}], checkins=checkins)
        agent = _make_agent(conn)
        result = await agent._outcome_backoff("dave")
        self.assertEqual(result["consecutive_ignored"], BACKOFF_INAPP_ONLY_THRESHOLD)
        self.assertTrue(result["channel_restricted"])
        # Restraint floor: even at the harshest tier the multiplier never
        # drops below 1.0 and never exceeds the single configured stretch.
        self.assertEqual(result["multiplier"], BACKOFF_STRETCH_MULTIPLIER)

    async def test_a_response_resets_the_streak(self):
        """Most recent checkin was answered (status='responded') -> streak
        resets to 0 even though older checkins were ignored."""
        now = _now()
        checkins = [
            {"user_id": "erin", "checkin_type": "client_72h", "status": "responded",
             "created_at": now - timedelta(days=1)},
            {"user_id": "erin", "checkin_type": "client_72h", "status": "sent",
             "created_at": now - timedelta(days=2)},
            {"user_id": "erin", "checkin_type": "client_72h", "status": "sent",
             "created_at": now - timedelta(days=3)},
        ]
        conn = _FakeConn(users=[{"username": "erin", "id": uuid.uuid4()}], checkins=checkins)
        agent = _make_agent(conn)
        result = await agent._outcome_backoff("erin")
        self.assertEqual(result["consecutive_ignored"], 0)
        self.assertEqual(result["multiplier"], 1.0)

    async def test_mixed_key_seam_nudge_open_resets_streak(self):
        """Real mixed-key exercise: nate_checkins row keyed by username,
        nate_nudges row keyed by the users.id UUID for that SAME person.
        The most recent checkin has status='sent' (never answered by SMS/
        email) but its paired in-app nudge WAS opened within the pairing
        window -> that counts as a response and resets the streak.

        This can only pass if _outcome_backoff performs the
        username -> UUID resolution before joining to nate_nudges; a naive
        `nate_checkins.user_id = nate_nudges.user_id` comparison would never
        match (str vs UUID) and this test would see consecutive_ignored=1,
        not 0.
        """
        now = _now()
        user_uuid = uuid.uuid4()
        checkin_created_at = now - timedelta(days=1)
        checkins = [
            {"user_id": "frank", "checkin_type": "client_72h", "status": "sent",
             "created_at": checkin_created_at},
        ]
        nudges = [
            {"user_id": user_uuid, "nudge_type": "checkin_client_72h",
             "scheduled_at": checkin_created_at + timedelta(minutes=2),
             "opened_at": checkin_created_at + timedelta(minutes=10)},
        ]
        conn = _FakeConn(
            users=[{"username": "frank", "id": user_uuid}],
            checkins=checkins,
            nudges=nudges,
        )
        agent = _make_agent(conn)
        result = await agent._outcome_backoff("frank")
        self.assertEqual(result["consecutive_ignored"], 0)
        self.assertEqual(result["multiplier"], 1.0)

    async def test_mixed_key_seam_unopened_nudge_still_counts_as_ignored(self):
        """Same mixed-key shape as above, but the paired nudge was never
        opened (opened_at IS NULL) -> counts as ignored, proving the join
        itself (not just "any nudge exists") drives the reset."""
        now = _now()
        user_uuid = uuid.uuid4()
        checkin_created_at = now - timedelta(days=1)
        checkins = [
            {"user_id": "grace", "checkin_type": "client_72h", "status": "sent",
             "created_at": checkin_created_at},
        ]
        nudges = [
            {"user_id": user_uuid, "nudge_type": "checkin_client_72h",
             "scheduled_at": checkin_created_at + timedelta(minutes=2),
             "opened_at": None},
        ]
        conn = _FakeConn(
            users=[{"username": "grace", "id": user_uuid}],
            checkins=checkins,
            nudges=nudges,
        )
        agent = _make_agent(conn)
        result = await agent._outcome_backoff("grace")
        self.assertEqual(result["consecutive_ignored"], 1)

    async def test_unresolvable_username_does_not_crash_and_still_counts_ignored(self):
        """No matching `users` row for this username (edge case): the nudge
        lookup can't run (no UUID to join on), but the checkin-status walk
        must still work off nate_checkins alone."""
        now = _now()
        checkins = [
            {"user_id": "ghost", "checkin_type": "client_72h", "status": "sent",
             "created_at": now - timedelta(days=1)},
        ]
        conn = _FakeConn(users=[], checkins=checkins, nudges=[])
        agent = _make_agent(conn)
        result = await agent._outcome_backoff("ghost")
        self.assertEqual(result["consecutive_ignored"], 1)

    async def test_db_error_fails_closed_to_no_backoff(self):
        """If the backoff lookup itself errors, the agent must fall back to
        multiplier=1.0 (i.e. behave as if Commit 3 didn't exist) rather than
        raise and break the check-in cycle."""
        class _ExplodingConn(_FakeConn):
            async def fetchval(self, query, *args):
                raise RuntimeError("db unavailable")

        conn = _ExplodingConn()
        agent = _make_agent(conn)
        result = await agent._outcome_backoff("whoever")
        self.assertEqual(result["multiplier"], 1.0)
        self.assertFalse(result["channel_restricted"])


class TestSnoozePrecedenceUnchanged(unittest.IsolatedAsyncioTestCase):
    async def test_suspend_outreach_gate_still_short_circuits_before_backoff(self):
        """Commit 3 inserts _outcome_backoff() AFTER _should_suspend_outreach()
        in _handle_client. Verify that precedence: when suspended, backoff is
        never computed and no outreach/check-in is recorded."""
        conn = _FakeConn()
        agent = _make_agent(conn)
        agent._outcome_backoff = AsyncMock(side_effect=AssertionError(
            "backoff must not be computed while outreach is suspended"))
        agent._send_client_outreach = AsyncMock()
        agent._record_checkin = AsyncMock()

        with patch.object(agent, "_should_suspend_outreach", return_value=True):
            await agent._handle_client(
                conn=conn, now=_now(), username="hank", hw_id="HW_HANK",
                name="Hank", profile={"safe_silence_mode_state": {"state": "active"}},
                hours_inactive=999.0,
            )

        agent._outcome_backoff.assert_not_called()
        agent._send_client_outreach.assert_not_called()
        agent._record_checkin.assert_not_called()


def tearDownModule():
    """Restore a fresh main-thread event loop after IsolatedAsyncioTestCase
    runs. unittest.IsolatedAsyncioTestCase calls asyncio.set_event_loop(None)
    on teardown, which sets asyncio's internal _set_called flag and disables
    get_event_loop()'s auto-create fallback for the REST of the pytest
    session — breaking any later-collected suite that still uses the legacy
    `asyncio.get_event_loop().run_until_complete(...)` pattern (several
    pre-existing suites do). This is a test-infrastructure side effect of
    this file's async test style, not a production code change, so the fix
    is scoped here rather than touching those pre-existing suites."""
    import asyncio
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


if __name__ == "__main__":
    unittest.main()
