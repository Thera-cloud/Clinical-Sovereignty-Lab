"""L4 credibility bars — full PASS requires mechanism + forecaster + fence.

Claim licensed only when l4_credible:
"A narrow, clinically-scoped neuro-symbolic system that autonomously improves
its own therapeutic rules within demonstrated hard boundaries, with logged
evidence of self-correction."
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

_SERVICES = Path(__file__).resolve().parents[1] / "app" / "services"


def _load(name: str, rel: str):
    path = _SERVICES / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _gate_class_of(rule: Dict[str, Any]) -> str:
    cond = rule.get("condition_json")
    if isinstance(cond, str):
        try:
            cond = json.loads(cond)
        except Exception:
            cond = {}
    if isinstance(cond, dict):
        return str(cond.get("gate_class") or "")
    return ""


class MemStore:
    def __init__(self) -> None:
        self.rules: List[Dict[str, Any]] = []
        self.audits: List[Dict[str, Any]] = []
        self.shadows: List[Dict[str, Any]] = []
        self.conf: Dict[str, Dict[str, Any]] = {}
        self._seq = 0
        self._clock = 0

    def next_id(self) -> int:
        self._seq += 1
        return self._seq

    def tick(self) -> int:
        self._clock += 1
        return self._clock


class MemConn:
    def __init__(self, store: MemStore) -> None:
        self.store = store

    async def __aenter__(self) -> "MemConn":
        return self

    async def __aexit__(self, *a: Any) -> None:
        return None

    def transaction(self) -> "MemConn":
        return self

    async def fetchrow(self, sql: str, *args: Any) -> Optional[Dict[str, Any]]:
        s = " ".join(sql.lower().split())
        if "from ln_rule_store" in s and "status in ('draft', 'sandbox')" in s:
            key, ver = args[0], int(args[1])
            for r in self.store.rules:
                if (
                    r["rule_key"] == key
                    and r["version"] == ver
                    and r["status"] in ("draft", "sandbox")
                ):
                    return {
                        "condition_json": r["condition_json"],
                        "action_json": r["action_json"],
                        "status": r["status"],
                    }
            return None
        if "from ln_rule_store" in s and "status = 'active'" in s:
            gclass = args[0]
            cands = [
                r
                for r in self.store.rules
                if r["status"] == "active" and _gate_class_of(r) == gclass
            ]
            cands.sort(
                key=lambda r: (r.get("promoted_at") or 0, r["version"]),
                reverse=True,
            )
            if not cands:
                return None
            r = cands[0]
            return {"rule_key": r["rule_key"], "version": r["version"]}
        if "from ln_rule_store" in s and "status = 'sandbox'" in s:
            gclass = args[0]
            cands = [
                r
                for r in self.store.rules
                if r["status"] == "sandbox" and _gate_class_of(r) == gclass
            ]
            cands.sort(key=lambda r: r["version"], reverse=True)
            if not cands:
                return None
            r = cands[0]
            return {"rule_key": r["rule_key"], "version": r["version"]}
        return None

    async def fetchval(self, sql: str, *args: Any) -> Any:
        s = " ".join(sql.lower().split())
        if "select confidence from clinical_gate_confidence" in s:
            row = self.store.conf.get(args[0])
            return None if not row else row["confidence"]
        if "select coalesce(sample_size, 0)" in s or (
            "sample_size" in s and "clinical_gate_confidence" in s and "select" in s
        ):
            row = self.store.conf.get(args[0])
            return 0 if not row else int(row["sample_size"])
        if "coalesce(max(version), 0) + 1" in s:
            key = args[0]
            vers = [r["version"] for r in self.store.rules if r["rule_key"] == key]
            return (max(vers) if vers else 0) + 1
        if "insert into ln_rule_store" in s:
            rid = self.store.next_id()
            self.store.rules.append(
                {
                    "id": rid,
                    "rule_key": args[0],
                    "version": int(args[1]),
                    "status": "draft",
                    "condition_json": args[2],
                    "action_json": args[3],
                    "created_by": args[4],
                    "notes": args[5],
                    "promoted_at": None,
                }
            )
            return rid
        if "insert into ln_rule_shadow_scores" in s:
            rid = self.store.next_id()
            phase = "post_promote" if "post_promote" in s else "shadow"
            row = {
                "id": rid,
                "rule_key": args[0],
                "version": int(args[1]),
                "phase": phase,
                "predicted_action": args[2],
                "predicted_would_suppress": bool(args[3]),
                "gate_class": args[4],
                "match_confidence": float(args[5]),
                "actual_suppressed": args[6] if len(args) > 6 else None,
                "actual_label": args[7] if len(args) > 7 else "pending",
            }
            if phase == "shadow":
                row["actual_label"] = "pending"
                row["actual_suppressed"] = None
            self.store.shadows.append(row)
            return rid
        if "update ln_rule_store" in s and "status = 'sandbox'" in s:
            key, ver = args[0], int(args[1])
            for r in self.store.rules:
                if r["rule_key"] == key and r["version"] == ver and r["status"] == "draft":
                    r["status"] = "sandbox"
                    return r["id"]
            return None
        if "update ln_rule_store" in s and "status = 'active'" in s and "promoted_at" in s:
            key, ver = args[0], int(args[1])
            for r in self.store.rules:
                if (
                    r["rule_key"] == key
                    and r["version"] == ver
                    and r["status"] in ("draft", "sandbox")
                ):
                    r["status"] = "active"
                    r["promoted_at"] = self.store.tick()
                    return r["id"]
            return None
        if (
            "update ln_rule_store" in s
            and "rolled_back" in s
            and "version = $2" in s
            and "status = 'active'" in s
        ):
            key, ver = args[0], int(args[1])
            for r in self.store.rules:
                if r["rule_key"] == key and r["version"] == ver and r["status"] == "active":
                    r["status"] = "rolled_back"
                    return r["id"]
            return None
        if "select max(version)" in s:
            key = args[0]
            vers = [r["version"] for r in self.store.rules if r["rule_key"] == key]
            return max(vers) if vers else None
        if "from ln_rule_shadow_scores" in s and "count(*)" in s:
            key = args[0]
            if len(args) > 1:
                ver = int(args[1])
                return sum(
                    1
                    for sh in self.store.shadows
                    if sh["rule_key"] == key
                    and sh["version"] == ver
                    and sh["phase"] == "shadow"
                )
            return sum(1 for sh in self.store.shadows if sh["rule_key"] == key)
        return None

    async def execute(self, sql: str, *args: Any) -> None:
        s = " ".join(sql.lower().split())
        if "insert into clinical_gate_confidence" in s:
            key = args[0]
            self.store.conf[key] = {
                "confidence": float(args[1]),
                "sample_size": int(args[2]),
            }
            return
        if "insert into ln_rule_audit" in s:
            action = args[2] if len(args) > 2 else ""
            detail = args[3] if len(args) > 3 else ""
            for lit in (
                "draft",
                "sandbox_pass",
                "sandbox_fail",
                "promote",
                "rollback",
                "fire",
                "shadow_fire",
                "accuracy_report",
            ):
                if f"'{lit}'" in s:
                    action = lit
                    break
            if len(args) == 3 and action == "rollback":
                detail = str(args[2])
            if len(args) == 3 and "sandbox_fail" in s:
                detail = str(args[2])
                action = "sandbox_fail"
            if "promoted to active" in s:
                detail = detail or "promoted to active"
            self.store.audits.append(
                {
                    "rule_key": args[0],
                    "version": int(args[1]),
                    "action": action,
                    "detail": detail,
                }
            )
            return
        if (
            "update ln_rule_store" in s
            and "rolled_back" in s
            and "status = 'active'" in s
            and "version = $2" not in s
        ):
            key = args[0]
            for r in self.store.rules:
                if r["rule_key"] == key and r["status"] == "active":
                    r["status"] = "rolled_back"
            return
        if "update ln_rule_shadow_scores" in s and "actual_label" in s:
            key, ver = args[0], int(args[1])
            actual, label = bool(args[2]), args[3]
            for sh in self.store.shadows:
                if (
                    sh["rule_key"] == key
                    and sh["version"] == ver
                    and sh["phase"] == "shadow"
                    and sh.get("actual_label") == "pending"
                ):
                    sh["actual_suppressed"] = actual
                    sh["actual_label"] = label
                    break
            return

    async def fetch(self, sql: str, *args: Any) -> List[Dict[str, Any]]:
        s = " ".join(sql.lower().split())
        if "from ln_rule_audit" in s:
            return [a for a in self.store.audits if a["rule_key"] == args[0]]
        if "from ln_rule_shadow_scores" in s:
            key = args[0]
            if len(args) > 1:
                ver = int(args[1])
                return [
                    sh
                    for sh in self.store.shadows
                    if sh["rule_key"] == key and sh["version"] == ver
                ]
            return [sh for sh in self.store.shadows if sh["rule_key"] == key]
        return []


class MemPool:
    def __init__(self) -> None:
        self.store = MemStore()

    @asynccontextmanager
    async def acquire(self):
        yield MemConn(self.store)


def _stub_gate_confidence(pool: MemPool):
    """Point clinical_gate_confidence.get_confidence at MemPool store."""
    stub = types.ModuleType("app.services.clinical_gate_confidence")

    async def get_confidence(db_pool, gate_key, default=0.70):
        row = pool.store.conf.get(gate_key)
        return float(row["confidence"]) if row else default

    stub.get_confidence = get_confidence  # type: ignore[attr-defined]
    if "app" not in sys.modules:
        sys.modules["app"] = types.ModuleType("app")
    if "app.services" not in sys.modules:
        sys.modules["app.services"] = types.ModuleType("app.services")
    sys.modules["app.services.clinical_gate_confidence"] = stub


class TestInvariantEnforcement(unittest.TestCase):
    def test_refuse_crisis_and_coach_routing(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        mod = _load("ln_rule_inv2", "ln_rule_loop.py")
        self.assertIsNotNone(
            mod.promotion_invariant_refusal(
                rule_key="x", condition={"gate_class": "crisis"},
            )
        )
        self.assertIsNotNone(
            mod.promotion_invariant_refusal(
                rule_key="x", condition={"gate_class": "coach_routing"},
            )
        )
        self.assertIsNone(
            mod.promotion_invariant_refusal(
                rule_key="soft_gate.sleep_aid.followup_suppress",
                condition={"gate_class": "sleep_aid"},
                action={"type": "suppress_soft_followup"},
            )
        )


class TestPromoteInvariant(unittest.IsolatedAsyncioTestCase):
    async def test_promote_rejects_hard_class_write(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        os.environ["LN_RULE_DUAL_COO_NOTIFY"] = "false"
        mod = _load("ln_rule_promote_inv2", "ln_rule_loop.py")
        audits: list = []

        class Conn:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            def transaction(self):
                return self

            async def fetchrow(self, sql, *args):
                return {
                    "condition_json": json.dumps({"gate_class": "coach_routing"}),
                    "action_json": json.dumps({"type": "suppress_soft_followup"}),
                    "status": "sandbox",
                }

            async def execute(self, sql, *args):
                audits.append(args)

            async def fetchval(self, *a):
                return None

        pool = MagicMock()
        pool.acquire = MagicMock(return_value=Conn())
        ok = await mod.promote_rule(
            pool, rule_key="soft_gate.coach_routing.followup", version=1,
        )
        self.assertFalse(ok)
        self.assertTrue(any("refused" in str(a) or "invariant" in str(a) for a in audits))


class TestFullCredibilityCycle(unittest.IsolatedAsyncioTestCase):
    async def test_e2e_lifecycle_rollback_and_accuracy(self):
        os.environ["ENABLE_LN_RULE_LOOP"] = "true"
        os.environ["LN_RULE_DUAL_COO_NOTIFY"] = "false"
        os.environ["LN_RULE_ACCURACY_PROMOTE_FLOOR"] = "0.0"
        os.environ["LN_RULE_ROLLBACK_CONFIDENCE"] = "0.25"
        os.environ["LN_RULE_PROMOTE_MIN_N"] = "5"
        mod = _load("ln_rule_cred_cycle2", "ln_rule_loop.py")
        pool = MemPool()
        _stub_gate_confidence(pool)
        out = await mod.run_l4_credibility_cycle(
            pool, gate_class="sleep_aid", force_rollback=True,
        )
        self.assertEqual(out.get("status"), "ok", out)
        self.assertEqual(out.get("rollback_path"), "lifecycle", out)
        self.assertTrue(out.get("l4_credible"), out)
        self.assertIsNotNone(out.get("claim_licensed"), out)
        cycle = out["cycle"]
        self.assertTrue(cycle["has_lifecycle_rollback"], cycle)
        self.assertTrue(cycle["has_promote"])
        self.assertTrue(cycle["has_shadow_or_fire"])
        self.assertGreaterEqual(cycle["shadow_score_count"], 3)
        self.assertGreaterEqual(int(cycle.get("scored") or 0), 2)
        self.assertIsNotNone(cycle.get("accuracy"))
        acc = out["accuracy"]
        self.assertGreaterEqual(float(acc.get("accuracy") or 0), 0.5)
        # Must not be a naked harness rollback without conf=
        self.assertTrue(
            any("lifecycle" in d and "conf=" in d for d in cycle["rollback_details"]),
            cycle["rollback_details"],
        )
        # Evidence rule must be rolled_back in store
        evid = [
            r
            for r in pool.store.rules
            if r["rule_key"] == out["rule_key"]
        ]
        self.assertTrue(evid and evid[0]["status"] == "rolled_back", evid)


if __name__ == "__main__":
    unittest.main()
