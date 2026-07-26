"""L3a outcome recall rank + L3b/L3c gate helpers (offline)."""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_SERVICES = Path(__file__).resolve().parents[1] / "app" / "services"


def _load(name: str, filename: str):
    path = _SERVICES / filename
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestL3aOutcomeRerank(unittest.IsolatedAsyncioTestCase):
    async def test_rerank_prefers_higher_avg_c_emo(self):
        os.environ["ENABLE_CRYSTAL_OUTCOME_RECALL_RANK"] = "true"
        os.environ["CRYSTAL_OUTCOME_RECALL_BLEND"] = "0.5"
        os.environ["CRYSTAL_OUTCOME_RECALL_MIN_SAMPLE"] = "1"

        import importlib
        import app.websocket.crystal_recall_bridge as crb

        importlib.reload(crb)

        crystals = [
            {"id": 1, "confidence": 0.5, "crystal_text": "low outcome"},
            {"id": 2, "confidence": 0.5, "crystal_text": "high outcome"},
        ]

        class _Conn:
            async def fetch(self, query, *args):
                return [
                    {"crystal_id": 1, "avg_c_emo": 0.2, "n": 5},
                    {"crystal_id": 2, "avg_c_emo": 0.9, "n": 5},
                ]

        ranked = await crb._rerank_by_outcome(_Conn(), crystals, 2)
        self.assertEqual(ranked[0]["id"], 2)
        self.assertEqual(ranked[1]["id"], 1)

    async def test_rerank_noop_without_outcomes(self):
        os.environ["ENABLE_CRYSTAL_OUTCOME_RECALL_RANK"] = "true"
        import importlib
        import app.websocket.crystal_recall_bridge as crb

        importlib.reload(crb)

        crystals = [
            {"id": 1, "confidence": 0.9},
            {"id": 2, "confidence": 0.4},
        ]

        class _Conn:
            async def fetch(self, query, *args):
                return []

        ranked = await crb._rerank_by_outcome(_Conn(), crystals, 2)
        self.assertEqual([c["id"] for c in ranked], [1, 2])


class TestL3bGateConfidence(unittest.TestCase):
    def test_fp_patterns(self):
        mod = _load("clinical_gate_confidence", "clinical_gate_confidence.py")
        self.assertTrue(mod.looks_like_false_positive("I was just curious about meds"))
        self.assertTrue(mod.looks_like_false_positive("not asking for a diagnosis"))
        self.assertFalse(
            mod.looks_like_false_positive("can these two antidepressants interact?")
        )


class TestL3cCalibrationFilter(unittest.TestCase):
    def test_soft_filtered_when_calibration_bad(self):
        mod = _load("foresight_calibration_gate", "foresight_calibration_gate.py")
        cons = [
            {"type": "slow_pacing", "instruction": "slow"},
            {"type": "witness_not_advise", "instruction": "witness"},
            {"type": "avoid_topic", "instruction": "avoid"},
        ]
        out = mod.filter_constraints_for_calibration(cons, calibration_ok=False)
        self.assertEqual([c["type"] for c in out], ["witness_not_advise"])

    def test_all_kept_when_calibration_ok(self):
        mod = _load("foresight_calibration_gate", "foresight_calibration_gate.py")
        cons = [{"type": "slow_pacing"}, {"type": "avoid_topic"}]
        out = mod.filter_constraints_for_calibration(cons, calibration_ok=True)
        self.assertEqual(len(out), 2)


class TestL4RuleLoopFlagOff(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_returns_empty(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "false"
        mod = _load("ln_rule_loop", "ln_rule_loop.py")
        self.assertEqual(await mod.list_active_rules(AsyncMock()), [])
        self.assertIsNone(
            await mod.draft_rule(
                AsyncMock(),
                rule_key="t",
                condition={},
                action={},
            )
        )


if __name__ == "__main__":
    unittest.main()
