"""
End-to-end wiring smoke test (WIRE_WHAT_EXISTS Commit 6 — STEP 5).

Exercises the full ACTION TAKEN -> WHAT HAPPENED NEXT -> ADJUST BEHAVIOR loop
built across Commits 2-5, against REAL production functions (never
reimplemented), with in-memory fake tables standing in for Postgres. One
synthetic user with intentionally mixed identity keys
(hardware_id/username/UUID) exercises every KEY_MISMATCH seam documented in
docs/WIRING_AUDIT_REPORT.md in a single run:

  PASS 1 (Commit 2)  Attribution   — recall_crystals_for_context() ->
                                      _persist_chat_to_conversation_history()
                                      writes crystal_ids into
                                      conversation_history.metadata.
  PASS 2 (Commit 4)  Outcome join  — crystal_outcome_view resolves
                                      hardware_id / username / UUID through
                                      one `users` hub and attributes each
                                      recall to its response + nearest C_emo.
  PASS 3 (Commit 3)  Behavior      — NateCheckInAgent._outcome_backoff()
                       adaptation    escalates on ignored outreach and resets
                                      on an opened nudge — restraint only.
  PASS 4 (Commit 4)  Shadow        — DatabaseMaintenanceAgent.
                       integrity     _shadow_weighting_pass() proposes a
                                      capped delta for a crystal with enough
                                      outcome-linked recalls and NEVER
                                      mutates nate_intelligence_crystals.
  PASS 5             Trial         — the same loop run for a public_trial
                       isolation     fingerprint contributes zero metadata
                                      attribution, zero outcome-view
                                      attribution, and zero shadow signal.

crystal_outcome_view (migration 236) is a read-only Postgres VIEW — there is
no sqlite/asyncpg-in-memory engine available here, so
`_simulate_crystal_outcome_view()` below is a line-for-line Python mirror of
that SQL (same LEFT JOINs, same `users` OR-chain, same +/-2/10 minute
windows). It is exercised against tables built by the REAL recall/persist
code paths (Commit 2), not synthetic fixtures, so what it proves is real:
"if crystal_outcome_view's join conditions are honored, three-key identity
resolution + attribution + outcome-linking all resolve correctly."

_persist_chat_to_conversation_history is extracted from bridge_server.py via
regex + exec (established convention — see test_crystal_attribution.py and
test_dojo_model_tier_routing.py): bridge_server.py is a 27k-line module using
module-level `str | None` syntax that raises TypeError under the Python 3.9
test runner.
"""

import inspect
import json
import logging
import os
import pathlib
import re
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app.websocket.crystal_recall_bridge as crb  # noqa: E402
from app.services.nate_checkin_agent import (  # noqa: E402
    NateCheckInAgent,
    BACKOFF_STRETCH_THRESHOLD,
    BACKOFF_STRETCH_MULTIPLIER,
)
from app.services.db_maintenance_agent import (  # noqa: E402
    DatabaseMaintenanceAgent,
    SHADOW_MIN_SAMPLE_SIZE,
    SHADOW_MAX_ABS_DELTA,
)


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Shared minimal asyncpg stand-ins
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# PASS 1 support — recall + persist fakes
# ---------------------------------------------------------------------------


class _RecallConn:
    """Backs recall_crystals_for_context()'s non-global_only branch: the one
    real query it issues is the users OR-chain lookup for hardware_id."""

    def __init__(self, users):
        self._users = users

    async def fetchval(self, query, *args):
        q = " ".join(query.split())
        if "SELECT id FROM users WHERE hardware_id" in q:
            (identifier,) = args
            for u in self._users:
                if u["hardware_id"] == identifier or u["username"] == identifier or str(u["id"]) == identifier:
                    return u["id"]
            return None
        raise AssertionError(f"Unexpected fetchval query: {q!r}")


class _RecordingConn:
    """Backs _persist_chat_to_conversation_history(): captures the INSERT
    it issues so the metadata JSONB can be asserted on."""

    def __init__(self):
        self.calls = []

    async def execute(self, query, *args):
        self.calls.append((query, args))


def _load_persist_function():
    bridge_path = (
        pathlib.Path(__file__).resolve().parents[1] / "app" / "websocket" / "bridge_server.py"
    )
    src = bridge_path.read_text()
    m = re.search(
        r"^async def _persist_chat_to_conversation_history\(" r"[\s\S]*?"
        r"^        logger\.warning\(\"_persist_chat_to_conversation_history: %s\", e\)\n",
        src,
        re.MULTILINE,
    )
    assert m, "_persist_chat_to_conversation_history not found in bridge_server.py"
    ns = {
        "os": os,
        "json": json,
        "logger": logging.getLogger("test_wiring_smoke_e2e"),
        "Optional": Optional,
    }
    exec(compile(m.group(0), "bridge_server._persist_chat_to_conversation_history", "exec"), ns)
    return ns["_persist_chat_to_conversation_history"]


# ---------------------------------------------------------------------------
# PASS 2 support — Python mirror of crystal_outcome_view (migration 236)
# ---------------------------------------------------------------------------


def _resolve_user(users, identifier):
    """Mirrors the view's `u.username = crl.user_id OR u.hardware_id = crl.user_id
    OR u.id::text = crl.user_id` OR-chain (same pattern as _identity_resolver.py)."""
    for u in users:
        if u["username"] == identifier or u.get("hardware_id") == identifier or str(u["id"]) == identifier:
            return u
    return None


def _simulate_crystal_outcome_view(recall_log, users, crystals, conv_history, nevedal_metrics):
    """Line-for-line Python mirror of migration 236's crystal_outcome_view."""
    crystals_by_id = {c["id"]: c for c in crystals}
    rows = []
    for crl in recall_log:
        if crl.get("crystal_id") is None:
            continue
        user = _resolve_user(users, crl["user_id"])
        username = user["username"] if user else None
        user_uuid = user["id"] if user else None
        nic = crystals_by_id.get(crl["crystal_id"])
        recalled_at = crl["recalled_at"]
        window_lo = recalled_at - timedelta(minutes=2)
        window_hi = recalled_at + timedelta(minutes=10)

        ch_match = None
        if username is not None:
            candidates = [
                ch for ch in conv_history
                if ch["user_id"] == username
                and window_lo <= ch["created_at"] <= window_hi
                and crl["crystal_id"] in ((ch.get("metadata") or {}).get("crystal_ids") or [])
            ]
            candidates.sort(key=lambda c: c["created_at"])
            ch_match = candidates[0] if candidates else None

        nm_match = None
        if user_uuid is not None:
            nm_candidates = [
                nm for nm in nevedal_metrics
                if nm["user_id"] == user_uuid
                and window_lo <= nm["recorded_at"] <= window_hi
            ]
            nm_candidates.sort(key=lambda nm: abs((nm["recorded_at"] - recalled_at).total_seconds()))
            nm_match = nm_candidates[0] if nm_candidates else None

        rows.append({
            "recall_log_id": crl.get("id"),
            "crystal_id": crl["crystal_id"],
            "crystal_domain": nic["domain"] if nic else None,
            "crystal_confidence": nic["confidence"] if nic else None,
            "source": crl.get("source"),
            "recalled_at": recalled_at,
            "username": username,
            "user_uuid": user_uuid,
            "conversation_history_id": ch_match["id"] if ch_match else None,
            "response_at": ch_match["created_at"] if ch_match else None,
            "c_emo": nm_match["c_emo"] if nm_match else None,
            "c_emo_recorded_at": nm_match["recorded_at"] if nm_match else None,
        })
    return rows


def _aggregate_for_shadow(view_rows, min_sample_size):
    """Mirrors _shadow_weighting_pass()'s own
    `GROUP BY crystal_id HAVING COUNT(*) FILTER (WHERE c_emo IS NOT NULL) >= N`."""
    by_crystal = {}
    for r in view_rows:
        by_crystal.setdefault(r["crystal_id"], []).append(r)

    out = []
    for cid, rows in by_crystal.items():
        domain = None
        confidence = None
        c_emos = []
        for r in rows:
            if r["crystal_domain"] is not None:
                domain = r["crystal_domain"]
            if r["crystal_confidence"] is not None:
                confidence = r["crystal_confidence"]
            if r["c_emo"] is not None:
                c_emos.append(float(r["c_emo"]))
        if len(c_emos) >= min_sample_size:
            out.append({
                "crystal_id": cid,
                "domain": domain,
                "current_confidence": confidence,
                "sample_size": len(c_emos),
                "avg_c_emo": sum(c_emos) / len(c_emos),
            })
    return out


# ---------------------------------------------------------------------------
# PASS 3 support — check-in / nudge fake (same shape as test_checkin_backoff.py)
# ---------------------------------------------------------------------------


class _CheckinConn:
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


# ---------------------------------------------------------------------------
# PASS 4 support — shadow weighting fake (same shape as
# test_shadow_weighting_no_update.py)
# ---------------------------------------------------------------------------


class _ShadowConn:
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


def _view_row(crystal_id, domain, current_confidence, sample_size, avg_c_emo):
    return {
        "crystal_id": crystal_id, "domain": domain, "current_confidence": current_confidence,
        "sample_size": sample_size, "avg_c_emo": avg_c_emo,
    }


# ---------------------------------------------------------------------------
# The smoke test
# ---------------------------------------------------------------------------


class TestWiringSmokeE2E(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Save every crystal_recall_bridge attribute this test monkeypatches
        # so nothing leaks into other test modules sharing this process.
        self._orig_fast_recall = crb._fast_recall_crystals
        self._orig_reinforce = crb._reinforce_recalled_crystals
        self._orig_deep_recall = crb._deep_recall_crystals
        self._orig_get_deep_cache = crb._get_deep_cache
        self._orig_attribution_flag = crb._ENABLE_CRYSTAL_ATTRIBUTION

    async def asyncTearDown(self):
        crb._fast_recall_crystals = self._orig_fast_recall
        crb._reinforce_recalled_crystals = self._orig_reinforce
        crb._deep_recall_crystals = self._orig_deep_recall
        crb._get_deep_cache = self._orig_get_deep_cache
        crb._ENABLE_CRYSTAL_ATTRIBUTION = self._orig_attribution_flag

    async def test_action_outcome_adjust_loop_end_to_end(self):
        # -------------------------------------------------------------
        # Synthetic user with genuinely mixed identity keys:
        #   crystal_recall_log.user_id   -> HARDWARE_ID (TEXT)
        #   conversation_history.user_id -> USERNAME    (TEXT)
        #   nevedal_metrics.user_id      -> USER_UUID    (UUID)
        #   nate_checkins.user_id        -> USERNAME     (TEXT)
        #   nate_nudges.user_id          -> USER_UUID    (UUID)
        # -------------------------------------------------------------
        HARDWARE_ID = "HW_SMOKE_001"
        USERNAME = "smoke_user"
        USER_UUID = uuid.uuid4()
        NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

        users_table = [{"username": USERNAME, "id": USER_UUID, "hardware_id": HARDWARE_ID}]
        crystals_table = [
            {"id": 501, "domain": "coaching", "confidence": 0.55},
            {"id": 502, "domain": "coaching", "confidence": 0.60},
            {"id": 503, "domain": "coaching", "confidence": 0.50},
        ]
        crystal_recall_log_table = []
        conversation_history_table = []
        nevedal_metrics_table = []

        # === PASS 1 (Commit 2) — Attribution ===================================
        # Mocked process_interaction: recall injects three known crystal ids;
        # assert conversation_history.metadata for that turn contains exactly
        # those ids. Uses the REAL recall_crystals_for_context() and the REAL
        # (regex-extracted) _persist_chat_to_conversation_history().
        with self.subTest(pass_="1-attribution"):
            async def _fake_fast_recall(conn, user_uuid, query_text, max_user=5, max_global=3):
                return (
                    [],
                    [
                        {"id": 501, "crystal_text": "insight 501", "confidence": 0.55, "domain": "coaching"},
                        {"id": 502, "crystal_text": "insight 502", "confidence": 0.60, "domain": "coaching"},
                        {"id": 503, "crystal_text": "insight 503", "confidence": 0.50, "domain": "coaching"},
                    ],
                    {501, 502, 503},
                )

            async def _fake_reinforce(db_pool, hardware_id, crystal_ids, source):
                for cid in crystal_ids:
                    crystal_recall_log_table.append({
                        "id": len(crystal_recall_log_table) + 1,
                        "user_id": hardware_id,
                        "crystal_id": cid,
                        "source": source,
                        "recalled_at": NOW,
                    })

            async def _fake_deep_recall(*args, **kwargs):
                return None

            crb._fast_recall_crystals = _fake_fast_recall
            crb._reinforce_recalled_crystals = _fake_reinforce
            crb._deep_recall_crystals = _fake_deep_recall
            crb._get_deep_cache = lambda *a, **k: None
            crb._ENABLE_CRYSTAL_ATTRIBUTION = True

            recall_pool = _FakePool(_RecallConn(users_table))
            ctx = await crb.recall_crystals_for_context(
                recall_pool, HARDWARE_ID, max_results=8, source="bridge_chat",
            )
            import asyncio
            await asyncio.sleep(0)  # let the fire-and-forget reinforce task run

            crystal_ids = sorted(getattr(ctx, "crystal_ids", []))
            self.assertEqual(crystal_ids, [501, 502, 503])
            self.assertEqual(len(crystal_recall_log_table), 3)

            persist_fn = _load_persist_function()
            os.environ["ENABLE_CRYSTAL_ATTRIBUTION"] = "true"
            recording_conn = _RecordingConn()
            await persist_fn(
                _FakePool(recording_conn), USERNAME, "hello nate", "hi there",
                session_id="sess-smoke", turn_id="turn-smoke-1", crystal_ids=crystal_ids,
            )

            self.assertEqual(len(recording_conn.calls), 1)
            _query, args = recording_conn.calls[0]
            meta = json.loads(args[4])
            self.assertEqual(meta["turn_id"], "turn-smoke-1")
            self.assertEqual(meta["crystal_ids"], [501, 502, 503])

            # Mirror what that INSERT would have produced, for PASS 2's join.
            conversation_history_table.append({
                "id": 1, "user_id": USERNAME,
                "created_at": NOW + timedelta(seconds=5),
                "metadata": meta,
            })
            # One recorded C_emo outcome for this same turn (Commit 4's "outcome
            # recorded" edge — nevedal_metrics keyed by UUID, not username/hw_id).
            nevedal_metrics_table.append({
                "user_id": USER_UUID, "c_emo": 0.90,
                "recorded_at": NOW + timedelta(seconds=30),
            })

        # === PASS 2 (Commit 4 STEP 3) — Outcome join ============================
        # Query crystal_outcome_view (simulated) and assert three rows, all
        # attributed to the turn-1 response, all carrying the seeded C_emo —
        # proving hardware_id -> username -> UUID all resolve through the
        # single `users` hub in one pass.
        with self.subTest(pass_="2-outcome-join"):
            view_rows = _simulate_crystal_outcome_view(
                crystal_recall_log_table, users_table, crystals_table,
                conversation_history_table, nevedal_metrics_table,
            )
            self.assertEqual(len(view_rows), 3)
            self.assertEqual(sorted(r["crystal_id"] for r in view_rows), [501, 502, 503])
            for row in view_rows:
                self.assertEqual(row["username"], USERNAME)
                self.assertEqual(row["user_uuid"], USER_UUID)
                self.assertIsNotNone(row["conversation_history_id"])
                self.assertEqual(row["c_emo"], 0.90)

        # Seed 4 more outcome-linked recalls of crystal 501 only (separate,
        # non-overlapping +/-2/10-minute windows) so it — and only it — clears
        # SHADOW_MIN_SAMPLE_SIZE ahead of PASS 4. 502/503 stay at sample_size=1:
        # this is the restraint the shadow job is supposed to show (no data,
        # no proposal).
        for i, c_emo in enumerate((0.90, 0.85, 0.95, 0.80), start=1):
            t = NOW + timedelta(minutes=60 * i)
            crystal_recall_log_table.append({
                "id": len(crystal_recall_log_table) + 1, "user_id": HARDWARE_ID,
                "crystal_id": 501, "source": "bridge_chat", "recalled_at": t,
            })
            conversation_history_table.append({
                "id": len(conversation_history_table) + 1, "user_id": USERNAME,
                "created_at": t + timedelta(seconds=5),
                "metadata": {"turn_id": f"turn-smoke-seed-{i}", "crystal_ids": [501]},
            })
            nevedal_metrics_table.append({
                "user_id": USER_UUID, "c_emo": c_emo, "recorded_at": t + timedelta(seconds=30),
            })

        full_view_rows = _simulate_crystal_outcome_view(
            crystal_recall_log_table, users_table, crystals_table,
            conversation_history_table, nevedal_metrics_table,
        )
        aggregated_before_trial = _aggregate_for_shadow(full_view_rows, SHADOW_MIN_SAMPLE_SIZE)
        agg_501_before = next(a for a in aggregated_before_trial if a["crystal_id"] == 501)
        self.assertEqual(agg_501_before["sample_size"], 5)
        self.assertEqual({a["crystal_id"] for a in aggregated_before_trial}, {501})  # 502/503 below threshold

        # === PASS 3 (Commit 3) — Behavior adaptation ============================
        # Two ignored check-ins -> multiplier 2.0. Mark the most recent nudge
        # opened -> multiplier resets to 1.0. Mixed-key seam: nate_checkins
        # keyed by USERNAME, nate_nudges keyed by USER_UUID.
        with self.subTest(pass_="3-behavior-adaptation"):
            self.assertGreaterEqual(BACKOFF_STRETCH_THRESHOLD, 2)
            checkin_times = [NOW - timedelta(days=2), NOW - timedelta(days=1)]
            checkins = [
                {"user_id": USERNAME, "checkin_type": "client_72h", "status": "sent", "created_at": t}
                for t in checkin_times
            ]
            conn_ignored = _CheckinConn(users=users_table, checkins=checkins, nudges=[])
            agent_ignored = NateCheckInAgent(db_pool=_FakePool(conn_ignored), notification_system=None)
            backoff_ignored = await agent_ignored._outcome_backoff(USERNAME)
            self.assertEqual(backoff_ignored["consecutive_ignored"], 2)
            self.assertEqual(backoff_ignored["multiplier"], BACKOFF_STRETCH_MULTIPLIER)

            most_recent_checkin_at = checkin_times[-1]
            nudges = [{
                "user_id": USER_UUID, "nudge_type": "checkin_client_72h",
                "scheduled_at": most_recent_checkin_at + timedelta(minutes=2),
                "opened_at": most_recent_checkin_at + timedelta(minutes=10),
            }]
            conn_opened = _CheckinConn(users=users_table, checkins=checkins, nudges=nudges)
            agent_opened = NateCheckInAgent(db_pool=_FakePool(conn_opened), notification_system=None)
            backoff_reset = await agent_opened._outcome_backoff(USERNAME)
            self.assertEqual(backoff_reset["consecutive_ignored"], 0)
            self.assertEqual(backoff_reset["multiplier"], 1.0)

        # === PASS 4 (Commit 4 STEP 4) — Shadow integrity ========================
        # Run the shadow job manually against the aggregated (pre-trial) view.
        # Assert a proposal exists for crystal 501 with |delta| <= cap and a
        # populated basis, and that nate_intelligence_crystals is untouched.
        with self.subTest(pass_="4-shadow-integrity"):
            crystals_snapshot_before = [dict(c) for c in crystals_table]

            shadow_view_rows = [
                _view_row(a["crystal_id"], a["domain"], a["current_confidence"],
                          a["sample_size"], a["avg_c_emo"])
                for a in aggregated_before_trial
            ]
            shadow_conn = _ShadowConn(last_computed_at=None, view_rows=shadow_view_rows)
            shadow_agent = DatabaseMaintenanceAgent(db_pool=_FakePool(shadow_conn))
            inserted = await shadow_agent._shadow_weighting_pass()

            self.assertEqual(inserted, 1)  # only crystal 501 met SHADOW_MIN_SAMPLE_SIZE
            self.assertEqual(len(shadow_conn.inserted), 1)
            args = shadow_conn.inserted[0]
            # (crystal_id, domain, current_confidence, delta, sample_size, avg_c_emo, reasoning)
            self.assertEqual(args[0], 501)
            self.assertLessEqual(abs(args[3]), SHADOW_MAX_ABS_DELTA)
            self.assertGreater(args[3], 0)  # avg_c_emo ~0.875 > 0.5 -> positive proposal
            self.assertGreaterEqual(args[4], SHADOW_MIN_SAMPLE_SIZE)
            self.assertTrue(args[6])  # reasoning populated

            self.assertEqual(crystals_table, crystals_snapshot_before)  # byte-identical, never mutated

            # Redundant static guarantee, independent of the behavioral
            # assertions above: no SQL UPDATE against nate_intelligence_crystals
            # anywhere in the method actually exercised.
            source = inspect.getsource(DatabaseMaintenanceAgent._shadow_weighting_pass)
            self.assertEqual(re.findall(r"UPDATE\s+\w+\s+SET", source, re.IGNORECASE), [])
            self.assertNotIn("nate_intelligence_crystals SET", source)

        # === PASS 5 — Trial isolation ===========================================
        # Repeat PASS 1's recall for an anonymous public_trial fingerprint
        # (global_only=True, exactly as public_trial_gate.py calls it) and
        # deliberately never call the persist function for it — matching the
        # real trial path, which bypasses process_interaction() entirely.
        # Assert zero metadata attribution, zero outcome-view attribution,
        # zero shadow-relevant signal.
        with self.subTest(pass_="5-trial-isolation"):
            TRIAL_FP = "TRIAL_FP_999"  # no corresponding `users` row anywhere
            conv_history_len_before = len(conversation_history_table)

            trial_ctx = await crb.recall_crystals_for_context(
                _FakePool(_RecallConn(users_table)), TRIAL_FP,
                max_results=4, source="public_trial", global_only=True,
            )
            import asyncio
            await asyncio.sleep(0)

            # Recall happened (globals still surfaced to the trial prompt)...
            self.assertTrue(getattr(trial_ctx, "crystal_ids", None))
            # ...but nothing durable was ever attributed: persist_fn was never
            # called for this fingerprint, so conversation_history is unchanged.
            self.assertEqual(len(conversation_history_table), conv_history_len_before)

            full_view_with_trial = _simulate_crystal_outcome_view(
                crystal_recall_log_table, users_table, crystals_table,
                conversation_history_table, nevedal_metrics_table,
            )
            trial_rows = [r for r in full_view_with_trial if r["source"] == "public_trial"]
            self.assertTrue(trial_rows, "trial recall must still appear in crystal_recall_log")
            for row in trial_rows:
                self.assertIsNone(row["username"])
                self.assertIsNone(row["user_uuid"])
                self.assertIsNone(row["conversation_history_id"])
                self.assertIsNone(row["c_emo"])

            # The trial's unresolvable identity means it can supply neither a
            # response match nor a C_emo match, so it changes nothing about
            # what the shadow job would compute for crystal 501 (or anyone
            # else) -- zero shadow proposals attributable to the trial.
            aggregated_with_trial = _aggregate_for_shadow(full_view_with_trial, SHADOW_MIN_SAMPLE_SIZE)
            agg_501_after = next(a for a in aggregated_with_trial if a["crystal_id"] == 501)
            self.assertEqual(agg_501_after["sample_size"], agg_501_before["sample_size"])
            self.assertAlmostEqual(agg_501_after["avg_c_emo"], agg_501_before["avg_c_emo"], places=9)
            self.assertEqual({a["crystal_id"] for a in aggregated_with_trial}, {501})


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
