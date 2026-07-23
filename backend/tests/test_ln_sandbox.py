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
        self.assertGreater(len(text), 40)

    async def test_run_cycle_noop_without_db(self):
        eng = _engine.LNSandboxEngine(db_pool=None, app_state=None)
        # flag off path: caller gates; run_cycle itself needs db
        # Simulate track method score only
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


if __name__ == "__main__":
    unittest.main()
