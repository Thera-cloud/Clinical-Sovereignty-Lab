"""Tests for SSE family engine — creation, age gating, heritage, privacy."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date, datetime, timezone


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db_pool():
    pool = AsyncMock()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


# ---------------------------------------------------------------------------
# Pure Functions (no DB needed)
# ---------------------------------------------------------------------------

def test_compute_age():
    from app.sse.family_engine import _compute_age
    today = date.today()
    assert _compute_age(date(today.year - 30, today.month, today.day)) == 30
    assert _compute_age(date(today.year - 17, today.month, today.day)) == 17
    future_bday = date(today.year - 10, 12, 31) if today.month < 12 else date(today.year - 10, 1, 1)
    age = _compute_age(future_bday)
    assert age >= 9  # sanity — roughly 10


def test_age_tier():
    from app.sse.family_engine import _age_tier
    assert _age_tier(5) == "child"
    assert _age_tier(12) == "child"
    assert _age_tier(13) == "adolescent"
    assert _age_tier(17) == "adolescent"
    assert _age_tier(18) == "adult"
    assert _age_tier(45) == "adult"


# ---------------------------------------------------------------------------
# Create Family Unit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_family_unit(mock_db_pool):
    pool, conn = mock_db_pool
    from app.sse.family_engine import create_family_unit
    result = await create_family_unit("HEAD_USER", "The Smiths", pool)
    assert result["name"] == "The Smiths"
    assert result["family_id"].startswith("FAM_")
    assert conn.execute.call_count >= 2  # families INSERT + family_members INSERT


# ---------------------------------------------------------------------------
# Add Member — Age Gating
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_member_minor_requires_consent(mock_db_pool):
    pool, conn = mock_db_pool
    from app.sse.family_engine import add_family_member
    today = date.today()
    minor_dob = date(today.year - 10, today.month, today.day).isoformat()
    result = await add_family_member("FAM_ABC", "CHILD_1", "child", "Timmy",
                                     minor_dob, pool, consenting_parent_id=None)
    assert result.get("error"), "Minor without consent should return error"


@pytest.mark.asyncio
async def test_add_member_minor_with_consent(mock_db_pool):
    pool, conn = mock_db_pool
    from app.sse.family_engine import add_family_member
    today = date.today()
    minor_dob = date(today.year - 10, today.month, today.day).isoformat()
    result = await add_family_member("FAM_ABC", "CHILD_1", "child", "Timmy",
                                     minor_dob, pool, consenting_parent_id="PARENT_1")
    assert result.get("added") is True
    assert result.get("age_gated") is True


@pytest.mark.asyncio
async def test_add_member_adult_no_consent_needed(mock_db_pool):
    pool, conn = mock_db_pool
    from app.sse.family_engine import add_family_member
    today = date.today()
    adult_dob = date(today.year - 30, today.month, today.day).isoformat()
    result = await add_family_member("FAM_ABC", "ADULT_1", "spouse", "Jane",
                                     adult_dob, pool)
    assert result.get("added") is True
    assert result.get("age_gated") is False


# ---------------------------------------------------------------------------
# Age Transition (18th birthday)
# ---------------------------------------------------------------------------

def test_age_transition_at_18():
    from app.sse.family_engine import _compute_age, _age_tier
    today = date.today()
    just_turned_18 = date(today.year - 18, today.month, today.day)
    assert _compute_age(just_turned_18) == 18
    assert _age_tier(_compute_age(just_turned_18)) == "adult"
    still_17 = date(today.year - 18, today.month, today.day + 1) if today.day < 28 else date(today.year - 18, today.month + 1, 1) if today.month < 12 else date(today.year - 17, 1, 1)
    age_17 = _compute_age(still_17)
    assert _age_tier(age_17) in ("adolescent", "child")
