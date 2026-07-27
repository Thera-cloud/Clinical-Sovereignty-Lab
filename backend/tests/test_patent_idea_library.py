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
    """Load module under a unique name — never overwrite live app.* sys.modules entries.

    Overwriting app.websocket.cli_dual_coo leaves a stale package attribute and breaks
    other suites that patch _redis on the real module (full CI gate).
    """
    _ensure_pkg("app", APP)
    _ensure_pkg("app.services", APP / "services")
    # Pre-register real library engine under its import path so reflection engine
    # `from app.services.patent_idea_library_engine import ...` resolves without
    # pulling app.services.__init__ (numpy).
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Unique names — do not clobber app.websocket.cli_dual_coo
_lib = _load(
    "patent_test_idea_library_engine",
    APP / "services" / "patent_idea_library_engine.py",
)
sys.modules["app.services.patent_idea_library_engine"] = _lib

_refl = _load(
    "patent_test_reflection_engine",
    APP / "services" / "patent_reflection_engine.py",
)

_cli = _load(
    "patent_test_cli_dual_coo",
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


class TestPatentCeoEmailBrief(unittest.TestCase):
    def test_brief_has_promote_level_and_summary(self):
        brief = _refl._patent_ceo_email_brief(
            title="Field coherence mesh",
            category="qec_quantum",
            topics=["coherence", "mesh"],
            summary=(
                "This idea extends QEC field sensing across household nodes. "
                "It proposes claim language for multi-node emotional coherence. "
                "Prior art risk is moderate. Enablement needs structural detail. "
                "Sandbox only until you approve."
            ),
            score=92.5,
            promote_reason="exploit",
            reflection_id=42,
        )
        pl = brief["payload"]
        self.assertEqual(pl["kind"], "patent_reflect")
        self.assertIn("EXPLOIT", pl["promote_level"])
        self.assertIn("Field coherence", pl["ceo_summary"])
        self.assertGreaterEqual(len(pl["why_it_matters"].split(".")), 3)
        self.assertIn("Patent Review", brief["email_title"])


class TestAuditorEndpointCount(unittest.TestCase):
    def test_ceo_auditor_has_10(self):
        path = APP / "services" / "ceo_dual_coo_auditor.py"
        ns: dict = {}
        exec(open(path).read(), ns)
        total = sum(len(t["endpoints"]) for t in ns["TAB_ENDPOINTS"])
        self.assertEqual(total, 10)


if __name__ == "__main__":
    unittest.main()
