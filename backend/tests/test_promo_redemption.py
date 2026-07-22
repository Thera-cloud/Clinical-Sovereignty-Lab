from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.promo_redemption import record_promo_redemption


@pytest.mark.asyncio
async def test_record_promo_redemption_increments_promotional_special():
    db = AsyncMock()
    db.execute.return_value = "UPDATE 1"

    ok = await record_promo_redemption(
        db,
        promo_code=" lpcmvp-100 ",
        source="promotional_specials",
    )

    assert ok is True
    db.execute.assert_awaited_once()
    query, code = db.execute.await_args.args
    assert "promotional_specials" in query
    assert code == "LPCMVP-100"


@pytest.mark.asyncio
async def test_record_promo_redemption_skips_empty_code():
    db = AsyncMock()

    ok = await record_promo_redemption(db, promo_code="   ", source="promotional_specials")

    assert ok is False
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_promo_redemption_respects_max_cap():
    db = AsyncMock()
    db.execute.return_value = "UPDATE 0"

    ok = await record_promo_redemption(db, promo_code="FULL10", source="promotional_specials")

    assert ok is False
