"""Live API — not stale token_expiry — gates social token SMS/email."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.token_renewal_agent import TokenRenewalAgent, admin_alert_required


def test_admin_alert_required_false_when_live():
    assert admin_alert_required(refresh_ok=False, live_ok=True) is False
    assert admin_alert_required(refresh_ok=True, live_ok=False) is False
    assert admin_alert_required(refresh_ok=True, live_ok=True) is False


def test_admin_alert_required_true_only_when_dead():
    assert admin_alert_required(refresh_ok=False, live_ok=False) is True


def test_sweep_skips_sms_when_facebook_still_live():
    agent = TokenRenewalAgent(db_pool=MagicMock())
    agent._notify_admin = AsyncMock()
    agent._seed_cooldowns_from_db = AsyncMock()
    agent._detect_failing_platforms = AsyncMock(
        return_value={"facebook": {"status": "connected"}}
    )
    agent._log_activity = AsyncMock()
    agent._retry_failed_posts = AsyncMock()
    agent._check_pending_resolutions = AsyncMock()
    agent._on_renewal_success = AsyncMock()

    adapter = MagicMock()
    adapter.refresh_token = AsyncMock(return_value=False)
    adapter.authenticate = AsyncMock(return_value=True)
    adapter._heal_past_token_expiry = AsyncMock()

    with patch(
        "app.services.platforms.get_all_adapters",
        return_value={"facebook": adapter},
    ):
        asyncio.run(agent._sweep())

    agent._notify_admin.assert_not_called()
    adapter._heal_past_token_expiry.assert_awaited()
    agent._log_activity.assert_awaited()


def test_sweep_sms_when_live_auth_fails():
    agent = TokenRenewalAgent(db_pool=MagicMock())
    agent._notify_admin = AsyncMock()
    agent._seed_cooldowns_from_db = AsyncMock()
    agent._detect_failing_platforms = AsyncMock(
        return_value={"x": {"status": "expired"}}
    )
    agent._log_activity = AsyncMock()
    agent._retry_failed_posts = AsyncMock()
    agent._check_pending_resolutions = AsyncMock()

    adapter = MagicMock()
    adapter.refresh_token = AsyncMock(return_value=False)
    adapter.authenticate = AsyncMock(return_value=False)
    adapter._heal_past_token_expiry = AsyncMock()

    with patch(
        "app.services.platforms.get_all_adapters",
        return_value={"x": adapter},
    ):
        asyncio.run(agent._sweep())

    agent._notify_admin.assert_awaited()
