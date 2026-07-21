"""Little Nate Dispatch account auto opt-in helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_normalize_and_validate_email():
    from app.newsletter.opt_in import is_valid_email, normalize_email

    assert normalize_email("  Foo@Bar.COM ") == "foo@bar.com"
    assert is_valid_email("a@b.co") is True
    assert is_valid_email("not-an-email") is False
    assert is_valid_email("") is False


@pytest.mark.asyncio
async def test_ensure_active_subscriber_skips_invalid_without_db():
    from app.newsletter.opt_in import ensure_active_subscriber

    result = await ensure_active_subscriber(None, "bad")
    assert result["ok"] is False
    assert result["skipped_reason"] == "invalid_email"


def test_ws_dependent_creation_schedules_newsletter_opt_in():
    bridge = (ROOT / "backend/app/websocket/bridge_server.py").read_text(encoding="utf-8")
    idx = bridge.index("async def create_dependent_account")
    end = bridge.index("return True, \"DEPENDENT_CREATED\"", idx)
    block = bridge[idx:end]
    assert "schedule_account_opt_in" in block
    assert "account_signup_ws_" in block


def test_newsletter_agent_daily_account_opt_in_backfill():
    agent = (ROOT / "backend/app/services/newsletter_agent.py").read_text(encoding="utf-8")
    assert "opt_in_all_platform_users" in agent
    assert "_last_opt_in_date" in agent
