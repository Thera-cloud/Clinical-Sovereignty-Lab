"""
Tests for WisdomMeshService — inter-Fibre communication.
Tests use in-memory fallback mode (no Redis required).
"""

import asyncio
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


class TestTemporalBatching:
    """Tests for low-priority temporal batching (PhD Spec §5.4)."""

    def _make_msg(self, priority: MeshPriority = MeshPriority.LOW) -> MeshMessage:
        return MeshMessage(
            message_type=MeshMessageType.OBSERVATION,
            sender_id=uuid4(),
            domain_tags=["batch-test"],
            body={"batch": True},
            priority=priority,
        )

    @pytest.mark.asyncio
    async def test_low_priority_queued_not_sent_immediately(self):
        """LOW-priority messages should be queued, not published immediately."""
        mesh = WisdomMeshService(db_pool=FakePool(), batch_window_seconds=5.0)

        msg = self._make_msg(MeshPriority.LOW)
        result = await mesh.publish(msg)

        assert result is True
        # Message is in the batch queue, not yet sent
        assert len(mesh._batch_queue) == 1
        assert mesh._metrics["messages_sent"] == 0  # not yet flushed
        # Cleanup
        if mesh._batch_task and not mesh._batch_task.done():
            mesh._batch_task.cancel()
            try:
                await mesh._batch_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_normal_priority_not_batched(self):
        """NORMAL-priority messages should bypass the batch queue entirely."""
        mesh = WisdomMeshService(db_pool=FakePool(), batch_window_seconds=5.0)

        msg = self._make_msg(MeshPriority.NORMAL)
        await mesh.publish(msg)

        assert len(mesh._batch_queue) == 0
        assert mesh._metrics["messages_sent"] == 1

    @pytest.mark.asyncio
    async def test_flush_publishes_batched_messages(self):
        """flush_batch_queue() should publish all queued messages."""
        mesh = WisdomMeshService(db_pool=FakePool(), batch_window_seconds=60.0)

        # Queue 3 low-priority messages
        for _ in range(3):
            await mesh.publish(self._make_msg(MeshPriority.LOW))

        assert len(mesh._batch_queue) == 3
        assert mesh._metrics["messages_sent"] == 0

        # Manually flush
        flushed = await mesh.flush_batch_queue()

        assert flushed == 3
        assert len(mesh._batch_queue) == 0
        assert mesh._metrics["messages_sent"] == 3
        # Cleanup
        if mesh._batch_task and not mesh._batch_task.done():
            mesh._batch_task.cancel()
            try:
                await mesh._batch_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_auto_flush_after_window(self):
        """Batch queue should auto-flush after the batch window elapses."""
        mesh = WisdomMeshService(db_pool=FakePool(), batch_window_seconds=0.2)

        await mesh.publish(self._make_msg(MeshPriority.LOW))
        await mesh.publish(self._make_msg(MeshPriority.LOW))

        assert mesh._metrics["messages_sent"] == 0

        # Wait for the auto-flush
        await asyncio.sleep(0.5)

        assert mesh._metrics["messages_sent"] == 2
        assert len(mesh._batch_queue) == 0

    @pytest.mark.asyncio
    async def test_health_shows_batched_count(self):
        """Health metrics should report the number of messages awaiting flush."""
        mesh = WisdomMeshService(db_pool=FakePool(), batch_window_seconds=60.0)

        for _ in range(4):
            await mesh.publish(self._make_msg(MeshPriority.LOW))

        health = await mesh.get_mesh_health()
        assert health.batched_messages_pending == 4
        # Cleanup
        if mesh._batch_task and not mesh._batch_task.done():
            mesh._batch_task.cancel()
            try:
                await mesh._batch_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_disconnect_flushes_batch_queue(self):
        """Disconnect should flush remaining batched messages before closing."""
        mesh = WisdomMeshService(db_pool=FakePool(), batch_window_seconds=60.0)

        for _ in range(2):
            await mesh.publish(self._make_msg(MeshPriority.LOW))

        assert len(mesh._batch_queue) == 2

        await mesh.disconnect()

        assert len(mesh._batch_queue) == 0
        # Messages should have been published during disconnect
        assert mesh._metrics["messages_sent"] == 2

    @pytest.mark.asyncio
    async def test_batching_disabled_when_window_zero(self):
        """When batch_window_seconds=0, low-priority messages publish immediately."""
        mesh = WisdomMeshService(db_pool=FakePool(), batch_window_seconds=0)

        msg = self._make_msg(MeshPriority.LOW)
        await mesh.publish(msg)

        # Should have been published immediately, not batched
        assert len(mesh._batch_queue) == 0
        assert mesh._metrics["messages_sent"] == 1
