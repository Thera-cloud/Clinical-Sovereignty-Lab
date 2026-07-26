"""L4 close-loop: Dual-COO notify + CEO APPROVE/REJECT (offline seams)."""

from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[1] / "app" / "services"


def _load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _install_dual_coo_stub(calls: list):
    stub = types.ModuleType("app.websocket.cli_dual_coo")
    stub.RISK_YELLOW = "YELLOW"  # type: ignore[attr-defined]
    stub.RISK_RED = "RED"  # type: ignore[attr-defined]

    def _enq(**kwargs):
        calls.append(kwargs)
        return {"status": "ok"}

    stub.enqueue_ceo = _enq  # type: ignore[attr-defined]
    # Ensure parent packages exist for `from app.websocket.cli_dual_coo import ...`
    if "app" not in sys.modules:
        sys.modules["app"] = types.ModuleType("app")
    if "app.websocket" not in sys.modules:
        sys.modules["app.websocket"] = types.ModuleType("app.websocket")
    sys.modules["app.websocket.cli_dual_coo"] = stub
    return stub


class TestL4DualCooNotify(unittest.TestCase):
    def test_notify_enqueues_lifecycle_payload(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        os.environ["LN_RULE_DUAL_COO_NOTIFY"] = "true"
        mod = _load("ln_rule_loop_notify", "ln_rule_loop.py")
        calls: list = []
        _install_dual_coo_stub(calls)
        mod._notify_dual_coo(
            event="draft_sandbox",
            rule_key="soft_gate.sleep_aid.followup_suppress",
            version=2,
            gate_class="sleep_aid",
            action_hint="promote",
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["payload"]["kind"], "ln_rule_lifecycle")
        self.assertEqual(calls[0]["payload"]["action"], "promote")
        self.assertEqual(calls[0]["payload"]["version"], 2)

    def test_notify_off_when_flag_false(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        os.environ["LN_RULE_DUAL_COO_NOTIFY"] = "false"
        mod = _load("ln_rule_loop_notify_off", "ln_rule_loop.py")
        calls: list = []
        _install_dual_coo_stub(calls)
        mod._notify_dual_coo(
            event="promote",
            rule_key="soft_gate.sleep_aid.followup_suppress",
            version=1,
        )
        self.assertEqual(calls, [])


class TestL4CeoApply(unittest.IsolatedAsyncioTestCase):
    async def test_approve_promotes(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        mod = _load("ln_rule_loop_ceo_approve", "ln_rule_loop.py")
        promoted = {"ok": False}

        async def _promote(_pool, **kwargs):
            promoted["ok"] = True
            self.assertEqual(
                kwargs["rule_key"], "soft_gate.pharma_interaction.followup_suppress"
            )
            self.assertEqual(kwargs["version"], 3)
            return True

        mod.promote_rule = _promote  # type: ignore
        out = await mod.ceo_apply_ln_rule(
            MagicMock(),
            {
                "kind": "ln_rule_lifecycle",
                "rule_key": "soft_gate.pharma_interaction.followup_suppress",
                "version": 3,
                "action": "promote",
            },
            approved_by="DrNevedal1",
            decision="APPROVE",
        )
        self.assertTrue(promoted["ok"])
        self.assertEqual(out["action"], "promote")
        self.assertTrue(out["ok"])

    async def test_reject_discards_sandbox(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        mod = _load("ln_rule_loop_ceo_reject", "ln_rule_loop.py")
        rejected = {"ok": False}

        async def _rej(_pool, **kwargs):
            rejected["ok"] = True
            return True

        mod.reject_sandbox_rule = _rej  # type: ignore
        out = await mod.ceo_apply_ln_rule(
            MagicMock(),
            {
                "kind": "ln_rule_lifecycle",
                "rule_key": "soft_gate.diagnosis_request.followup_suppress",
                "version": 2,
                "action": "promote",
            },
            decision="REJECT",
        )
        self.assertTrue(rejected["ok"])
        self.assertEqual(out["action"], "reject")

    async def test_refuse_hard_class_draft(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        mod = _load("ln_rule_loop_hard_refuse", "ln_rule_loop.py")
        rid = await mod.draft_rule(
            MagicMock(),
            rule_key="soft_gate.suicide.followup_suppress",
            condition={"gate_class": "suicide_ideation"},
            action={"type": "suppress_soft_followup"},
        )
        self.assertIsNone(rid)


class TestL4PromoteRequiresCeo(unittest.IsolatedAsyncioTestCase):
    async def test_lifecycle_enqueues_instead_of_promote(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        os.environ["LN_RULE_PROMOTE_REQUIRES_CEO"] = "true"
        os.environ["LN_RULE_DUAL_COO_NOTIFY"] = "true"
        os.environ["LN_RULE_SHADOW_PROMOTE_MIN"] = "3"
        mod = _load("ln_rule_loop_ceo_gate", "ln_rule_loop.py")
        promoted = {"ok": False}
        notified: list = []

        async def _conf(_pool, _gc):
            return 0.40, 2

        async def _shadows(_pool, _key, _ver):
            return 5

        async def _promote(_pool, **kwargs):
            promoted["ok"] = True
            return True

        def _notify(**kwargs):
            notified.append(kwargs)

        mod._gate_confidence = _conf  # type: ignore
        mod._shadow_fire_count = _shadows  # type: ignore
        mod.promote_rule = _promote  # type: ignore
        mod._notify_dual_coo = _notify  # type: ignore

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                None,
                {"rule_key": "soft_gate.sleep_aid.followup_suppress", "version": 1},
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
        self.assertFalse(promoted["ok"])
        self.assertTrue(any(n.get("event") == "promote_ready" for n in notified))
        os.environ["LN_RULE_PROMOTE_REQUIRES_CEO"] = "false"


if __name__ == "__main__":
    unittest.main()
