"""
Tests for FibreManager — Fibre lifecycle management.
"""

import pytest
from uuid import uuid4

from app.services.fibre_manager import FibreManager
from app.services.identity_chain import IdentityChainService
from app.models.fibre import FibreConfig, FibreResult, FibreType, FibreStatus, AutonomyLevel
from app.fibres.base_fibre import BaseFibre


# ─── Fake DB Pool ─────────────────────────────────────────────────────────────

class FakeConnection:
    def __init__(self):
        self._executed = []

    async def fetch(self, query, *args):
        return []

    async def fetchrow(self, query, *args):
        return None

    async def execute(self, query, *args):
        self._executed.append((query, args))
        return "INSERT 0 1"


class FakePool:
    def __init__(self):
        self._conn = FakeConnection()

    def acquire(self):
        return FakeAcquireContext(self._conn)


class FakeAcquireContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


# ─── Test Fibre Implementation ────────────────────────────────────────────────

class MockFibre(BaseFibre):
    """Minimal Fibre for testing."""

    async def _execute_impl(self, task):
        return FibreResult(
            task_id=task.task_id,
            fibre_id=self.fibre_id,
            success=True,
            output={"status": "ok"},
        )

    async def observe(self):
        return {"fibre_id": str(self.fibre_id), "status": "observing"}


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestFibreManagerInit:
    def test_initialization(self):
        pool = FakePool()
        mgr = FibreManager(db_pool=pool)
        assert mgr.db_pool is pool
        assert len(mgr._active_fibres) == 0
        assert len(mgr._fibre_registry) == 0


class TestFibreTypeRegistration:
    def test_register_fibre_type(self):
        pool = FakePool()
        mgr = FibreManager(db_pool=pool)
        mgr.register_fibre_type(FibreType.CAMPAIGN, MockFibre)

        assert FibreType.CAMPAIGN in mgr._fibre_registry
        assert mgr._fibre_registry[FibreType.CAMPAIGN] is MockFibre


class TestSpawn:
    @pytest.mark.asyncio
    async def test_spawn_without_identity_service(self):
        """Should spawn a Fibre even without identity service."""
        pool = FakePool()
        mgr = FibreManager(db_pool=pool)
        mgr.register_fibre_type(FibreType.CAMPAIGN, MockFibre)

        config = FibreConfig(
            fibre_type=FibreType.CAMPAIGN,
            name="Test Campaign Fibre",
            domain_tags=["test"],
        )

        fibre = await mgr.spawn(config, spawn_reason="test")
        assert fibre is not None
        assert fibre.name == "Test Campaign Fibre"
        assert fibre.fibre_type == FibreType.CAMPAIGN
        assert fibre.db_pool is pool

    @pytest.mark.asyncio
    async def test_spawn_with_identity_service(self):
        """Should spawn a Fibre with signed identity."""
        pool = FakePool()
        identity = IdentityChainService()
        identity.initialize_master_key()

        mgr = FibreManager(db_pool=pool, identity_service=identity)
        mgr.register_fibre_type(FibreType.CAMPAIGN, MockFibre)

        config = FibreConfig(
            fibre_type=FibreType.CAMPAIGN,
            name="Signed Fibre",
        )

        fibre = await mgr.spawn(config, spawn_reason="identity test")
        assert fibre is not None

    @pytest.mark.asyncio
    async def test_spawn_unregistered_type_raises(self):
        """Should raise when trying to spawn an unregistered type."""
        pool = FakePool()
        mgr = FibreManager(db_pool=pool)

        config = FibreConfig(
            fibre_type=FibreType.CAMPAIGN,
            name="Unregistered",
        )

        with pytest.raises(Exception):
            await mgr.spawn(config)


class TestInventory:
    @pytest.mark.asyncio
    async def test_inventory_empty(self):
        pool = FakePool()
        mgr = FibreManager(db_pool=pool)
        items = await mgr.inventory()
        assert items == []

    @pytest.mark.asyncio
    async def test_inventory_after_spawn(self):
        pool = FakePool()
        mgr = FibreManager(db_pool=pool)
        mgr.register_fibre_type(FibreType.CAMPAIGN, MockFibre)

        config = FibreConfig(
            fibre_type=FibreType.CAMPAIGN,
            name="Inventory Test",
        )
        await mgr.spawn(config)

        items = await mgr.inventory()
        assert len(items) == 1
        assert items[0]["name"] == "Inventory Test"
        assert items[0]["type"] == "campaign"


class TestGetFibre:
    @pytest.mark.asyncio
    async def test_get_nonexistent_fibre(self):
        pool = FakePool()
        mgr = FibreManager(db_pool=pool)
        result = mgr.get_fibre(uuid4())
        assert result is None
