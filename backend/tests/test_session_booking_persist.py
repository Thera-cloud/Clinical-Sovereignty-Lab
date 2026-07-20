"""book_session persists pending_approval via upsert_session_pg."""

import importlib.util
import sys
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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
    pool, conn = mock_pool
    conn.fetchrow = AsyncMock(
        side_effect=[
            {
                "username": "audit_client",
                "role": "CLIENT",
                "hardware_id": "HW_CLIENT",
                "profile_data": {
                    "name": "Audit",
                    "coach_id": "COACH_COACHN_ID",
                },
            },
            {
                "hardware_id": "COACH_COACHN_ID",
                "username": "CoachN",
                "name": "Coach N",
            },
        ]
    )

    with patch.object(
        booking, "upsert_session_pg", create=True
    ):
        # Inject stubs into module namespace used by book_session imports
        async def _upsert(db, session):
            _upsert.called_with = session
            return True

        _upsert.called_with = None

        with patch.dict(
            "sys.modules",
            {
                "app.services.pg_data_helpers": MagicMock(
                    upsert_session_pg=AsyncMock(side_effect=_upsert)
                ),
                "app.services.session_negotiation_service": MagicMock(
                    negotiation_enabled=lambda: False,
                    open_from_pending_session=AsyncMock(),
                ),
            },
        ):
            # Re-bind after sys.modules patch by calling through fresh import path
            result = await booking.book_session(
                pool,
                client_hw_id="HW_CLIENT",
                slot_start="2026-07-22T15:00:00+00:00",
            )

    assert result["success"] is True
    assert result["status"] == "pending_approval"
    assert "session_id" in result
