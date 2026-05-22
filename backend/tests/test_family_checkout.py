"""Tests for family checkout fix — dependent pricing, slot counting, tier env keys.

Only imports from app.services.registration_finalize (lightweight) to avoid
numpy crash on macOS Python 3.9. Bridge and checkout router tests run inside
Docker where numpy is stable.
"""

import pytest
from unittest.mock import AsyncMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_conn():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()
    return conn


# ---------------------------------------------------------------------------
# _family_tier_price_cents  (pure function)
# ---------------------------------------------------------------------------

def test_family_tier_first_paid_is_75():
    """1st paid dependent = $75/mo (7500 cents)."""
    from app.services.registration_finalize import _family_tier_price_cents
    assert _family_tier_price_cents(1) == 7500


def test_family_tier_second_paid_is_60():
    """2nd paid dependent = $60/mo."""
    from app.services.registration_finalize import _family_tier_price_cents
    assert _family_tier_price_cents(2) == 6000


def test_family_tier_third_paid_is_45():
    """3rd paid dependent = $45/mo."""
    from app.services.registration_finalize import _family_tier_price_cents
    assert _family_tier_price_cents(3) == 4500


def test_family_tier_fourth_plus_is_30():
    """4th+ paid dependent = $30/mo (floor)."""
    from app.services.registration_finalize import _family_tier_price_cents
    assert _family_tier_price_cents(4) == 3000
    assert _family_tier_price_cents(10) == 3000


# ---------------------------------------------------------------------------
# _family_tier_env_key
# ---------------------------------------------------------------------------

def test_family_tier_env_key_ordinals():
    from app.services.registration_finalize import _family_tier_env_key
    assert _family_tier_env_key(1) == "STRIPE_PRICE_FAMILY_TIER_1"
    assert _family_tier_env_key(2) == "STRIPE_PRICE_FAMILY_TIER_2"
    assert _family_tier_env_key(3) == "STRIPE_PRICE_FAMILY_TIER_3"
    assert _family_tier_env_key(4) == "STRIPE_PRICE_FAMILY_TIER_4"


def test_family_tier_env_key_clamps_high_ordinals():
    """Ordinals > 4 clamp to tier 4."""
    from app.services.registration_finalize import _family_tier_env_key
    assert _family_tier_env_key(99) == "STRIPE_PRICE_FAMILY_TIER_4"


# ---------------------------------------------------------------------------
# _count_existing_dependents (async, mocked DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_dependents_returns_count(mock_conn):
    from app.services.registration_finalize import _count_existing_dependents
    mock_conn.fetchval.return_value = 3
    count = await _count_existing_dependents(mock_conn, "fam-uuid-123")
    assert count == 3


@pytest.mark.asyncio
async def test_count_dependents_returns_zero_on_null(mock_conn):
    from app.services.registration_finalize import _count_existing_dependents
    mock_conn.fetchval.return_value = None
    count = await _count_existing_dependents(mock_conn, "fam-uuid-empty")
    assert count == 0


@pytest.mark.asyncio
async def test_count_dependents_query_checks_tier_and_family_role(mock_conn):
    """SQL must check both tier='DEPENDENT' and family_role='dependent'."""
    from app.services.registration_finalize import _count_existing_dependents
    mock_conn.fetchval.return_value = 0
    await _count_existing_dependents(mock_conn, "fam-uuid-x")
    sql = mock_conn.fetchval.call_args[0][0]
    assert "tier = 'DEPENDENT'" in sql
    assert "family_role" in sql


# ---------------------------------------------------------------------------
# Dependent-eligible parent tiers (set membership)
# ---------------------------------------------------------------------------

def test_eligible_parent_tiers_include_sovereign():
    from app.services.registration_finalize import DEPENDENT_ELIGIBLE_PARENT_TIERS
    assert "TOP_TIER" in DEPENDENT_ELIGIBLE_PARENT_TIERS


def test_eligible_parent_tiers_exclude_trial():
    from app.services.registration_finalize import DEPENDENT_ELIGIBLE_PARENT_TIERS
    assert "TRIAL" not in DEPENDENT_ELIGIBLE_PARENT_TIERS
    assert "STANDARD" not in DEPENDENT_ELIGIBLE_PARENT_TIERS


# ---------------------------------------------------------------------------
# Pricing constants consistency
# ---------------------------------------------------------------------------

def test_pricing_constants_match():
    """FAMILY_TIER_PRICE_CENTS has 3 explicit tiers, default is lower."""
    from app.services.registration_finalize import (
        FAMILY_TIER_PRICE_CENTS,
        FAMILY_TIER_PRICE_DEFAULT_CENTS,
    )
    assert len(FAMILY_TIER_PRICE_CENTS) == 3
    for v in FAMILY_TIER_PRICE_CENTS.values():
        assert v > FAMILY_TIER_PRICE_DEFAULT_CENTS
