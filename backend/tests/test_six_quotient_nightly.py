"""Offline seams for D.12 nightly measure (importlib — avoid numpy crash)."""

from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"


def _load(name: str, path: Path):
    if "app" not in sys.modules:
        sys.modules["app"] = types.ModuleType("app")
    if "app.services" not in sys.modules:
        pkg = types.ModuleType("app.services")
        pkg.__path__ = [str(APP / "services")]  # type: ignore[attr-defined]
        sys.modules["app.services"] = pkg
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_bank = _load(
    "app.services.six_quotient_scenario_bank",
    APP / "services" / "six_quotient_scenario_bank.py",
)
_agent = _load(
    "app.services.six_quotient_battery_agent",
    APP / "services" / "six_quotient_battery_agent.py",
)
_judge = _load(
    "app.services.six_quotient_auto_judge",
    APP / "services" / "six_quotient_auto_judge.py",
)
_aud = _load(
    "app.services.six_quotient_battery_auditor",
    APP / "services" / "six_quotient_battery_auditor.py",
)


class TestHoldoutDeterminism(unittest.TestCase):
    def test_same_input_same_keys(self):
        keys = [f"AQ-{i}" for i in range(9)] + [f"SQ-{i}" for i in range(6)]
        a = _bank.holdout_keys_deterministic(keys, fraction=0.3)
        b = _bank.holdout_keys_deterministic(keys, fraction=0.3)
        self.assertEqual(a, b)
        self.assertTrue(len(a) >= 1)

    def test_never_unmarks_semantics(self):
        # Function only selects from provided free keys — already-held-out omitted by caller
        free = ["AQ-1", "AQ-2", "AQ-3", "AQ-4", "AQ-5", "AQ-6"]
        picked = _bank.holdout_keys_deterministic(free, fraction=0.3)
        self.assertTrue(set(picked).issubset(set(free)))


class TestNightlyGate(unittest.IsolatedAsyncioTestCase):
    async def test_flag_off_noops(self):
        agent = _agent.SixQuotientBatteryAgent(db_pool=None, app_state=None)
        with patch.dict(os.environ, {"SIX_QUOTIENT_NIGHTLY_MEASURE": "false"}, clear=False):
            out = await agent._maybe_nightly(force=True)
        self.assertFalse(out.get("ok"))
        self.assertIn("off", str(out.get("error") or ""))

    async def test_outside_hour_noops(self):
        agent = _agent.SixQuotientBatteryAgent(db_pool=MagicMock(), app_state=None)
        fake_now = datetime(2026, 7, 21, 14, 0, 0, tzinfo=timezone.utc)  # not 02-03
        with patch.dict(os.environ, {"SIX_QUOTIENT_NIGHTLY_MEASURE": "true"}, clear=False):
            with patch.object(_agent, "datetime") as mock_dt:
                mock_dt.now.return_value = fake_now
                mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
                out = await agent._maybe_nightly(force=False)
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "outside_02_03_utc")


class TestRotationSQL(unittest.TestCase):
    def test_nightly_sql_excludes_held_out_and_orders(self):
        sql = _bank.NIGHTLY_ROTATION_SQL
        self.assertIn("held_out", sql)
        self.assertIn("FALSE", sql)
        self.assertIn("last_measured_at ASC NULLS FIRST", sql)

    def test_transfer_sql_requires_held_out(self):
        sql = _bank.TRANSFER_ROTATION_SQL
        self.assertIn("TRUE", sql)
        self.assertIn("last_measured_at ASC NULLS FIRST", sql)


class TestAutoJudgeFailure(unittest.IsolatedAsyncioTestCase):
    async def test_llm_failure_no_score_submit(self):
        pool = MagicMock()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": "r1",
                "status": "awaiting_scores",
                "results_json": {
                    "results": [
                        {
                            "scenario_id": "AQ-1",
                            "section": "AQ",
                            "rubric_focus": "crisis",
                            "client_says": "I have a plan",
                            "response": "Tell me about means",
                        }
                    ]
                },
                "environment": "production",
            }
        )
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=None)
        pool.acquire = MagicMock(return_value=cm)

        with patch.object(
            _judge,
            "ensure_evaluator_calibrated",
            AsyncMock(return_value={"ok": True, "already_calibrated": True}),
        ):
            with patch.object(_judge, "_llm_judge", AsyncMock(return_value=None)):
                with patch(
                    "app.services.six_quotient_score_intake.upsert_scores",
                    new_callable=AsyncMock,
                ) as upsert:
                    out = await _judge.auto_score_run(pool, None, "r1")
                    upsert.assert_not_called()
        self.assertFalse(out.get("ok"))
        self.assertIn("judge failed", str(out.get("error") or ""))


class TestAuditorSeventeen(unittest.TestCase):
    def test_count(self):
        total = sum(len(t["endpoints"]) for t in _aud.TAB_ENDPOINTS)
        self.assertEqual(total, 18)


if __name__ == "__main__":
    unittest.main()
