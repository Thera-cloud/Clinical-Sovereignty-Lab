"""Tap-to-confirm token hashing, HTML, and refund reverse_transfer."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.session_confirm import (
    confirm_html,
    confirm_url,
    consume_confirm_token,
    hash_confirm_token,
    mint_raw_token,
)
from app.services.session_invoice_repay import invoice_owned_by_customer
from app.services.session_booking_billing import create_session_refund


def test_hash_confirm_token_is_stable():
    a = hash_confirm_token("abc")
    b = hash_confirm_token("abc")
    assert a == b
    assert a != hash_confirm_token("abd")
    assert len(a) == 64


def test_mint_raw_token_is_urlsafe_length():
    raw = mint_raw_token()
    assert len(raw) >= 32
    assert "/" not in raw


def test_confirm_url_uses_public_api(monkeypatch):
    monkeypatch.setenv("API_PUBLIC_BASE", "https://api.sovereignsanctuary.net")
    url = confirm_url("tok_abc")
    assert url.startswith("https://api.sovereignsanctuary.net/api/billing/session-confirm?t=")


def test_confirm_html_success_and_expired():
    ok = confirm_html(ok=True, when="Monday 2pm")
    assert "Appointment confirmed" in ok
    assert "#C9A962" in ok
    expired = confirm_html(ok=False, expired=True)
    assert "Link expired" in expired
    assert "#EF4444" in expired


def test_invoice_owned_by_customer_rejects_other_cus():
    inv = SimpleNamespace(customer="cus_owner")
    assert invoice_owned_by_customer(inv, "cus_owner") is True
    assert invoice_owned_by_customer(inv, "cus_other") is False
    assert invoice_owned_by_customer(inv, "") is False


def test_create_session_refund_sets_reverse_transfer():
    captured = {}

    class _Refund:
        @staticmethod
        def create(**kw):
            captured.update(kw)
            return SimpleNamespace(id="re_1", amount=9000)

    refund = create_session_refund(SimpleNamespace(Refund=_Refund), "pi_x")
    assert refund.id == "re_1"
    assert captured["payment_intent"] == "pi_x"
    assert captured["reverse_transfer"] is True
    assert captured["refund_application_fee"] is True
    assert "amount" not in captured


def test_create_session_refund_falls_back_without_transfer():
    calls = []

    class _Refund:
        @staticmethod
        def create(**kw):
            calls.append(kw)
            if kw.get("reverse_transfer"):
                raise RuntimeError("no transfer on this charge")
            return SimpleNamespace(id="re_plain", amount=5000)

    refund = create_session_refund(SimpleNamespace(Refund=_Refund), "pi_y", amount_cents=5000)
    assert refund.id == "re_plain"
    assert len(calls) == 2
    assert calls[1] == {"payment_intent": "pi_y", "amount": 5000}


@pytest.mark.asyncio
async def test_consume_confirm_token_marks_confirmed():
    raw = mint_raw_token()
    th = hash_confirm_token(raw)
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "id": "11111111-1111-1111-1111-111111111111",
        "session_id": "SES_C",
        "client_id": "CLIENT_X",
        "coach_id": "COACH_N",
        "client_name": "Pat",
        "client_confirmed_at": None,
        "confirm_token_expires_at": None,
        "status": "scheduled",
        "scheduled_at": None,
        "coach_email": "coach@example.com",
        "coach_name": "Coach",
    })
    conn.execute = AsyncMock(return_value="UPDATE 1")
    out = await consume_confirm_token(conn, raw)
    assert out["ok"] is True
    assert out["session_id"] == "SES_C"
    assert out["already"] is False
    args0 = conn.fetchrow.await_args.args[1]
    assert args0 == th
