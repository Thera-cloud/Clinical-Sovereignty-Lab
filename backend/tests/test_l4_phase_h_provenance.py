"""Phase H / R6: PHASE_H_OPEN promote gate + N>=5 provenance-independent
users gate for the L4 therapeutic rule loop (offline seams).

Plan §H1: "crisis / SI / escalation never trainable — export AND register.
Export generalization gate: N>=5 provenance-independent users (distinct
payment lineage / device fingerprints / coach assignments), not merely N>=5
usernames. Promoted therapeutic rules also sit under the R1 Goodhart drift
sentinel." The crisis/SI/escalation refusal is already covered by
`promotion_invariant_refusal` (see test_l4_credibility_evidence.py). This
file covers the two new gates added on top of it.

Isolation discipline: this repo has a documented class of test-pollution
bugs from unrestored `sys.modules` / `os.environ` monkeypatches (see
test_l3_outcome_recall_and_gates.py history). Every mutation here goes
through `unittest.mock.patch.dict`, which guarantees restoration on exit
even if an assertion raises mid-test — no manual "reset at the end of the
test" lines that a failure could skip.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1] / "app" / "services"


def _load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@contextmanager
def _feature_flags_stub(enabled: bool, *, raise_error: bool = False):
    """Stub app.services.ln7_feature_flags for the duration of the `with`
    block only, so promote_rule's dynamic import of flag_enabled() resolves
    to a controllable async fn without touching the real module (which
    needs a live db_pool).

    Uses mock.patch.dict(sys.modules, ...) so the prior state — present or
    absent — is restored on exit even if the test body raises. `app` /
    `app.services` are only added to the override set when they are not
    already real, loaded packages in this process, so a real import earlier
    in the same pytest session is never clobbered.
    """
    stub = types.ModuleType("app.services.ln7_feature_flags")

    async def _flag_enabled(_db_pool, _key, *, default: bool = False) -> bool:
        if raise_error:
            raise RuntimeError("simulated flag lookup failure")
        return enabled

    stub.flag_enabled = _flag_enabled  # type: ignore[attr-defined]

    overrides: dict = {"app.services.ln7_feature_flags": stub}
    if "app" not in sys.modules:
        overrides["app"] = types.ModuleType("app")
    if "app.services" not in sys.modules:
        overrides["app.services"] = types.ModuleType("app.services")

    with patch.dict(sys.modules, overrides):
        yield stub


class _Conn:
    """Reusable fake asyncpg connection — sandbox row present, soft class,
    always ready to "succeed" the transaction unless a gate refuses first."""

    def __init__(self, audits: list):
        self._audits = audits

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    def transaction(self):
        return self

    async def fetchrow(self, sql, *args):
        return {
            "condition_json": json.dumps({"gate_class": "sleep_aid"}),
            "action_json": json.dumps({"type": "suppress_soft_followup"}),
            "status": "sandbox",
        }

    async def execute(self, sql, *args):
        self._audits.append(args)

    async def fetchval(self, *a):
        return 1  # truthy "id" for the RETURNING id UPDATE


def _pool_with(audits: list) -> MagicMock:
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_Conn(audits))
    return pool


class TestPhaseHOpenGate(unittest.IsolatedAsyncioTestCase):
    async def test_promote_refused_when_phase_h_closed(self):
        env = {
            "ENABLE_LN_RULE_LOOP": "true",
            "LN_RULE_DUAL_COO_NOTIFY": "false",
            "LN_RULE_REQUIRE_PHASE_H": "true",
            "LN_RULE_PROMOTE_MIN_PROVENANCE": "0",
        }
        with patch.dict(os.environ, env), _feature_flags_stub(enabled=False):
            mod = _load("ln_rule_ph_closed", "ln_rule_loop.py")
            audits: list = []
            ok = await mod.promote_rule(
                _pool_with(audits),
                rule_key="soft_gate.sleep_aid.followup_suppress",
                version=1,
            )
        self.assertFalse(ok)
        self.assertTrue(any("PHASE_H_OPEN" in str(a) for a in audits))

    async def test_promote_refused_when_phase_h_lookup_errors(self):
        """Fail-closed: a broken flag lookup must refuse, never silently pass."""
        env = {
            "ENABLE_LN_RULE_LOOP": "true",
            "LN_RULE_DUAL_COO_NOTIFY": "false",
            "LN_RULE_REQUIRE_PHASE_H": "true",
            "LN_RULE_PROMOTE_MIN_PROVENANCE": "0",
        }
        with patch.dict(os.environ, env), _feature_flags_stub(
            enabled=True, raise_error=True,
        ):
            mod = _load("ln_rule_ph_error", "ln_rule_loop.py")
            audits: list = []
            ok = await mod.promote_rule(
                _pool_with(audits),
                rule_key="soft_gate.sleep_aid.followup_suppress",
                version=1,
            )
        self.assertFalse(ok)

    async def test_promote_succeeds_when_phase_h_open(self):
        env = {
            "ENABLE_LN_RULE_LOOP": "true",
            "LN_RULE_DUAL_COO_NOTIFY": "false",
            "LN_RULE_REQUIRE_PHASE_H": "true",
            "LN_RULE_PROMOTE_MIN_PROVENANCE": "0",
        }
        with patch.dict(os.environ, env), _feature_flags_stub(enabled=True):
            mod = _load("ln_rule_ph_open", "ln_rule_loop.py")
            audits: list = []
            ok = await mod.promote_rule(
                _pool_with(audits),
                rule_key="soft_gate.sleep_aid.followup_suppress",
                version=1,
            )
        self.assertTrue(ok)

    async def test_default_disabled_does_not_gate_promotion(self):
        """Regression: LN_RULE_REQUIRE_PHASE_H unset must not change behavior
        for installs that predate the predicate poller."""
        env = {
            "ENABLE_LN_RULE_LOOP": "true",
            "LN_RULE_DUAL_COO_NOTIFY": "false",
            "LN_RULE_PROMOTE_MIN_PROVENANCE": "0",
        }
        with patch.dict(os.environ, env):
            os.environ.pop("LN_RULE_REQUIRE_PHASE_H", None)
            mod = _load("ln_rule_ph_default_off", "ln_rule_loop.py")
            audits: list = []
            ok = await mod.promote_rule(
                _pool_with(audits),
                rule_key="soft_gate.sleep_aid.followup_suppress",
                version=1,
            )
        self.assertTrue(ok)


class TestProvenanceGate(unittest.IsolatedAsyncioTestCase):
    async def test_promote_refused_below_min_provenance(self):
        env = {
            "ENABLE_LN_RULE_LOOP": "true",
            "LN_RULE_DUAL_COO_NOTIFY": "false",
            "LN_RULE_REQUIRE_PHASE_H": "false",
            "LN_RULE_PROMOTE_MIN_PROVENANCE": "5",
        }
        with patch.dict(os.environ, env):
            mod = _load("ln_rule_prov_low", "ln_rule_loop.py")

            async def _count(_pool, _rule_key):
                return 2

            mod._distinct_provenance_count = _count  # type: ignore
            audits: list = []
            ok = await mod.promote_rule(
                _pool_with(audits),
                rule_key="soft_gate.sleep_aid.followup_suppress",
                version=1,
            )
        self.assertFalse(ok)
        self.assertTrue(any("provenance=2" in str(a) for a in audits))

    async def test_promote_succeeds_at_min_provenance(self):
        env = {
            "ENABLE_LN_RULE_LOOP": "true",
            "LN_RULE_DUAL_COO_NOTIFY": "false",
            "LN_RULE_REQUIRE_PHASE_H": "false",
            "LN_RULE_PROMOTE_MIN_PROVENANCE": "5",
        }
        with patch.dict(os.environ, env):
            mod = _load("ln_rule_prov_ok", "ln_rule_loop.py")

            async def _count(_pool, _rule_key):
                return 5

            mod._distinct_provenance_count = _count  # type: ignore
            audits: list = []
            ok = await mod.promote_rule(
                _pool_with(audits),
                rule_key="soft_gate.sleep_aid.followup_suppress",
                version=1,
            )
        self.assertTrue(ok)

    async def test_distinct_provenance_count_queries_audit_table(self):
        with patch.dict(os.environ, {"ENABLE_LN_RULE_LOOP": "true"}):
            mod = _load("ln_rule_prov_query", "ln_rule_loop.py")
            conn = AsyncMock()
            conn.fetchval = AsyncMock(return_value=3)
            pool = MagicMock()
            pool.acquire = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=conn),
                    __aexit__=AsyncMock(return_value=None),
                )
            )
            n = await mod._distinct_provenance_count(
                pool, "soft_gate.sleep_aid.followup_suppress",
            )
        self.assertEqual(n, 3)
        conn.fetchval.assert_awaited_once()
        sql = conn.fetchval.call_args.args[0]
        self.assertIn("DISTINCT provenance_hash", sql)
        self.assertIn("shadow_fire", sql)
        self.assertIn("fire", sql)


class TestAuditProvenanceThreading(unittest.IsolatedAsyncioTestCase):
    async def test_audit_persists_provenance_hash(self):
        with patch.dict(os.environ, {"ENABLE_LN_RULE_LOOP": "true"}):
            mod = _load("ln_rule_audit_prov", "ln_rule_loop.py")
            conn = AsyncMock()
            pool = MagicMock()
            pool.acquire = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=conn),
                    __aexit__=AsyncMock(return_value=None),
                )
            )
            await mod._audit(
                pool,
                rule_key="soft_gate.sleep_aid.followup_suppress",
                version=1,
                action="shadow_fire",
                detail="test",
                provenance_hash="HW123|COACH_A",
            )
        conn.execute.assert_awaited_once()
        args = conn.execute.call_args.args
        self.assertIn("provenance_hash", args[0])
        self.assertEqual(args[-1], "HW123|COACH_A")

    async def test_apply_soft_gate_rules_threads_provenance_hash(self):
        env = {"ENABLE_LN_RULE_LOOP": "true", "LN_RULE_LOOP_APPLY": "false"}
        with patch.dict(os.environ, env):
            mod = _load("ln_rule_apply_prov", "ln_rule_loop.py")

            async def _ensure(_pool, _gc):
                return None

            async def _conf(_pool, _gc):
                return 0.0, 0

            async def _list_rules(_pool):
                return [
                    {
                        "rule_key": "soft_gate.sleep_aid.followup_suppress",
                        "version": 1,
                        "status": "sandbox",
                        "condition": {"fired_new": False},
                        "action": {"type": "suppress_soft_followup"},
                    }
                ]

            audit_calls: list = []

            async def _audit_spy(_pool, **kwargs):
                audit_calls.append(kwargs)

            async def _noop(*a, **kw):
                return None

            mod.ensure_soft_rule_drafted = _ensure  # type: ignore
            mod._gate_confidence = _conf  # type: ignore
            mod.list_eval_rules = _list_rules  # type: ignore
            mod._audit = _audit_spy  # type: ignore
            mod.record_shadow_score = _noop  # type: ignore
            mod._notify_l5_observe = _noop  # type: ignore
            mod.maybe_lifecycle_from_gate_confidence = _noop  # type: ignore

            result = await mod.apply_soft_gate_rules(
                MagicMock(),
                {"class": "sleep_aid", "fired_new": "false", "active_topics": []},
                user_id="uid-not-persisted",
                provenance_hash="HWabc|COACH_B",
            )
        self.assertIsNotNone(result)
        self.assertTrue(
            any(c.get("provenance_hash") == "HWabc|COACH_B" for c in audit_calls)
        )


if __name__ == "__main__":
    unittest.main()
