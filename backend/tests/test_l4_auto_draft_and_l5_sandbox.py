"""L4 outcome auto-draft + L5 observe sandbox isolation (offline)."""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_SERVICES = Path(__file__).resolve().parents[1] / "app" / "services"


def _load(name: str, rel: str):
    path = _SERVICES / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestL4AutoDraftGates(unittest.TestCase):
    def test_auto_draft_respects_master_flag(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "false"
        os.environ["ENABLE_LN_RULE_AUTO_DRAFT"] = "true"
        mod = _load("ln_rule_loop", "ln_rule_loop.py")
        self.assertFalse(mod.auto_draft_enabled())

    def test_soft_only(self):
        mod = _load("ln_rule_loop", "ln_rule_loop.py")
        self.assertTrue(mod.is_soft_gate_class("diagnosis_request"))
        self.assertFalse(mod.is_soft_gate_class("suicide_ideation"))


class TestL4DraftFromFP(unittest.IsolatedAsyncioTestCase):
    async def test_fp_draft_refuses_hard_class(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        os.environ["ENABLE_LN_RULE_AUTO_DRAFT"] = "true"
        mod = _load("ln_rule_loop", "ln_rule_loop.py")
        out = await mod.maybe_draft_from_false_positive(
            AsyncMock(), "suicide_ideation",
        )
        self.assertIsNone(out)

    async def test_fp_draft_skips_high_confidence(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        os.environ["ENABLE_LN_RULE_AUTO_DRAFT"] = "true"
        os.environ["LN_RULE_FP_DRAFT_MIN_N"] = "3"
        os.environ["LN_RULE_FP_DRAFT_MAX_CONF"] = "0.45"
        mod = _load("ln_rule_loop", "ln_rule_loop.py")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "confidence": 0.80,
                "sample_size": 10,
                "negative_count": 5,
                "positive_count": 5,
            }
        )
        pool = MagicMock()
        pool.acquire = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=None),
            )
        )
        out = await mod.maybe_draft_from_false_positive(pool, "diagnosis_request")
        self.assertIsNone(out)

    async def test_fp_draft_and_sandbox_on_low_conf(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        os.environ["ENABLE_LN_RULE_AUTO_DRAFT"] = "true"
        os.environ["LN_RULE_FP_DRAFT_MIN_N"] = "3"
        os.environ["LN_RULE_FP_DRAFT_MAX_CONF"] = "0.45"
        mod = _load("ln_rule_loop", "ln_rule_loop.py")

        drafted = {"rid": 99, "sandbox": False}

        async def _has(_pool, _key):
            return False

        async def _draft(_pool, **kwargs):
            self.assertEqual(kwargs["created_by"], "ln_gate_fp")
            self.assertEqual(kwargs["condition"]["gate_class"], "sleep_aid")
            self.assertIn(kwargs["action"]["type"], ("suppress_soft_followup", "noop"))
            return drafted["rid"]

        async def _ver(_pool, _key):
            return 2

        async def _sandbox(_pool, **kwargs):
            drafted["sandbox"] = True
            self.assertEqual(kwargs["version"], 2)
            return True

        async def _l5(*_a, **_k):
            return None

        mod._has_live_or_pending_rule = _has  # type: ignore
        mod.draft_rule = _draft  # type: ignore
        mod._latest_version = _ver  # type: ignore
        mod.move_to_sandbox = _sandbox  # type: ignore
        mod._notify_l5_observe = _l5  # type: ignore

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "confidence": 0.30,
                "sample_size": 8,
                "negative_count": 4,
                "positive_count": 4,
            }
        )
        pool = MagicMock()
        pool.acquire = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=None),
            )
        )
        rid = await mod.maybe_draft_from_false_positive(pool, "sleep_aid")
        self.assertEqual(rid, 99)
        self.assertTrue(drafted["sandbox"])

    async def test_cycle_evidence_complete(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        mod = _load("ln_rule_loop", "ln_rule_loop.py")
        actions = ["draft", "sandbox_pass", "shadow_fire", "promote"]
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[{"action": a, "version": 1, "detail": "", "recorded_at": None}
                         for a in actions]
        )
        pool = MagicMock()
        pool.acquire = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=None),
            )
        )
        ev = await mod.cycle_evidence(pool, "soft_gate.diagnosis_request.followup_suppress")
        self.assertTrue(ev["l4_cycle_complete"])
        self.assertTrue(ev["has_draft"])
        self.assertTrue(ev["has_promote"])


class TestL5SandboxGates(unittest.TestCase):
    def test_never_writes_live(self):
        from app.services.l5_sandbox import gates

        self.assertFalse(gates.can_write_live_rules())

    def test_refuse_hard_class(self):
        from app.services.l5_sandbox import gates

        self.assertTrue(gates.refuse_hard_class("suicide_ideation"))
        self.assertTrue(gates.refuse_hard_class(""))
        self.assertFalse(gates.refuse_hard_class("pharma_interaction"))

    def test_adapt_requires_observe(self):
        from app.services.l5_sandbox import gates

        prev_o = os.environ.get("ENABLE_L5_OBSERVE")
        prev_a = os.environ.get("ENABLE_L5_ADAPT")
        try:
            os.environ["ENABLE_L5_OBSERVE"] = "false"
            os.environ["ENABLE_L5_ADAPT"] = "true"
            self.assertFalse(gates.adapt_enabled())
        finally:
            if prev_o is None:
                os.environ.pop("ENABLE_L5_OBSERVE", None)
            else:
                os.environ["ENABLE_L5_OBSERVE"] = prev_o
            if prev_a is None:
                os.environ.pop("ENABLE_L5_ADAPT", None)
            else:
                os.environ["ENABLE_L5_ADAPT"] = prev_a


class TestL5AdaptorIsolation(unittest.IsolatedAsyncioTestCase):
    async def test_propose_live_promotion_refused(self):
        from app.services.l5_sandbox import adaptor

        out = await adaptor.propose_live_promotion(AsyncMock(), hypothesis_key="x")
        self.assertFalse(out["allowed"])
        self.assertFalse(out["can_write_live_rules"])

    async def test_adapt_skips_hard_class(self):
        from app.services.l5_sandbox import adaptor

        prev_o = os.environ.get("ENABLE_L5_OBSERVE")
        prev_a = os.environ.get("ENABLE_L5_ADAPT")
        try:
            os.environ["ENABLE_L5_OBSERVE"] = "true"
            os.environ["ENABLE_L5_ADAPT"] = "true"
            out = await adaptor.maybe_adapt_from_event(
                AsyncMock(),
                event="shadow_fire",
                gate_class="suicide_ideation",
                rule_key="bad",
            )
            self.assertIsNone(out)
        finally:
            if prev_o is None:
                os.environ.pop("ENABLE_L5_OBSERVE", None)
            else:
                os.environ["ENABLE_L5_OBSERVE"] = prev_o
            if prev_a is None:
                os.environ.pop("ENABLE_L5_ADAPT", None)
            else:
                os.environ["ENABLE_L5_ADAPT"] = prev_a


if __name__ == "__main__":
    unittest.main()
