from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.stripe_integration import StripeWebhookHandler


class _FakeDB:
    def __init__(self, row):
        self._row = row
        self.exec_calls = []

    async def fetchrow(self, query, *args):
        if "FROM pending_signups" in query and "status = 'pending'" in query:
            return self._row
        return None

    async def fetchval(self, query, *args):
        if "SELECT status FROM pending_signups" in query:
            return "pending"
        if "SELECT id FROM users WHERE username" in query:
            return "00000000-0000-0000-0000-000000000001"
        return None

    async def execute(self, query, *args):
        self.exec_calls.append((query, args))
        return "OK"


@pytest.mark.asyncio
async def test_pending_signup_triggers_bridge_user_reload(monkeypatch):
    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "role": "CLIENT",
        "username": "longra",
        "password_hash": "salt:hash",
        "email": "rlong6767@gmail.com",
        "payload": {"name": "Ryan Long"},
        "tier": "TOP_TIER",
        "selected_dojos": [],
        "discount_code": None,
    }
    db = _FakeDB(row)
    handler = StripeWebhookHandler(db)

    async def _fake_finalize_signup(*_args, **_kwargs):
        return True, "REGISTRATION_SUCCESS"

    monkeypatch.setattr(
        "app.services.registration_finalize.finalize_signup",
        _fake_finalize_signup,
    )
    handler._send_support_paid_registration_notice = AsyncMock()
    handler._send_support_trial_started_notice = AsyncMock()
    handler._send_registration_receipt = AsyncMock()
    handler._notify_bridge_reload = AsyncMock()

    await handler._handle_pending_signup(
        {"id": "cs_test_123", "customer": "cus_test_123", "subscription": None, "amount_total": 14900, "mode": "subscription"},
        "11111111-1111-1111-1111-111111111111",
        "evt_test_123",
    )

    handler._notify_bridge_reload.assert_awaited_once_with("longra")
    assert any("status='completed'" in q for q, _ in db.exec_calls)


@pytest.mark.asyncio
async def test_pending_dependent_signup_triggers_bridge_user_reload(monkeypatch):
    row = {
        "id": "22222222-2222-2222-2222-222222222222",
        "role": "CLIENT",
        "username": "lana_long",
        "password_hash": "salt:hash",
        "email": "lana@example.com",
        "payload": {
            "name": "Lana Long",
            "signup_type": "dependent",
            "parent_username": "longra",
            "paid_ordinal": 1,
            "monthly_cost_cents": 7500,
        },
        "tier": "DEPENDENT",
        "selected_dojos": [],
        "discount_code": None,
    }
    db = _FakeDB(row)
    handler = StripeWebhookHandler(db)

    async def _fake_finalize_paid_dependent_signup(*_args, **_kwargs):
        return True, "DEPENDENT_PAID_REGISTRATION_SUCCESS", {"user_id": "u1"}

    monkeypatch.setattr(
        "app.services.registration_finalize.finalize_paid_dependent_signup",
        _fake_finalize_paid_dependent_signup,
    )
    handler._send_support_paid_registration_notice = AsyncMock()
    handler._send_support_trial_started_notice = AsyncMock()
    handler._send_registration_receipt = AsyncMock()
    handler._notify_bridge_reload = AsyncMock()

    await handler._handle_pending_signup(
        {"id": "cs_test_dep_123", "customer": "cus_test_dep_123", "subscription": "sub_dep_123", "amount_total": 7500, "mode": "subscription"},
        "22222222-2222-2222-2222-222222222222",
        "evt_test_dep_123",
    )

    handler._notify_bridge_reload.assert_awaited_once_with("lana_long")
    assert any("status='completed'" in q for q, _ in db.exec_calls)
