"""Offline unit tests for Six-Quotient Battery flywheel.

Loads modules via importlib to avoid app.services.__init__ → numpy crash on macOS.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"


def _load(name: str, path: Path, inject: dict | None = None):
    """Load a module from file; optionally pre-inject deps into sys.modules."""
    if inject:
        for k, v in inject.items():
            sys.modules[k] = v
    # Stub package parents so relative-looking imports resolve lightly
    if "app" not in sys.modules:
        sys.modules["app"] = types.ModuleType("app")
    if "app.services" not in sys.modules:
        pkg = types.ModuleType("app.services")
        pkg.__path__ = [str(APP / "services")]  # type: ignore[attr-defined]
        sys.modules["app.services"] = pkg
    if "app.routers" not in sys.modules:
        pkg = types.ModuleType("app.routers")
        pkg.__path__ = [str(APP / "routers")]  # type: ignore[attr-defined]
        sys.modules["app.routers"] = pkg
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Preload growth engine (gap analyzer depends on it) without package __init__
_growth = _load(
    "app.services.six_quotient_growth_engine",
    APP / "services" / "six_quotient_growth_engine.py",
)
_pregrader = _load(
    "app.services.six_quotient_pregrader",
    APP / "services" / "six_quotient_pregrader.py",
)
_gap = _load(
    "app.services.six_quotient_gap_analyzer",
    APP / "services" / "six_quotient_gap_analyzer.py",
    inject={"app.services.six_quotient_growth_engine": _growth},
)

# Stub api_server.require_admin for router import
_api_server = types.ModuleType("app.services.api_server")
_api_server.require_admin = MagicMock()  # type: ignore[attr-defined]
sys.modules["app.services.api_server"] = _api_server

_api = _load(
    "app.routers.six_quotient_api",
    APP / "routers" / "six_quotient_api.py",
)

_agent = _load(
    "app.services.six_quotient_battery_agent",
    APP / "services" / "six_quotient_battery_agent.py",
    inject={
        "app.services.six_quotient_pregrader": _pregrader,
    },
)


class TestPregrader(unittest.TestCase):
    def test_flags_banned_words(self):
        pg = _pregrader.pregrade_response(
            scenario_id="AQ-3",
            section="AQ",
            client_says="my child is dying",
            response="I hear you standing at this aching threshold of grief.",
        )
        self.assertIn("banned_word", pg["flags"])
        self.assertEqual(pg["scoring_authority"], "external_only")
        self.assertNotIn("score", pg)

    def test_solution_offering_on_aq(self):
        pg = _pregrader.pregrade_response(
            scenario_id="AQ-3",
            section="AQ",
            client_says="unsolvable",
            response="Have you tried a grounding technique or coping strategy?",
        )
        self.assertIn("solution_offering", pg["flags"])
        self.assertIn("solution_offering", pg["attention_areas"])

    def test_battery_wrap(self):
        rows = _pregrader.pregrade_battery([
            {
                "scenario_id": "SQ-2",
                "section": "SQ",
                "response": "Absolutely, of course, here are some actionable steps.",
            }
        ])
        self.assertIn("accommodation", rows[0]["pregrade"]["flags"])


class TestGapAggregator(unittest.TestCase):
    def test_aggregate_full_battery(self):
        scores = []
        for q in ("IQ", "EQ", "MQ", "SQ", "CQ", "AQ"):
            for i in range(1, 5):
                scores.append({
                    "scenario_id": f"{q}-{i}",
                    "section": q,
                    "primary": 3,
                    "accuracy": 3,
                    "naturalness": 3,
                })
        by = _gap.aggregate_scores_by_section(scores)
        self.assertEqual(by["IQ"]["score"], 36)
        self.assertEqual(by["IQ"]["pct"], 100.0)

    def test_aq_regression_is_red(self):
        scores = [
            {"scenario_id": f"AQ-{i}", "section": "AQ", "primary": 1, "accuracy": 1, "naturalness": 1}
            for i in range(1, 5)
        ]
        by = _gap.aggregate_scores_by_section(scores)
        self.assertEqual(by["AQ"]["score"], 12)
        self.assertEqual(by["AQ"]["risk"], "RED")


class TestScenariosPack(unittest.TestCase):
    def test_v4_pack_has_24(self):
        path = BACKEND / "app" / "data" / "six_quotient_scenarios_v4.json"
        self.assertTrue(path.exists(), path)
        pack = json.loads(path.read_text())
        self.assertEqual(pack["battery_version"], "v4")
        self.assertEqual(len(pack["scenarios"]), 24)


class TestScoresIntakeValidation(unittest.TestCase):
    def test_rejects_self_evaluator(self):
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            _api.ScoresIntake(
                run_id="00000000-0000-0000-0000-000000000001",
                evaluator_id="self",
                scores=[{
                    "scenario_id": "IQ-1",
                    "primary": 2,
                    "accuracy": 2,
                    "naturalness": 2,
                }],
            )

    def test_accepts_external_evaluator(self):
        body = _api.ScoresIntake(
            run_id="00000000-0000-0000-0000-000000000001",
            evaluator_id="gemini-external-2026-07",
            scores=[{
                "scenario_id": "IQ-1",
                "section": "IQ",
                "primary": 2,
                "accuracy": 2,
                "naturalness": 2,
            }],
        )
        self.assertEqual(body.evaluator_id, "gemini-external-2026-07")


class TestBatteryAgentDryRun(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_no_db(self):
        agent = _agent.SixQuotientBatteryAgent(db_pool=None)
        result = await agent.run_once(dry_run=True, limit=2, persist=False)
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("scenarios"), 2)
        self.assertEqual(result.get("mode"), "dry_run")


class TestRunnerDryRun(unittest.IsolatedAsyncioTestCase):
    async def test_cli_dry_run(self):
        runner_path = BACKEND / "scripts" / "six_quotient_battery_runner.py"
        mod = _load("sq_battery_runner_test", runner_path)
        p = mod.build_parser()
        args = p.parse_args(["--dry-run", "--limit", "1", "--out-dir", "/tmp/sq_battery_test_out"])
        rc = await mod.main_async(args)
        self.assertEqual(rc, 0)
        out = Path("/tmp/sq_battery_test_out/master_results.json")
        self.assertTrue(out.exists())
        data = json.loads(out.read_text())
        self.assertEqual(data["scoring"], "EXTERNAL — no automated scoring")
        self.assertEqual(len(data["results"]), 1)


if __name__ == "__main__":
    unittest.main()
