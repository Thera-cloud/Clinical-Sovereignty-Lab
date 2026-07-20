"""Phase 3: detect_plan_divergence + maybe_record_plan_divergence wiring."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_MOD_PATH = _ROOT / "app" / "services" / "nate_therapeutic_plan_service.py"


def _load():
    name = "nate_therapeutic_plan_service_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    sys.modules[name] = mod
    return mod


tp = _load()


def test_detect_divergence_off_topic_markers():
    assert tp.detect_plan_divergence(
        "I want to talk about something else entirely today",
        "attachment and trust building",
    )


def test_detect_no_divergence_when_theme_overlap():
    assert not tp.detect_plan_divergence(
        "I've been thinking a lot about attachment and trust this week",
        "attachment and trust building",
    )


@pytest.fixture
def mock_pool():
    conn = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool, conn


@pytest.mark.asyncio
async def test_maybe_record_divergence_appends_log(mock_pool, monkeypatch):
    monkeypatch.setenv("ENABLE_THERAPEUTIC_PLANS", "true")
    pool, conn = mock_pool
    conn.fetchrow = AsyncMock(
        return_value={
            "id": "11111111-1111-1111-1111-111111111111",
            "current_step": 1,
            "step_definitions": [{"step_number": 1, "theme": "grief processing"}],
        }
    )
    conn.execute = AsyncMock()
    result = await tp.maybe_record_plan_divergence(
        pool,
        "audit_client",
        "I want to change the subject and talk about something else entirely",
    )
    assert result is True
    assert conn.execute.await_count >= 1
    sql = conn.execute.await_args.args[0]
    assert "adaptation_log" in sql


@pytest.mark.asyncio
async def test_maybe_record_skips_when_flag_off(mock_pool, monkeypatch):
    monkeypatch.setenv("ENABLE_THERAPEUTIC_PLANS", "false")
    pool, _ = mock_pool
    result = await tp.maybe_record_plan_divergence(pool, "audit_client", "hello")
    assert result is False
