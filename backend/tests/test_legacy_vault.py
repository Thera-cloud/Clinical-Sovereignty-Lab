"""
Tests for LegacyVault — transgenerational pattern storage and consent management.
"""

import pytest
from uuid import uuid4

from app.services.legacy_vault import LegacyVault


# ─── Helpers ───────────────────────────────────────────────────────────────────

def make_vault(fake_pool):
    return LegacyVault(db_pool=fake_pool)


# ─── Tests ─────────────────────────────────────────────────────────────────────

class TestLegacyVaultInit:
    def test_initialization(self, fake_pool):
        vault = make_vault(fake_pool)
        assert vault.db_pool is fake_pool
        assert vault.blob_storage is None
        assert isinstance(vault._consent_cache, dict)


class TestConsentCheckEmpty:
    @pytest.mark.asyncio
    async def test_check_consent_empty_db(self, fake_pool, fake_conn):
        """check_consent should return False when no consent record exists."""
        fake_conn._fetchrow_result = None

        vault = make_vault(fake_pool)
        result = await vault.check_consent(user_id=1, family_id=10)

        assert result is False


class TestGrantConsent:
    @pytest.mark.asyncio
    async def test_grant_consent(self, fake_pool, fake_conn):
        """grant_consent should execute INSERT and update the cache."""
        vault = make_vault(fake_pool)
        result = await vault.grant_consent(user_id=1, family_id=10)

        assert result["consented"] is True
        assert result["user_id"] == 1
        assert result["family_id"] == 10
        # Verify cache was updated
        assert vault._consent_cache[10][1] is True
        # Verify DB was called
        assert len(fake_conn._executed) >= 1


class TestWithdrawConsent:
    @pytest.mark.asyncio
    async def test_withdraw_consent(self, fake_pool, fake_conn):
        """withdraw_consent should execute INSERT and update the cache."""
        vault = make_vault(fake_pool)

        # First grant, then withdraw
        await vault.grant_consent(user_id=1, family_id=10)
        result = await vault.withdraw_consent(user_id=1, family_id=10)

        assert result["consented"] is False
        assert vault._consent_cache[10][1] is False


class TestGetVaultEntries:
    @pytest.mark.asyncio
    async def test_get_vault_entries_empty(self, fake_pool, fake_conn):
        """get_vault_entries should return empty list when no entries."""
        fake_conn._fetch_results = []

        vault = make_vault(fake_pool)
        entries = await vault.get_vault_entries(family_id=10)

        assert entries == []

    @pytest.mark.asyncio
    async def test_get_vault_entries_with_type(self, fake_pool, fake_conn):
        """get_vault_entries with entry_type filter should return empty list."""
        fake_conn._fetch_results = []

        vault = make_vault(fake_pool)
        entries = await vault.get_vault_entries(family_id=10, entry_type="inheritance_map")

        assert entries == []


class TestGetConsentedMembers:
    @pytest.mark.asyncio
    async def test_empty_consented_members(self, fake_pool, fake_conn):
        """get_consented_members should return empty list when no one consented."""
        fake_conn._fetch_results = []

        vault = make_vault(fake_pool)
        members = await vault.get_consented_members(family_id=10)

        assert members == []
