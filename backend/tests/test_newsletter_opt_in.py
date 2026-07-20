"""Little Nate Dispatch account auto opt-in helpers."""
from __future__ import annotations


def test_normalize_and_validate_email():
    from app.newsletter.opt_in import is_valid_email, normalize_email

    assert normalize_email("  Foo@Bar.COM ") == "foo@bar.com"
    assert is_valid_email("a@b.co") is True
    assert is_valid_email("not-an-email") is False
    assert is_valid_email("") is False


import pytest


@pytest.mark.asyncio
async def test_ensure_active_subscriber_skips_invalid_without_db():
    from app.newsletter.opt_in import ensure_active_subscriber

    result = await ensure_active_subscriber(None, "bad")
    assert result["ok"] is False
    assert result["skipped_reason"] == "invalid_email"
