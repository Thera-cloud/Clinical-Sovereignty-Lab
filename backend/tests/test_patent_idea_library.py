"""Offline unit tests — patent idea library rank gate, study cap, archive.

Loads via importlib to avoid app.services.__init__ → numpy crash on macOS.
# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"


def _ensure_pkg(name: str, path: Path) -> None:
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]  # type: ignore[attr-defined]
        sys.modules[name] = pkg


def _load(name: str, path: Path):
    _ensure_pkg("app", APP.parent if APP.name == "app" else APP)
    _ensure_pkg("app.services", APP / "services")
    _ensure_pkg("app.websocket", APP / "websocket")
    if "app" not in sys.modules or not getattr(sys.modules["app"], "__path__", None):
        app_mod = types.ModuleType("app")
        app_mod.__path__ = [str(APP)]  # type: ignore[attr-defined]
        sys.modules["app"] = app_mod
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_lib = _load(
    "app.services.patent_idea_library_engine",
    APP / "services" / "patent_idea_library_engine.py",
)
_refl = _load(
    "app.services.patent_reflection_engine",
    APP / "services" / "patent_reflection_engine.py",
)
_cli = _load(
    "app.websocket.cli_dual_coo",
    APP / "websocket" / "cli_dual_coo.py",
)

PROMOTE_MIN = _lib.PROMOTE_MIN
SEED_WEIGHTS = _lib.SEED_WEIGHTS
PatentIdeaLibraryEngine = _lib.PatentIdeaLibraryEngine
PatentReflectionEngine = _refl.PatentReflectionEngine
clamp_weights = _lib.clamp_weights
compute_rank_score = _lib.compute_rank_score
pick_study_category = _lib.pick_study_category
patent_reflections_enabled = _lib.patent_reflections_enabled
slugify = _lib.slugify
classify_risk = _cli.classify_risk
RISK_GREEN = _cli.RISK_GREEN
RISK_YELLOW = _cli.RISK_YELLOW


class TestPatentRankMath(unittest.TestCase):
    def test_promote_min_default_90(self):
        self.assertGreaterEqual(PROMOTE_MIN, 90.0)

    def test_weights_sum_to_one(self):
        w = clamp_weights(SEED_WEIGHTS)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=5)

    def test_score_89_below_exploit(self):
        dims = {k: 89.0 for k in SEED_WEIGHTS}
        score = compute_rank_score(dims, SEED_WEIGHTS)
        self.assertLess(score, PROMOTE_MIN)

    def test_score_95_can_exploit(self):
        dims = {k: 95.0 for k in SEED_WEIGHTS}
        score = compute_rank_score(dims, SEED_WEIGHTS)
        self.assertGreaterEqual(score, PROMOTE_MIN)

    def test_category_mix_covers_pillars(self):
        cats = {pick_study_category(x) for x in (0.0, 0.29, 0.35, 0.55, 0.80, 0.99)}
        self.assertTrue(cats & {"world_qol", "platform", "qec_quantum", "queens_nate"})

    def test_slugify(self):
        self.assertEqual(slugify("Hello World!!"), "hello-world")


class TestPatentRiskClassify(unittest.TestCase):
    def test_patent_reflect_is_yellow(self):
        self.assertEqual(classify_risk(kind="patent_reflect"), RISK_YELLOW)

    def test_patent_implement_is_yellow(self):
        self.assertEqual(classify_risk(kind="patent_implement_sandbox"), RISK_YELLOW)

    def test_patent_tag_propose_stays_green(self):
        self.assertEqual(classify_risk(kind="patent_tag_propose"), RISK_GREEN)


class TestPatentFlag(unittest.TestCase):
    def test_flag_default_off(self):
        with patch.dict(os.environ, {"ENABLE_PATENT_REFLECTIONS": "false"}, clear=False):
            self.assertFalse(patent_reflections_enabled())

    def test_flag_on(self):
        with patch.dict(os.environ, {"ENABLE_PATENT_REFLECTIONS": "true"}, clear=False):
            self.assertTrue(patent_reflections_enabled())


class TestSandboxPathGuard(unittest.TestCase):
    def test_rejects_official_patent_write(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "sandbox_reflections"), exist_ok=True)
            eng = PatentIdeaLibraryEngine(None, patent_root=td)
            with self.assertRaises(ValueError):
                eng._assert_sandbox_path(
                    os.path.join(td, "QUANTUM_EMOTIONAL_COHERENCE_PATENT.md")
                )

    def test_allows_sandbox(self):
        with tempfile.TemporaryDirectory() as td:
            sandbox = os.path.join(td, "sandbox_reflections")
            os.makedirs(sandbox, exist_ok=True)
            eng = PatentIdeaLibraryEngine(None, patent_root=td)
            p = eng._assert_sandbox_path(os.path.join(sandbox, "x.md"))
            self.assertTrue(p.endswith("x.md"))


class TestCategoryGrouping(unittest.TestCase):
    def test_group_by_category_and_topic(self):
        eng = PatentIdeaLibraryEngine(None)
        rows = [
            {"id": 1, "primary_category": "world_qol", "topics": ["trauma_informed_qol"]},
            {"id": 2, "primary_category": "platform", "topics": ["trust", "voice_pipeline"]},
            {"id": 3, "primary_category": "platform", "topics": ["trust"]},
        ]
        grouped = eng.group_by_category(rows)
        self.assertIn("trauma_informed_qol", grouped["world_qol"])
        self.assertEqual(len(grouped["platform"]["trust"]), 2)
        self.assertEqual(len(grouped["platform"]["voice_pipeline"]), 1)


class TestArchiveExclusion(unittest.IsolatedAsyncioTestCase):
    async def test_list_excludes_archived_by_default(self):
        pool = MagicMock()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        pool.acquire = MagicMock(return_value=cm)
        eng = PatentIdeaLibraryEngine(pool)
        await eng.list_library()
        sql = conn.fetch.await_args.args[0]
        self.assertIn("library_status <> 'archived'", sql)

    async def test_list_status_archived_includes(self):
        pool = MagicMock()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        pool.acquire = MagicMock(return_value=cm)
        eng = PatentIdeaLibraryEngine(pool)
        await eng.list_library(status="archived", include_archived=True)
        sql = conn.fetch.await_args.args[0]
        self.assertIn("library_status = $1", sql)
        self.assertNotIn("library_status <> 'archived'", sql)


class TestStudyCapLogic(unittest.IsolatedAsyncioTestCase):
    async def test_study_cap_blocks_fourth(self):
        pool = MagicMock()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=3)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        pool.acquire = MagicMock(return_value=cm)

        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "sandbox_reflections"), exist_ok=True)
            eng = PatentIdeaLibraryEngine(pool, patent_root=td)
            rem = await eng.study_cap_remaining()
            self.assertEqual(rem, 0)
            res = await eng.upsert_from_study(
                title="Fourth idea",
                category="platform",
                topics=["t"],
                summary="summary text long enough for scoring",
                reflection_md="reflection",
                source_paths=[],
                has_proven_anchor=True,
            )
            self.assertEqual(res.get("status"), "skipped")
            self.assertEqual(res.get("reason"), "study_cap")


class TestDecideNotReady(unittest.IsolatedAsyncioTestCase):
    async def test_approve_requires_ready(self):
        pool = MagicMock()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "library_id": 9,
                "status": "pending",
                "sandbox_path": "/tmp/x.md",
                "idea_summary": "x",
            }
        )
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        pool.acquire = MagicMock(return_value=cm)

        eng = PatentReflectionEngine(pool)
        res = await eng.decide(1, decision="APPROVE_CLI")
        self.assertEqual(res.get("status"), "error")
        self.assertEqual(res.get("error"), "not_ready")


class TestAuditorEndpointCount(unittest.TestCase):
    def test_ceo_auditor_has_10(self):
        path = APP / "services" / "ceo_dual_coo_auditor.py"
        ns: dict = {}
        exec(open(path).read(), ns)
        total = sum(len(t["endpoints"]) for t in ns["TAB_ENDPOINTS"])
        self.assertEqual(total, 10)


if __name__ == "__main__":
    unittest.main()
