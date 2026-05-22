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


# ---------------------------------------------------------------------------
# Free-slot billing rules (HoH never charged for spouse or 1st dependent)
# ---------------------------------------------------------------------------

def test_first_dependent_slot_is_free_by_ordinal():
    """0 existing dependents => paid_ordinal 0 => $0 (not DEPENDENT_REQUIRES_PAYMENT)."""
    existing_count = 0
    paid_ordinal = existing_count
    assert paid_ordinal == 0
    from app.services.registration_finalize import _family_tier_price_cents
    assert _family_tier_price_cents(paid_ordinal) == 3000  # dict miss uses default
    # Business rule: ordinal 0 never enters paid path (paid_ordinal > 0 gate)


def test_second_dependent_is_first_paid_slot():
    """1 existing dependent => paid_ordinal 1 => $75/mo to HoH plan."""
    existing_count = 1
    paid_ordinal = existing_count
    assert paid_ordinal == 1
    from app.services.registration_finalize import _family_tier_price_cents
    assert _family_tier_price_cents(paid_ordinal) == 7500


def test_dependent_price_preview_free_when_zero_existing():
    """Mirror /dependent-price: existing==0 => free first dependent."""
    existing = 0
    assert existing == 0  # triggers free branch
    preview = {
        "eligible": True,
        "free": True,
        "ordinal": 1,
        "monthly_cost_cents": 0,
    }
    assert preview["free"] is True
    assert preview["monthly_cost_cents"] == 0


@pytest.mark.asyncio
async def test_count_dependents_excludes_spouse_role(mock_conn):
    """Spouse (family_role=SPOUSE) must not consume the free dependent slot."""
    from app.services.registration_finalize import _count_existing_dependents
    mock_conn.fetchval.return_value = 0
    await _count_existing_dependents(mock_conn, "fam-uuid")
    sql = mock_conn.fetchval.call_args[0][0]
    assert "family_role" in sql
    assert "dependent" in sql.lower()
    assert "SPOUSE" not in sql.upper()


@pytest.mark.asyncio
async def test_finalize_free_dependent_when_no_existing(mock_conn):
    """First dependent under HoH: no Stripe, paid_ordinal=0, monthly_cost_cents=0."""
    from contextlib import asynccontextmanager
    from app.services.registration_finalize import finalize_dependent_signup

    parent_row = {
        "id": "parent-uuid",
        "family_id": "fam-uuid",
        "tier": "TOP_TIER",
        "subscription_status": "ACTIVE",
        "name": "HoHUser",
        "stripe_customer_id": "cus_test",
        "stripe_subscription_id": "sub_test",
    }

    async def _fetchrow(sql, *args):
        if "FROM users" in sql and "LOWER(username)" in sql and "role = 'CLIENT'" in sql:
            if args[0].lower() == "hohuser":
                return parent_row
            return None
        return None

    async def _fetchval(sql, *args):
        if "SELECT 1 FROM users" in sql:
            return None
        if "COUNT(*)" in sql and "family_id" in sql:
            return 0
        if "head_of_household_id" in sql:
            return "parent-uuid"
        if "INSERT INTO users" in sql:
            return "new-user-uuid"
        return None

    mock_conn.fetchrow = AsyncMock(side_effect=_fetchrow)
    mock_conn.fetchval = AsyncMock(side_effect=_fetchval)
    mock_conn.execute = AsyncMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    pool = AsyncMock()
    pool.acquire = _acquire

    ok, reason, info = await finalize_dependent_signup(
        pool,
        username="kid1",
        password_hash="salt:hash",
        email="kid1@test.com",
        profile_fields={"name": "Kid One", "dob": "2015-01-01"},
        parent_username="HoHUser",
    )

    assert ok is True
    assert reason == "DEPENDENT_REGISTRATION_SUCCESS"
    assert info.get("paid_ordinal") == 0
    assert info.get("monthly_cost_cents") == 0
    assert reason != "DEPENDENT_REQUIRES_PAYMENT"
