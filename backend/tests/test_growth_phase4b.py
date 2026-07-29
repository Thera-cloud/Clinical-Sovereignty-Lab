"""Phase 4b Adaptive Growth — try theme telemetry + crystal poison guards.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import asyncio
import inspect
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.growth import try_theme_telemetry_enabled
from app.services.growth.try_theme_classifier import (
    THEME_ALLOWLIST,
    classify_try_theme,
)
from app.services.growth.try_theme_emitter import emit_try_theme
from app.services.trial_merge_ingestion import assert_trial_merge_crystal_allowed


def test_flag_default_off():
    with patch.dict(os.environ, {"ENABLE_TRY_THEME_TELEMETRY": "false"}, clear=False):
        assert try_theme_telemetry_enabled() is False
    with patch.dict(os.environ, {"ENABLE_TRY_THEME_TELEMETRY": "true"}, clear=False):
        assert try_theme_telemetry_enabled() is True


def test_classifier_allowlist_anxiety():
    assert classify_try_theme("I've had so much anxiety this week") == "anxiety"
    assert "anxiety" in THEME_ALLOWLIST


def test_classifier_crisis_ops_only():
    assert classify_try_theme("I want to kill myself tonight") == "ops_only"
    assert classify_try_theme("thinking about suicide a lot") == "ops_only"


def test_classifier_no_match():
    assert classify_try_theme("hello") is None
    assert classify_try_theme("") is None


def test_classifier_never_returns_ops_only_as_upsert_candidate():
    """ops_only must not be in THEME_ALLOWLIST (cannot PK upsert)."""
    assert "ops_only" not in THEME_ALLOWLIST


def test_emit_skips_when_flag_off():
    async def _run():
        with patch.dict(os.environ, {"ENABLE_TRY_THEME_TELEMETRY": "false"}, clear=False):
            return await emit_try_theme(MagicMock(), "anxiety about work")

    out = asyncio.run(_run())
    assert out.get("skipped") is True


def test_emit_crisis_no_upsert():
    pool = MagicMock()
    pool.acquire = MagicMock()

    async def _run():
        with patch.dict(os.environ, {"ENABLE_TRY_THEME_TELEMETRY": "true"}, clear=False):
            return await emit_try_theme(pool, "I want to end my life")

    out = asyncio.run(_run())
    assert out.get("theme") == "ops_only"
    assert out.get("upserted") is False
    pool.acquire.assert_not_called()


def test_emit_upserts_theme():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__.return_value = conn
    cm.__aexit__.return_value = None
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=cm)

    async def _run():
        with patch.dict(os.environ, {"ENABLE_TRY_THEME_TELEMETRY": "true"}, clear=False):
            return await emit_try_theme(pool, "My marriage is falling apart")

    out = asyncio.run(_run())
    assert out.get("upserted") is True
    assert out.get("theme") == "couples_conflict"
    conn.execute.assert_awaited()
    sql = conn.execute.await_args.args[0]
    assert "try_theme_weekly" in sql
    args = conn.execute.await_args.args[1:]
    assert all("marriage" not in str(a).lower() for a in args)


def test_merge_forbids_marketing_global():
    with pytest.raises(ValueError, match="forbids"):
        assert_trial_merge_crystal_allowed(domain="marketing", scope="global")
    # clinical/user allowed
    assert_trial_merge_crystal_allowed(domain="clinical", scope="user")


def test_crystallizer_harvest_denies_public_trial_merge():
    import app.services.nate_memory_crystallizer as cryst

    src = inspect.getsource(cryst.NateMemoryCrystallizer._harvest_cycle)
    assert "public_trial_merge" in src
    assert "NOT IN" in src or "not in" in src.lower()
    assert "trial_%" in src


def test_no_llm_in_classifier_module():
    import app.services.growth.try_theme_classifier as mod

    src = inspect.getsource(mod)
    for banned in ("openai", "NateInferenceRouter", "generate(", "chat.completions"):
        assert banned not in src


def test_finalize_is_single_emit_call_site():
    import app.services.public_trial_gate as gate

    src = inspect.getsource(gate.finalize_public_trial_turn)
    # import + create_task — only call site in finalize
    assert src.count("emit_try_theme") == 2
    assert "create_task" in src
    # No other module-level emit outside finalize
    mod = inspect.getsource(gate)
    assert mod.count("create_task(emit_try_theme") == 1
