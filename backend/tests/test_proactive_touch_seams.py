"""Seam tests for proactive_touch_policy (Phase 0) — offline mocks."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.proactive_touch_policy import PolicyDecision, can_send_proactive_touch


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
async def test_policy_disabled_allows(mock_pool):
    pool, _ = mock_pool
    with patch.dict("os.environ", {"ENABLE_PROACTIVE_TOUCH_POLICY": "false"}):
        d = await can_send_proactive_touch(pool, "hw_abc", source="commitment")
    assert d.allowed is True
    assert d.reason == "policy_disabled"


@pytest.mark.asyncio
async def test_mixed_identity_si_suppression(mock_pool):
    """Gate called with hardware_id must still resolve username for SI check."""
    pool, conn = mock_pool
    conn.fetchrow.side_effect = [
        {
            "username": "client1",
            "hardware_id": "HW_CLIENT1",
            "role": "CLIENT",
            "tier": "STANDARD",
            "profile_data": {"proactive_presence_consent": True, "timezone": "UTC"},
        },
        True,  # SI row
    ]
    with patch.dict(
        "os.environ",
        {"ENABLE_PROACTIVE_TOUCH_POLICY": "true", "SI_TOUCH_SUPPRESSION_HOURS": "24"},
    ):
        with patch(
            "app.services._identity_resolver.resolve_username",
            AsyncMock(return_value="client1"),
        ):
            d = await can_send_proactive_touch(
                pool, "HW_CLIENT1", source="commitment", channel_pref="email"
            )
    assert d.allowed is False
    assert d.reason == "skipped_si_window"


@pytest.mark.asyncio
async def test_trial_user_denied(mock_pool):
    pool, conn = mock_pool
    conn.fetchrow.return_value = {
        "username": "trial_user",
        "hardware_id": "HW_TRIAL",
        "role": "CLIENT",
        "tier": "public_trial",
        "profile_data": {"proactive_presence_consent": True},
    }
    with patch.dict("os.environ", {"ENABLE_PROACTIVE_TOUCH_POLICY": "true"}):
        with patch(
            "app.services._identity_resolver.resolve_username",
            AsyncMock(return_value="trial_user"),
        ):
            d = await can_send_proactive_touch(pool, "HW_TRIAL", source="nudge")
    assert d.allowed is False
    assert d.reason == "skipped_trial"


@pytest.mark.asyncio
async def test_consent_never_set_denies(mock_pool):
    """Account that never wrote proactive_presence_consent at all (key absent,
    not False) must be denied — default-deny, not default-allow, on missing consent."""
    pool, conn = mock_pool
    user_row = {
        "username": "never_touched_consent",
        "hardware_id": "HW_NEVER_TOUCHED",
        "role": "CLIENT",
        "tier": "STANDARD",
        "profile_data": {"timezone": "UTC"},  # no "proactive_presence_consent" key at all
    }
    conn.fetchrow = AsyncMock(side_effect=[user_row, None])
    with patch.dict("os.environ", {"ENABLE_PROACTIVE_TOUCH_POLICY": "true"}):
        with patch(
            "app.services._identity_resolver.resolve_username",
            AsyncMock(return_value="never_touched_consent"),
        ):
            d = await can_send_proactive_touch(
                pool, "HW_NEVER_TOUCHED", source="commitment"
            )
    assert d.allowed is False
    assert d.reason == "skipped_consent"
    assert "proactive_presence_consent" not in user_row["profile_data"]


@pytest.mark.asyncio
async def test_sensitive_in_app_only(mock_pool):
    pool, conn = mock_pool
    user_row = {
        "username": "client1",
        "hardware_id": "HW1",
        "role": "CLIENT",
        "tier": "STANDARD",
        "profile_data": {"proactive_presence_consent": True, "timezone": "UTC"},
    }
    conn.fetchrow = AsyncMock(side_effect=[user_row, None])
    conn.fetchval.return_value = 0
    with patch.dict("os.environ", {"ENABLE_PROACTIVE_TOUCH_POLICY": "true"}):
        with patch(
            "app.services._identity_resolver.resolve_username",
            AsyncMock(return_value="client1"),
        ):
            with patch(
                "app.services.proactive_touch_policy._quiet_hours",
                return_value=(__import__("datetime").time(0, 0), __import__("datetime").time(23, 59)),
            ):
                d = await can_send_proactive_touch(
                    pool,
                    "HW1",
                    source="commitment",
                    sensitivity="sensitive",
                )
    assert d.allowed is False
    assert d.reason == "skipped_sensitive"
