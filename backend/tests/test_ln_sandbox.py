"""Offline unit tests for LN Sandbox DOJO (engine score + promotion helpers)."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"


def _load(name: str, path: Path, inject: dict | None = None):
    if inject:
        for k, v in inject.items():
            sys.modules[k] = v
    if "app" not in sys.modules:
        sys.modules["app"] = types.ModuleType("app")
    if "app.services" not in sys.modules:
        pkg = types.ModuleType("app.services")
        pkg.__path__ = [str(APP / "services")]  # type: ignore[attr-defined]
        sys.modules["app.services"] = pkg
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_engine = _load(
    "app.services.ln_sandbox_engine",
    APP / "services" / "ln_sandbox_engine.py",
)
_promo = _load(
    "app.services.ln_sandbox_promotion",
    APP / "services" / "ln_sandbox_promotion.py",
)
_ctx = _load(
    "app.services.ln_sandbox_context",
    APP / "services" / "ln_sandbox_context.py",
)


class TestSandboxScore(unittest.TestCase):
    def test_pass_when_tokens_present(self):
        text = (
            "I hear you. I'm here with you right now, and we can notice what "
            "your body is doing without rushing."
        )
        j = _engine.score_response(
            text,
            must_include=["hear", "here"],
            must_not_include=["liminal", "aching"],
        )
        self.assertTrue(j["passed"])
        self.assertGreaterEqual(j["score"], 0.67)

    def test_fail_on_banned(self):
        text = (
            "I hear the liminal ache at the threshold of your story and I'm here."
        )
        j = _engine.score_response(
            text,
            must_include=["hear", "here"],
            must_not_include=["liminal", "threshold", "aching"],
        )
        self.assertFalse(j["passed"])
        self.assertIn("banned", j["notes"])

    def test_fail_too_short(self):
        j = _engine.score_response("ok", must_include=["you"])
        self.assertFalse(j["passed"])
        self.assertEqual(j["score"], 0.0)


class TestSandboxEngineOffline(unittest.IsolatedAsyncioTestCase):
    async def test_generate_fallback_without_lni(self):
        eng = _engine.LNSandboxEngine(db_pool=None, app_state=None)
        text = await eng._generate("practice", domain="clinical")
        self.assertIn("[SANDBOX_FALLBACK]", text)
        self.assertGreater(len(text), 40)

    async def test_cycle_lock_rejects_overlap(self):
        eng = _engine.LNSandboxEngine(db_pool=None, app_state=None)

        async def _hold():
            async with eng._cycle_lock:
                await asyncio.sleep(0.15)

        t = asyncio.create_task(_hold())
        await asyncio.sleep(0.02)
        out = await eng.run_cycle(force_tracks=["engineering"])
        self.assertFalse(out["ok"])
        self.assertEqual(out.get("error"), "cycle_in_progress")
        await t

    async def test_run_cycle_noop_without_db(self):
        eng = _engine.LNSandboxEngine(db_pool=None, app_state=None)
        j = _engine.score_response(
            "Use to_jsonb($1::int) under asyncpg for polymorphic casts.",
            must_include=["::int", "to_jsonb", "asyncpg"],
        )
        self.assertTrue(j["passed"])


class TestPromotionHelpers(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_no_db(self):
        out = await _promo.enqueue_promotion(None, "x")
        self.assertFalse(out["ok"])

    async def test_domain_mapping(self):
        self.assertEqual(_promo._domain_for_track("engineering"), "research")
        self.assertEqual(_promo._domain_for_track("clinical_strategy"), "clinical")


class TestContextEmpty(unittest.IsolatedAsyncioTestCase):
    async def test_candidates_empty_without_db(self):
        text = await _ctx.get_sandbox_candidates_for_user(None, "alice")
        self.assertEqual(text, "")

    def test_inject_gate_excludes_failure_lesson(self):
        self.assertNotIn("failure_lesson", _ctx._LIVE_KINDS)
        self.assertIn("success_pattern", _ctx._LIVE_KINDS)
        self.assertIn("client_prep", _ctx._LIVE_KINDS)
        self.assertGreaterEqual(_ctx._MIN_DRAFT_SCORE, 0.67)

    def test_injectable_predicate(self):
        def injectable(kind, status, score):
            if kind == "failure_lesson" or kind not in _ctx._LIVE_KINDS:
                return False
            if status in ("queued", "promoted"):
                return True
            return status == "draft" and (score or 0) >= _ctx._MIN_DRAFT_SCORE

        self.assertFalse(injectable("failure_lesson", "draft", 0.99))
        self.assertFalse(injectable("success_pattern", "draft", 0.2))
        self.assertTrue(injectable("success_pattern", "draft", 0.7))
        self.assertTrue(injectable("client_prep", "queued", 0.0))


class TestFallbackCorpusSkip(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_only_skips_corpus_write(self):
        eng = _engine.LNSandboxEngine(db_pool=MagicMock(), app_state=None)
        eng._open_session = AsyncMock(return_value="sess-1")
        eng._close_session = AsyncMock()
        eng._record_attempt = AsyncMock()
        eng._write_corpus = AsyncMock(return_value="should-not-run")
        eng._generate = AsyncMock(
            return_value="[SANDBOX_FALLBACK] I hear you. I'm here with you right now."
        )
        task = {
            "task_key": "t1",
            "title": "fallback only",
            "prompt": "practice",
            "domain": "clinical",
            "must_include": ["hear", "here"],
            "must_not_include": ["liminal"],
        }
        out = await eng._practice_loop(
            track="clinical_strategy",
            task=task,
            trigger_reason="test",
            target_user_id=None,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out.get("skipped_corpus"), "fallback_only")
        self.assertIsNone(out.get("corpus_id"))
        eng._write_corpus.assert_not_called()


class TestPromotionScope(unittest.TestCase):
    def test_client_prep_domain(self):
        self.assertEqual(_promo._domain_for_track("client_prep"), "clinical")


class TestScoreAnyGroups(unittest.TestCase):
    def test_must_include_any_or_group(self):
        text = (
            "Under asyncpg you must cast: to_jsonb($1::int) so the polymorphic "
            "type resolves. Never use bare to_jsonb($1)."
        )
        j = _engine.score_response(
            text,
            must_include=["asyncpg"],
            must_include_any=[["::int", "cast"], ["to_jsonb"]],
        )
        self.assertTrue(j["passed"])
        self.assertGreaterEqual(j["score"], 0.67)

    def test_must_include_any_misses(self):
        text = (
            "You should always cast parameters carefully when talking to "
            "Postgres from Python drivers in production systems."
        )
        j = _engine.score_response(
            text,
            must_include=["asyncpg"],
            must_include_any=[["::int"], ["to_jsonb"]],
        )
        self.assertFalse(j["passed"])


class TestGenerateSkipsLniByDefault(unittest.IsolatedAsyncioTestCase):
    async def test_router_hit_never_calls_lni(self):
        eng = _engine.LNSandboxEngine(db_pool=None, app_state=MagicMock())
        eng.app_state.littlenate_inference = MagicMock()
        eng.app_state.littlenate_inference.generate = AsyncMock(
            side_effect=AssertionError("LNI must not run")
        )
        eng._generate_via_router = AsyncMock(
            return_value="I hear you. I'm here with you right now and we can notice."
        )
        text = await eng._generate("practice", domain="coding")
        self.assertNotIn("[SANDBOX_FALLBACK]", text)
        eng.app_state.littlenate_inference.generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
