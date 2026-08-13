"""book_session must not persist — coach decides via client_book_session."""

import importlib.util
import sys
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock

_ROOT = Path(__file__).resolve().parents[1]
_MOD_PATH = _ROOT / "app" / "services" / "session_booking_service.py"


def _load_booking():
    name = "session_booking_service_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    sys.modules[name] = mod
    return mod


booking = _load_booking()


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
async def test_book_session_writes_pending(mock_pool):
    pool, _conn = mock_pool
    result = await booking.book_session(
        pool,
        client_hw_id="HW_CLIENT",
        slot_start="2026-07-22T15:00:00+00:00",
    )
    assert result["success"] is False
    assert result["error"] == "coach_decision_required"
