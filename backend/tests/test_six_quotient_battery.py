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

# Stub api_server.require_admin only while loading the router, then remove it.
# Leaving the stub in sys.modules poisons later CI suites (ImportError / 401).
_api_server = types.ModuleType("app.services.api_server")
_api_server.require_admin = MagicMock()  # type: ignore[attr-defined]

_api = _load(
    "app.routers.six_quotient_api",
    APP / "routers" / "six_quotient_api.py",
    inject={"app.services.api_server": _api_server},
)
sys.modules.pop("app.services.api_server", None)

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
        result = await agent.run_once(
            dry_run=True, limit=2, persist=False, multi_turn=False
        )
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("scenarios"), 2)
        self.assertEqual(result.get("mode"), "dry_run")

    async def test_dry_run_multi_turn(self):
        agent = _agent.SixQuotientBatteryAgent(db_pool=None)
        result = await agent.run_once(
            dry_run=True, limit=1, persist=False, multi_turn=True
        )
        self.assertTrue(result.get("ok"))
        self.assertIn("multi_turn", result.get("mode", ""))


_irt = _load(
    "app.services.six_quotient_irt",
    APP / "services" / "six_quotient_irt.py",
)
_judge = _load(
    "app.services.six_quotient_judge_calibration",
    APP / "services" / "six_quotient_judge_calibration.py",
)
_mt = _load(
    "app.services.six_quotient_multi_turn",
    APP / "services" / "six_quotient_multi_turn.py",
)
_gen = _load(
    "app.services.six_quotient_scenario_generator",
    APP / "services" / "six_quotient_scenario_generator.py",
)


class TestIRT(unittest.TestCase):
    def test_fisher_peaks_near_b(self):
        # At θ=b, information should be high
        i_at = _irt.fisher_information(0.0, 1.5, 0.0)
        i_far = _irt.fisher_information(3.0, 1.5, 0.0)
        self.assertGreater(i_at, i_far)

    def test_select_max_info(self):
        items = [
            {"scenario_key": "a", "irt_a": 1.0, "irt_b": 0.0},
            {"scenario_key": "b", "irt_a": 2.0, "irt_b": 0.1},
            {"scenario_key": "c", "irt_a": 0.5, "irt_b": 2.0},
        ]
        picked = _irt.select_max_info(items, theta=0.0, k=2)
        keys = {p["scenario_key"] for p in picked}
        self.assertIn("b", keys)


class TestJudgeCalibration(unittest.TestCase):
    def test_perfect_match_passes(self):
        gold = _judge.load_gold()
        ratings = []
        for it in gold["items"]:
            ratings.append({"id": it["id"], **it["ratings"]})
        result = _judge.calibrate_evaluator(ratings)
        self.assertTrue(result["passed"])
        self.assertGreaterEqual(result["kappa"], 0.9)

    def test_bad_match_fails(self):
        gold = _judge.load_gold()
        ratings = [
            {"id": it["id"], "primary": 0, "accuracy": 0, "naturalness": 0}
            for it in gold["items"]
        ]
        # Invert from gold AQ-fail which is already low — force mismatch on good items
        result = _judge.calibrate_evaluator(ratings)
        self.assertFalse(result["passed"])


class TestSafetyScan(unittest.TestCase):
    def test_pii_flagged(self):
        flags = _gen.safety_scan("My SSN is 123-45-6789 and email a@b.com")
        self.assertIn("pii_pattern", flags)

    def test_bleed_flagged(self):
        flags = _gen.safety_scan("Welcome to Sovereign Sanctuary with Little Nate")
        self.assertIn("platform_bleed", flags)


class TestGenerateTextExtract(unittest.TestCase):
    def test_inference_result_dataclass(self):
        class FakeResult:
            text = '{"title":"x"}'
            provider = "grok"

        text, provider = _gen._extract_generate_text(FakeResult())
        self.assertEqual(text, '{"title":"x"}')
        self.assertEqual(provider, "grok")

    def test_dict_and_str(self):
        t, p = _gen._extract_generate_text({"text": "hi", "provider": "workers_ai"})
        self.assertEqual(t, "hi")
        self.assertEqual(p, "workers_ai")
        t2, _ = _gen._extract_generate_text("plain")
        self.assertEqual(t2, "plain")


class TestAiEvaluatorGate(unittest.TestCase):
    def test_ai_vs_human(self):
        self.assertTrue(_api._is_ai_evaluator("gpt-4o-judge"))
        self.assertTrue(_api._is_ai_evaluator("claude-sonnet-judge"))
        self.assertFalse(_api._is_ai_evaluator("DrNevedal1"))
        self.assertFalse(_api._is_ai_evaluator("clinician_hope"))


class TestAuditorEndpointCount(unittest.TestCase):
    def test_eighteen_checks(self):
        aud = _load(
            "app.services.six_quotient_battery_auditor",
            APP / "services" / "six_quotient_battery_auditor.py",
        )
        total = sum(len(t["endpoints"]) for t in aud.TAB_ENDPOINTS)
        self.assertEqual(total, 18)


class TestMultiTurnProcess(unittest.TestCase):
    def test_process_metrics(self):
        turns = [
            {"role": "client", "text": "I have a plan"},
            {"role": "nate", "text": "Tell me about means and whether you are safe"},
            {"role": "client", "text": "pills"},
            {"role": "nate", "text": "I hear the hurt underneath"},
        ]
        m = _mt.process_metrics(turns, "AQ")
        self.assertEqual(m["turns_to_lethality_language"], 1)
        self.assertEqual(m["turns_to_affect_language"], 2)
        self.assertEqual(m["scoring_authority"], "external_only")


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
