"""Unit tests for research_pseudonym + research_aggregator (Slice 5)."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.services import research_aggregator as agg
from app.services import research_pseudonym as rp
from app.services.research_pseudonym import ResearchKeyMissing


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("RESEARCH_HMAC_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_ALLOW_MISSING_KEY", raising=False)
    monkeypatch.delenv("ENABLE_RESEARCH_AGGREGATION", raising=False)
    yield


# ---------------------------------------------------------------------------
# pseudonymize
# ---------------------------------------------------------------------------


def test_pseudonymize_fails_closed_without_key():
    with pytest.raises(ResearchKeyMissing):
        rp.pseudonymize("alice")


def test_pseudonymize_relax_flag_allows_test_only_key(monkeypatch):
    monkeypatch.setenv("RESEARCH_ALLOW_MISSING_KEY", "1")
    p = rp.pseudonymize("alice")
    assert isinstance(p, str) and len(p) == 64


def test_pseudonymize_is_deterministic(monkeypatch):
    monkeypatch.setenv("RESEARCH_HMAC_KEY", "test-key-abc")
    a1 = rp.pseudonymize("alice")
    a2 = rp.pseudonymize("alice")
    assert a1 == a2
    assert len(a1) == 64


def test_pseudonymize_differs_across_users(monkeypatch):
    monkeypatch.setenv("RESEARCH_HMAC_KEY", "test-key-abc")
    assert rp.pseudonymize("alice") != rp.pseudonymize("bob")


def test_pseudonymize_rotates_when_key_changes(monkeypatch):
    monkeypatch.setenv("RESEARCH_HMAC_KEY", "key-one")
    a = rp.pseudonymize("alice")
    monkeypatch.setenv("RESEARCH_HMAC_KEY", "key-two")
    b = rp.pseudonymize("alice")
    assert a != b


def test_pseudonymize_none_returns_none(monkeypatch):
    monkeypatch.setenv("RESEARCH_HMAC_KEY", "k")
    assert rp.pseudonymize(None) is None


def test_pseudonymize_empty_string_returns_none(monkeypatch):
    monkeypatch.setenv("RESEARCH_HMAC_KEY", "k")
    assert rp.pseudonymize("") is None
    assert rp.pseudonymize("   ") is None


def test_pseudonymize_accepts_uuid(monkeypatch):
    monkeypatch.setenv("RESEARCH_HMAC_KEY", "k")
    u = UUID("12345678-1234-5678-1234-567812345678")
    p = rp.pseudonymize(u)
    assert isinstance(p, str) and len(p) == 64
    # Same UUID as string produces same pseudonym
    assert rp.pseudonymize(str(u)) == p


def test_pseudonymize_accepts_bytes(monkeypatch):
    monkeypatch.setenv("RESEARCH_HMAC_KEY", "k")
    p = rp.pseudonymize(b"alice")
    assert rp.pseudonymize("alice") == p


def test_pseudonymize_rejects_bad_types(monkeypatch):
    monkeypatch.setenv("RESEARCH_HMAC_KEY", "k")
    with pytest.raises(TypeError):
        rp.pseudonymize({"user_id": "alice"})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        rp.pseudonymize(42)  # type: ignore[arg-type]


def test_pseudonymize_strips_whitespace(monkeypatch):
    monkeypatch.setenv("RESEARCH_HMAC_KEY", "k")
    assert rp.pseudonymize("alice") == rp.pseudonymize("  alice  ")


def test_is_configured_reflects_env(monkeypatch):
    assert rp.is_configured() is False
    monkeypatch.setenv("RESEARCH_HMAC_KEY", "k")
    assert rp.is_configured() is True
    # Relax flag does not count as configured
    monkeypatch.delenv("RESEARCH_HMAC_KEY", raising=False)
    monkeypatch.setenv("RESEARCH_ALLOW_MISSING_KEY", "1")
    assert rp.is_configured() is False


# ---------------------------------------------------------------------------
# research_aggregator flag
# ---------------------------------------------------------------------------


def test_aggregator_disabled_by_default():
    assert agg.is_enabled() is False


@pytest.mark.parametrize("v", ["1", "true", "TRUE", "yes", "on"])
def test_aggregator_enabled_variants(monkeypatch, v):
    monkeypatch.setenv("ENABLE_RESEARCH_AGGREGATION", v)
    assert agg.is_enabled() is True


@pytest.mark.parametrize("v", ["0", "false", "no", "off", "maybe", ""])
def test_aggregator_disabled_variants(monkeypatch, v):
    monkeypatch.setenv("ENABLE_RESEARCH_AGGREGATION", v)
    assert agg.is_enabled() is False


@pytest.mark.asyncio
async def test_run_daily_aggregation_flag_off_is_noop():
    result = await agg.run_daily_aggregation(db_pool=None)
    assert result == {"status": "skipped", "reason": "flag off"}


@pytest.mark.asyncio
async def test_run_daily_aggregation_no_pool_when_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_RESEARCH_AGGREGATION", "1")
    result = await agg.run_daily_aggregation(db_pool=None)
    assert result == {"status": "skipped", "reason": "no db_pool"}
