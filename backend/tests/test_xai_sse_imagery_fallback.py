"""SSE Grok Imagine credit block → Gemini fallback + xAI billing helpers."""
from __future__ import annotations

import pytest


def test_is_credit_or_auth_block_detects_prod_error():
    from app.sse.infrastructure.grok_imagine_client import _is_credit_or_auth_block

    msg = (
        'Grok Imagine 403: {"code":"permission-denied","error":"Your team '
        "06ee7605-a4a7-4b65-be59-c639f0168efd has either used all available credits "
        'or reached its monthly spending limit."}'
    )
    assert _is_credit_or_auth_block(msg) is True
    assert _is_credit_or_auth_block("Grok Imagine 429: rate limit") is False
    assert _is_credit_or_auth_block("content moderation") is False


def test_cents_to_usd_prepaid_sign():
    from app.sse.infrastructure.xai_billing import _cents_to_usd

    assert _cents_to_usd("-2317") == 23.17
    assert _cents_to_usd("183") == 1.83
    assert _cents_to_usd(None) is None


@pytest.mark.asyncio
async def test_generate_image_falls_back_to_gemini_on_credit_403(monkeypatch):
    from app.sse.infrastructure import grok_imagine_client as client

    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("GEMINI_API_KEY", "gem-test")
    monkeypatch.delenv("XAI_FALLBACK_KEY", raising=False)

    async def boom_imagine(_key, _payload):
        raise RuntimeError(
            'Grok Imagine 403: {"code":"permission-denied","error":'
            '"used all available credits or reached its monthly spending limit"}'
        )

    async def fake_gemini(prompt, source_image_url=None):
        return b"\x89PNG\r\n\x1a\n" + b"0" * 600

    monkeypatch.setattr(client, "_imagine_with_key", boom_imagine)
    monkeypatch.setattr(client, "_gemini_image_fallback", fake_gemini)

    out = await client.generate_image("a quiet path through trees")
    assert out.startswith(b"\x89PNG")
    assert len(out) >= 600


@pytest.mark.asyncio
async def test_fetch_prepaid_balance_unconfigured(monkeypatch):
    from app.sse.infrastructure import xai_billing

    monkeypatch.delenv("XAI_MANAGEMENT_KEY", raising=False)
    monkeypatch.delenv("XAI_MGMT_KEY", raising=False)
    monkeypatch.delenv("XAI_TEAM_ID", raising=False)

    result = await xai_billing.fetch_prepaid_balance()
    assert result["ok"] is False
    assert result["configured"] is False
