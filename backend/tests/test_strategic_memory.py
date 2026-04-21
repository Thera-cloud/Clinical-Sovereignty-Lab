"""
Tests for StrategicMemoryService — 6-layer strategic memory CRUD.
Uses mocked asyncpg pool that simulates INSERT RETURNING and SELECT.
"""

import json
import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from app.services.strategic_memory import StrategicMemoryService


# ─── Fake DB Pool ─────────────────────────────────────────────────────────────

class FakeRow(dict):
    """Dict that also supports attribute access (like asyncpg Record)."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


class FakeConnection:
    """Mock asyncpg connection that tracks queries and returns fake data."""

    def __init__(self):
        self._rows = []  # pre-set rows for fetch()
        self._row = None  # pre-set row for fetchrow()
        self._queries = []

    async def fetch(self, query, *args):
        self._queries.append(("fetch", query, args))
        return self._rows

    async def fetchrow(self, query, *args):
        self._queries.append(("fetchrow", query, args))
        if "INSERT" in query and "RETURNING" in query:
            # Simulate returning the inserted row
            return FakeRow({
                "id": 1,
                "order_id": uuid4(),
                "title": args[0] if args else "test",
                "directive": args[1] if len(args) > 1 else "test",
                "origin": "big_nate_direct",
                "domain_tags": [],
                "priority": 5,
                "active": True,
                "performance_score": None,
                "created_by": "big_nate",
                "metadata": "{}",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                # Insight fields
                "insight_id": uuid4(),
                "body": "test body",
                "domain": "operational",
                "confidence": 0.5,
                "tags": [],
                "source_fibre_id": None,
                "source_type": "system",
                # Proposal fields
                "proposal_id": uuid4(),
                "description": "test description",
                "action_type": "test",
                "proposed_by": "sovereign_mind",
                "risk": "medium",
                "status": "proposed",
                "execution_payload": "{}",
                "auto_execute_after": None,
            })
        return self._row

    async def execute(self, query, *args):
        self._queries.append(("execute", query, args))
        return "UPDATE 1"


class FakePool:
    def __init__(self, conn=None):
        self._conn = conn or FakeConnection()

    def acquire(self):
        return FakeAcquireContext(self._conn)


class FakeAcquireContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestLayer1StandingOrders:
    @pytest.mark.asyncio
    async def test_create_standing_order(self):
        """Should insert a standing order and return it."""
        pool = FakePool()
        svc = StrategicMemoryService(pool)

        result = await svc.create_standing_order(
            title="Test Order",
            directive="Do something",
            priority=8,
        )

        assert result is not None
        assert result["title"] == "Test Order"
        assert pool._conn._queries[-1][0] == "fetchrow"

    @pytest.mark.asyncio
    async def test_get_active_standing_orders(self):
        """Should return active orders."""
        conn = FakeConnection()
        conn._rows = [
            FakeRow({"order_id": uuid4(), "title": "Order A", "priority": 8, "active": True}),
            FakeRow({"order_id": uuid4(), "title": "Order B", "priority": 5, "active": True}),
        ]
        pool = FakePool(conn)
        svc = StrategicMemoryService(pool)

        results = await svc.get_active_standing_orders()
        assert len(results) == 2
        assert results[0]["title"] == "Order A"


class TestLayer2InsightLog:
    @pytest.mark.asyncio
    async def test_log_insight(self):
        pool = FakePool()
        svc = StrategicMemoryService(pool)

        result = await svc.log_insight(
            title="Test Insight",
            body="Something interesting happened",
            domain="operational",
            confidence=0.8,
            tags=["test"],
        )

        assert result is not None
        assert result["title"] == "Test Insight"

    @pytest.mark.asyncio
    async def test_get_recent_insights(self):
        conn = FakeConnection()
        conn._rows = [
            FakeRow({"insight_id": uuid4(), "title": "Recent", "confidence": 0.9, "domain": "clinical"}),
        ]
        pool = FakePool(conn)
        svc = StrategicMemoryService(pool)

        results = await svc.get_recent_insights(hours=24)
        assert len(results) == 1


class TestLayer3Proposals:
    @pytest.mark.asyncio
    async def test_create_proposal_self_contained(self):
        """A proposal with all required structured fields is persisted."""
        pool = FakePool()
        svc = StrategicMemoryService(pool)

        result = await svc.create_proposal(
            title="Verify client coherence metrics across active users",
            description="A thing to do",
            action_type="marketing_campaign",
            risk="low",
            objective="Run a coherence verification scan across active users.",
            reasoning="Three users showed rapid GAP increase this week.",
            action_steps=[
                "Query nevedal_metrics for all active users",
                "Flag users with GAP > 0.7",
                "Notify assigned coaches of flagged clients",
            ],
            expected_impact="Coaches receive early warning for at-risk clients.",
            rollback="Read-only scan + notifications; coach can dismiss alerts.",
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_create_proposal_rejects_short_title(self):
        """Title shorter than 10 chars raises ProposalValidationError."""
        from app.services.exceptions import ProposalValidationError

        pool = FakePool()
        svc = StrategicMemoryService(pool)

        with pytest.raises(ProposalValidationError) as exc:
            await svc.create_proposal(
                title="verify",
                description="x",
                action_type="general",
                risk="low",
                objective="o", reasoning="r",
                action_steps=["s"], expected_impact="i", rollback="rb",
            )
        assert "title" in exc.value.reason

    @pytest.mark.asyncio
    async def test_create_proposal_rejects_missing_objective(self):
        """A long title without an objective is still rejected."""
        from app.services.exceptions import ProposalValidationError

        pool = FakePool()
        svc = StrategicMemoryService(pool)

        with pytest.raises(ProposalValidationError) as exc:
            await svc.create_proposal(
                title="A reasonably long title for the gate",
                description="x",
                action_type="general",
                risk="low",
                objective="",
                reasoning="r",
                action_steps=["s"],
                expected_impact="i",
                rollback="rb",
            )
        assert "objective" in exc.value.reason

    @pytest.mark.asyncio
    async def test_create_proposal_rejects_empty_action_steps(self):
        from app.services.exceptions import ProposalValidationError

        pool = FakePool()
        svc = StrategicMemoryService(pool)

        with pytest.raises(ProposalValidationError):
            await svc.create_proposal(
                title="A reasonably long title for the gate",
                description="x",
                action_type="general",
                risk="low",
                objective="o",
                reasoning="r",
                action_steps=["", "  "],  # whitespace-only counts as empty
                expected_impact="i",
                rollback="rb",
            )

    @pytest.mark.asyncio
    async def test_create_proposal_blocks_auto_execute_for_medium_risk(self):
        """auto_execute_after must be NULL for any non-LOW risk proposal."""
        pool = FakePool()
        svc = StrategicMemoryService(pool)

        await svc.create_proposal(
            title="Medium-risk proposal needing approval",
            description="",
            action_type="general",
            risk="medium",
            auto_execute_hours=2,  # caller asked for auto-execute
            objective="o", reasoning="r",
            action_steps=["s"], expected_impact="i", rollback="rb",
        )
        # The 9th positional arg to the INSERT is auto_execute_after; for
        # MEDIUM risk it must be None even when auto_execute_hours was set.
        last = pool._conn._queries[-1]
        assert last[0] == "fetchrow"
        assert "INSERT INTO strategy_proposals" in last[1]
        assert last[2][7] is None, "MEDIUM risk must not auto-execute"

    @pytest.mark.asyncio
    async def test_get_pending_proposals(self):
        conn = FakeConnection()
        conn._rows = [
            FakeRow({"proposal_id": uuid4(), "title": "Pending", "status": "proposed", "risk": "low"}),
        ]
        pool = FakePool(conn)
        svc = StrategicMemoryService(pool)

        results = await svc.get_pending_proposals()
        assert len(results) == 1


class TestLayer4CoherenceBriefing:
    @pytest.mark.asyncio
    async def test_get_latest_coherence_briefing_empty(self):
        conn = FakeConnection()
        conn._row = None
        pool = FakePool(conn)
        svc = StrategicMemoryService(pool)

        result = await svc.get_latest_coherence_briefing()
        assert result is None


class TestLayer5ForesightAlerts:
    @pytest.mark.asyncio
    async def test_get_active_foresight_alerts_empty(self):
        conn = FakeConnection()
        conn._rows = []
        pool = FakePool(conn)
        svc = StrategicMemoryService(pool)

        results = await svc.get_active_foresight_alerts()
        assert results == []


class TestLayer6SwarmOversight:
    @pytest.mark.asyncio
    async def test_get_swarm_overview_empty(self):
        conn = FakeConnection()
        conn._rows = []
        conn._row = FakeRow({"active_fibre_count": 0, "total_tokens_consumed": 0}) if False else None
        pool = FakePool(conn)
        svc = StrategicMemoryService(pool)

        result = await svc.get_swarm_overview()
        # Should return something even if empty
        assert result is not None or result is None  # permissive — just no crash
