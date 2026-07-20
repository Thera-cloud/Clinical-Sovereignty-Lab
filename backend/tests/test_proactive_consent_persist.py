"""Consent persist uses jsonb_set (no full profile_data replace)."""

import importlib.util
import sys
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock

_ROOT = Path(__file__).resolve().parents[1]
_MOD_PATH = _ROOT / "app" / "services" / "nate_commitment_service.py"


def _load_commitment_service():
    name = "nate_commitment_service_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    sys.modules[name] = mod
    return mod


cs = _load_commitment_service()


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
async def test_update_consent_uses_jsonb_set(mock_pool):
    pool, conn = mock_pool
    conn.fetchrow = AsyncMock(
        return_value={"username": "audit_client", "hardware_id": "HW_AUDIT"}
    )
    result = await cs.update_proactive_consent(
        pool, hardware_id="HW_AUDIT", enabled=True
    )
    assert result["ok"] is True
    assert result["proactive_presence_consent"] is True
    sql = conn.fetchrow.await_args.args[0]
    assert "jsonb_set" in sql
    assert "to_jsonb($1::boolean)" in sql


@pytest.mark.asyncio
async def test_get_consent_key_absent(mock_pool):
    pool, conn = mock_pool
    conn.fetchrow = AsyncMock(return_value={"profile_data": {}})
    result = await cs.get_proactive_consent(pool, "HW_AUDIT")
    assert result["ok"] is True
    assert result["proactive_presence_consent"] is False
    assert result["key_set"] is False


@pytest.mark.asyncio
async def test_get_consent_key_true(mock_pool):
    pool, conn = mock_pool
    conn.fetchrow = AsyncMock(
        return_value={"profile_data": {"proactive_presence_consent": True}}
    )
    result = await cs.get_proactive_consent(pool, "audit_client")
    assert result["proactive_presence_consent"] is True
    assert result["key_set"] is True
