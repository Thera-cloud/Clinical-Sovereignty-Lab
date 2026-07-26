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


def _load_l5_adaptor():
    """Load adaptor without importing app.services (avoids nevedal/numpy on macOS)."""
    import types

    pkg = "app.services.l5_sandbox"
    for name in ("app", "app.services", pkg):
        if name not in sys.modules:
            m = types.ModuleType(name)
            if name == pkg:
                m.__path__ = [str(_SERVICES / "l5_sandbox")]
            sys.modules[name] = m
    gates_name = f"{pkg}.gates"
    if gates_name not in sys.modules:
        gpath = _SERVICES / "l5_sandbox" / "gates.py"
        gspec = importlib.util.spec_from_file_location(gates_name, gpath)
        gmod = importlib.util.module_from_spec(gspec)
        assert gspec.loader is not None
        sys.modules[gates_name] = gmod
        gspec.loader.exec_module(gmod)
    aname = f"{pkg}.adaptor"
    apath = _SERVICES / "l5_sandbox" / "adaptor.py"
    aspec = importlib.util.spec_from_file_location(aname, apath)
    amod = importlib.util.module_from_spec(aspec)
    assert aspec.loader is not None
    amod.__package__ = pkg
    sys.modules[aname] = amod
    aspec.loader.exec_module(amod)
    return amod


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

        async def _pending(_pool, _key):
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

        mod._has_pending_draft_or_sandbox = _pending  # type: ignore
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

    async def test_fp_supersede_skips_when_sandbox_pending(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        os.environ["ENABLE_LN_RULE_AUTO_DRAFT"] = "true"
        os.environ["LN_RULE_FP_DRAFT_MIN_N"] = "3"
        os.environ["LN_RULE_FP_DRAFT_MAX_CONF"] = "0.45"
        mod = _load("ln_rule_loop", "ln_rule_loop.py")

        async def _pending(_pool, _key):
            return True

        mod._has_pending_draft_or_sandbox = _pending  # type: ignore
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "confidence": 0.20,
                "sample_size": 10,
                "negative_count": 6,
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
        self.assertIsNone(await mod.maybe_draft_from_false_positive(pool, "pharma_interaction"))

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

    async def test_lifecycle_promotes_newer_sandbox_over_active(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        os.environ["LN_RULE_SHADOW_PROMOTE_MIN"] = "3"
        mod = _load("ln_rule_loop", "ln_rule_loop.py")
        promoted = {"ok": False}

        async def _conf(_pool, _gc):
            return 0.40, 2

        async def _shadows(_pool, _key, _ver):
            return 5

        async def _promote(_pool, **kwargs):
            self.assertEqual(kwargs["version"], 2)
            promoted["ok"] = True
            return True

        async def _l5(*_a, **_k):
            return None

        mod._gate_confidence = _conf  # type: ignore
        mod._shadow_fire_count = _shadows  # type: ignore
        mod.promote_rule = _promote  # type: ignore
        mod._notify_l5_observe = _l5  # type: ignore

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"rule_key": "soft_gate.sleep_aid.followup_suppress", "version": 1},
                {"rule_key": "soft_gate.sleep_aid.followup_suppress", "version": 2},
            ]
        )
        pool = MagicMock()
        pool.acquire = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=None),
            )
        )
        await mod.maybe_lifecycle_from_gate_confidence(pool, "sleep_aid")
        self.assertTrue(promoted["ok"])


class TestL5SandboxGates(unittest.TestCase):
    def test_never_writes_live(self):
        gates = _load("l5_gates", "l5_sandbox/gates.py")
        self.assertFalse(gates.can_write_live_rules())

    def test_refuse_hard_class(self):
        gates = _load("l5_gates", "l5_sandbox/gates.py")
        self.assertTrue(gates.refuse_hard_class("suicide_ideation"))
        self.assertTrue(gates.refuse_hard_class(""))
        self.assertFalse(gates.refuse_hard_class("pharma_interaction"))

    def test_adapt_requires_observe(self):
        gates = _load("l5_gates", "l5_sandbox/gates.py")
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
        adaptor = _load_l5_adaptor()
        out = await adaptor.propose_live_promotion(AsyncMock(), hypothesis_key="x")
        self.assertFalse(out["allowed"])
        self.assertFalse(out["can_write_live_rules"])

    async def test_adapt_skips_hard_class(self):
        adaptor = _load_l5_adaptor()
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
