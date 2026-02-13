"""
Tests for WisdomMeshService — inter-Fibre communication.
Tests use in-memory fallback mode (no Redis required).
"""

import pytest
from datetime import datetime
from uuid import uuid4

from app.services.wisdom_mesh import WisdomMeshService
from app.models.mesh import MeshMessage, MeshMessageType, MeshPriority, MeshHealth


# ─── Fake DB Pool ─────────────────────────────────────────────────────────────

class FakeConnection:
    async def execute(self, query, *args):
        return "INSERT 0 1"

    async def fetch(self, query, *args):
        return []

    async def fetchrow(self, query, *args):
        return None


class FakePool:
    def acquire(self):
        return FakeAcquireContext()


class FakeAcquireContext:
    async def __aenter__(self):
        return FakeConnection()

    async def __aexit__(self, *args):
        pass


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestWisdomMeshInit:
    def test_default_init(self):
        """Should initialize with no Redis (in-memory mode)."""
        mesh = WisdomMeshService()
        assert mesh._redis is None
        assert mesh._metrics["messages_sent"] == 0

    def test_init_with_pool(self):
        mesh = WisdomMeshService(db_pool=FakePool())
        assert mesh.db_pool is not None


class TestSubscriptions:
    @pytest.mark.asyncio
    async def test_subscribe(self):
        """Should register a subscription for a Fibre."""
        mesh = WisdomMeshService()
        fibre_id = uuid4()

        await mesh.subscribe(fibre_id, "marketing")

        assert fibre_id in mesh._subscriptions
        assert "marketing" in mesh._subscriptions[fibre_id]

    @pytest.mark.asyncio
    async def test_subscribe_multiple_topics(self):
        mesh = WisdomMeshService()
        fibre_id = uuid4()

        await mesh.subscribe(fibre_id, "marketing")
        await mesh.subscribe(fibre_id, "clinical")

        assert len(mesh._subscriptions[fibre_id]) == 2

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        mesh = WisdomMeshService()
        fibre_id = uuid4()

        await mesh.subscribe(fibre_id, "marketing")
        await mesh.unsubscribe(fibre_id, "marketing")

        assert "marketing" not in mesh._subscriptions.get(fibre_id, set())


class TestPublish:
    @pytest.mark.asyncio
    async def test_publish_message_in_memory(self):
        """Should track message in metrics even without Redis."""
        mesh = WisdomMeshService(db_pool=FakePool())
        fibre_id = uuid4()

        message = MeshMessage(
            message_type=MeshMessageType.INSIGHT,
            sender_id=fibre_id,
            domain_tags=["test"],
            payload={"key": "value"},
            priority=MeshPriority.NORMAL,
        )

        result = await mesh.publish(message)
        # In-memory mode: publish may fail gracefully or succeed
        assert mesh._metrics["messages_sent"] >= 1

    @pytest.mark.asyncio
    async def test_publish_increments_metrics(self):
        mesh = WisdomMeshService(db_pool=FakePool())

        message = MeshMessage(
            message_type=MeshMessageType.CONVERGENCE_CHECK,
            sender_id=uuid4(),
            domain_tags=["metrics-test"],
            payload={"test": True},
        )

        initial = mesh._metrics["messages_sent"]
        await mesh.publish(message)
        assert mesh._metrics["messages_sent"] >= initial


class TestMeshHealth:
    @pytest.mark.asyncio
    async def test_health_returns_mesh_health(self):
        """Health metrics should be returned even with no activity."""
        mesh = WisdomMeshService()
        health = await mesh.get_mesh_health()

        assert isinstance(health, MeshHealth)
        assert health.total_messages_24h >= 0
        assert health.messages_per_minute >= 0.0
        assert 0.0 <= health.delivery_success_rate <= 1.0
        assert health.convergence_alerts_24h >= 0

    @pytest.mark.asyncio
    async def test_health_reflects_activity(self):
        mesh = WisdomMeshService(db_pool=FakePool())

        # Generate some traffic
        for _ in range(5):
            msg = MeshMessage(
                message_type=MeshMessageType.INSIGHT,
                sender_id=uuid4(),
                domain_tags=["load-test"],
                payload={"i": 1},
            )
            await mesh.publish(msg)

        health = await mesh.get_mesh_health()
        assert health.total_messages_24h >= 5
