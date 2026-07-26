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


class TestL4SoftRuleBind(unittest.TestCase):
    def test_soft_condition_match(self):
        mod = _load("ln_rule_loop", "ln_rule_loop.py")
        cond = {
            "gate_class": "diagnosis_request",
            "fired_new": False,
            "max_confidence": 0.30,
        }
        self.assertTrue(
            mod.condition_matches(
                cond, gate_class="diagnosis_request", fired_new=False, confidence=0.20,
            )
        )
        self.assertFalse(
            mod.condition_matches(
                cond, gate_class="diagnosis_request", fired_new=False, confidence=0.80,
            )
        )
        self.assertFalse(
            mod.condition_matches(
                cond, gate_class="diagnosis_request", fired_new=True, confidence=0.20,
            )
        )

    def test_hard_class_never_matches(self):
        mod = _load("ln_rule_loop", "ln_rule_loop.py")
        self.assertFalse(mod.is_soft_gate_class("suicide_ideation"))
        self.assertFalse(
            mod.condition_matches(
                {"gate_class": "suicide_ideation"},
                gate_class="suicide_ideation",
                fired_new=True,
                confidence=0.9,
            )
        )

class TestL4DraftRefuse(unittest.IsolatedAsyncioTestCase):
    async def test_draft_refuses_hard_class(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        mod = _load("ln_rule_loop", "ln_rule_loop.py")
        rid = await mod.draft_rule(
            AsyncMock(),
            rule_key="bad.si",
            condition={"gate_class": "suicide_ideation"},
            action={"type": "suppress_soft_followup"},
        )
        self.assertIsNone(rid)


class TestL4ApplySoftGate(unittest.IsolatedAsyncioTestCase):
    async def test_active_suppress_followup(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        os.environ["LN_RULE_LOOP_APPLY"] = "true"
        mod = _load("ln_rule_loop", "ln_rule_loop.py")

        rules = [
            {
                "rule_key": "soft_gate.diagnosis_request.followup_suppress",
                "version": 1,
                "status": "active",
                "condition": {
                    "gate_class": "diagnosis_request",
                    "fired_new": False,
                    "max_confidence": 0.30,
                },
                "action": {"type": "suppress_soft_followup"},
            }
        ]

        async def _list(_pool):
            return rules

        async def _conf(_pool, _cls):
            return 0.20, 10

        async def _audit(*_a, **_k):
            return None

        async def _life(*_a, **_k):
            return None

        async def _ensure(*_a, **_k):
            return None

        mod.list_eval_rules = _list  # type: ignore
        mod._gate_confidence = _conf  # type: ignore
        mod._audit = _audit  # type: ignore
        mod.maybe_lifecycle_from_gate_confidence = _life  # type: ignore
        mod.ensure_soft_rule_drafted = _ensure  # type: ignore

        out = await mod.apply_soft_gate_rules(
            object(),
            {
                "class": "diagnosis_request",
                "fired_new": "false",
                "response": {"type": "clinical_gate"},
            },
        )
        self.assertIsNone(out)

    async def test_sandbox_does_not_suppress(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        os.environ["LN_RULE_LOOP_APPLY"] = "true"
        mod = _load("ln_rule_loop", "ln_rule_loop.py")

        rules = [
            {
                "rule_key": "soft_gate.diagnosis_request.followup_suppress",
                "version": 1,
                "status": "sandbox",
                "condition": {
                    "gate_class": "diagnosis_request",
                    "fired_new": False,
                },
                "action": {"type": "suppress_soft_followup"},
            }
        ]

        async def _list(_pool):
            return rules

        async def _conf(_pool, _cls):
            return 0.20, 10

        async def _audit(*_a, **_k):
            return None

        async def _life(*_a, **_k):
            return None

        async def _ensure(*_a, **_k):
            return None

        mod.list_eval_rules = _list  # type: ignore
        mod._gate_confidence = _conf  # type: ignore
        mod._audit = _audit  # type: ignore
        mod.maybe_lifecycle_from_gate_confidence = _life  # type: ignore
        mod.ensure_soft_rule_drafted = _ensure  # type: ignore

        gate = {
            "class": "diagnosis_request",
            "fired_new": "false",
            "response": {"type": "clinical_gate"},
        }
        out = await mod.apply_soft_gate_rules(object(), gate)
        self.assertIs(out, gate)

    async def test_active_suppress_with_zero_samples(self):
        """Empty confidence table must not block first soft follow-up suppress."""
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        os.environ["LN_RULE_LOOP_APPLY"] = "true"
        mod = _load("ln_rule_loop", "ln_rule_loop.py")

        rules = [
            {
                "rule_key": "soft_gate.pharma_interaction.followup_suppress",
                "version": 1,
                "status": "active",
                "condition": {
                    "gate_class": "pharma_interaction",
                    "fired_new": False,
                    "max_confidence": 0.30,
                },
                "action": {"type": "suppress_soft_followup"},
            }
        ]

        async def _list(_pool):
            return rules

        async def _conf(_pool, _cls):
            return 0.70, 0  # default conf, no samples

        async def _audit(*_a, **_k):
            return None

        async def _life(*_a, **_k):
            return None

        async def _ensure(*_a, **_k):
            return None

        mod.list_eval_rules = _list  # type: ignore
        mod._gate_confidence = _conf  # type: ignore
        mod._audit = _audit  # type: ignore
        mod.maybe_lifecycle_from_gate_confidence = _life  # type: ignore
        mod.ensure_soft_rule_drafted = _ensure  # type: ignore

        out = await mod.apply_soft_gate_rules(
            object(),
            {
                "class": "pharma_interaction",
                "fired_new": "false",
                "response": {"type": "clinical_gate"},
            },
        )
        self.assertIsNone(out)

    async def test_si_class_passthrough(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        os.environ["LN_RULE_LOOP_APPLY"] = "true"
        mod = _load("ln_rule_loop", "ln_rule_loop.py")
        gate = {"class": "suicide_ideation", "fired_new": "true", "response": {}}
        out = await mod.apply_soft_gate_rules(object(), gate)
        self.assertIs(out, gate)


if __name__ == "__main__":
    unittest.main()

