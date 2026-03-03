"""
Tests for CoherenceEngine — 5-layer coherence measurement with mocked DB.
"""

import json
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.coherence_engine import CoherenceEngine
from app.models.coherence import CoherenceLayer, CoherenceMeasurement, PulseSnapshot


# ─── Fake asyncpg connection/pool ─────────────────────────────────────────────

class FakeConnection:
    """Mock asyncpg connection that returns pre-set rows."""

    def __init__(self, fetch_results=None, fetchrow_result=None):
        self._fetch_results = fetch_results or []
        self._fetchrow_result = fetchrow_result
        self._executed = []

    async def fetch(self, query, *args):
        return self._fetch_results

    async def fetchrow(self, query, *args):
        return self._fetchrow_result

    async def execute(self, query, *args):
        self._executed.append((query, args))

    async def fetchval(self, query, *args):
        return None


class FakePool:
    """Mock asyncpg pool with configurable connection."""

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

class TestCoherenceEngineInit:
    def test_default_thresholds(self):
        engine = CoherenceEngine(db_pool=FakePool())
        assert engine.thresholds is not None
        assert engine.thresholds.individual_min_sessions >= 0


class TestMeasureIndividual:
    @pytest.mark.asyncio
    async def test_no_data_raises_insufficient(self):
        """With no metrics, quiz, or sessions, engine raises InsufficientDataException."""
        from app.services.exceptions import InsufficientDataException
        pool = FakePool(FakeConnection(fetch_results=[]))
        engine = CoherenceEngine(db_pool=pool)

        user_id = uuid4()
        with pytest.raises(InsufficientDataException) as exc_info:
            await engine.measure_individual(user_id)

        assert exc_info.value.details["layer"] == "individual"
        assert exc_info.value.details["available"] == 0

    @pytest.mark.asyncio
    async def test_with_metrics_data(self):
        """With c_emo metrics, score should reflect the data."""
        metrics = [
            {"c_emo": 0.8, "cee_window": True, "recorded_at": datetime.utcnow()},
            {"c_emo": 0.7, "cee_window": False, "recorded_at": datetime.utcnow()},
            {"c_emo": 0.9, "cee_window": True, "recorded_at": datetime.utcnow()},
        ]

        call_count = [0]

        class MultiResultConn(FakeConnection):
            async def fetch(self, query, *args):
                call_count[0] += 1
                if call_count[0] == 1:
                    return metrics  # nevedal_metrics
                elif call_count[0] == 2:
                    return []  # quiz_responses
                elif call_count[0] == 3:
                    return [{"id": uuid4(), "started_at": datetime.utcnow(), "ended_at": datetime.utcnow()}]
                return []

            async def fetchrow(self, query, *args):
                return None

        pool = FakePool(MultiResultConn())
        engine = CoherenceEngine(db_pool=pool)

        measurement = await engine.measure_individual(uuid4())

        assert measurement.score > 0.0
        assert measurement.sample_size == 3
        assert "cee_aggregate" in measurement.components


class TestMeasureGlobal:
    @pytest.mark.asyncio
    async def test_global_with_no_layers(self):
        """Global measurement with no sub-layer data should still produce a result."""
        pool = FakePool(FakeConnection(fetchrow_result=None))
        engine = CoherenceEngine(db_pool=pool)

        measurement = await engine.measure_global()

        assert isinstance(measurement, CoherenceMeasurement)
        assert measurement.layer == CoherenceLayer.GLOBAL
        assert 0.0 <= measurement.score <= 1.0


class TestGapAnalysis:
    @pytest.mark.asyncio
    async def test_gap_analysis_returns_coherence_gap(self):
        """Gap analysis should produce internal/external scores."""
        pool = FakePool(FakeConnection(fetchrow_result=None))
        engine = CoherenceEngine(db_pool=pool)

        gap = await engine.compute_gap_analysis()

        assert gap is not None
        assert hasattr(gap, "internal_score")
        assert hasattr(gap, "external_score")
        assert hasattr(gap, "gap_magnitude")
        assert -1.0 <= gap.gap_magnitude <= 1.0


class TestPulseSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_structure(self):
        """Pulse snapshot should contain all expected fields."""
        pool = FakePool(FakeConnection(fetchrow_result=None))
        engine = CoherenceEngine(db_pool=pool)

        snapshot = await engine.generate_pulse_snapshot()

        assert isinstance(snapshot, PulseSnapshot)
        assert hasattr(snapshot, "global_coherence_index")
        assert hasattr(snapshot, "layer_scores")
        assert hasattr(snapshot, "trending_themes")
        assert isinstance(snapshot.trending_themes, list)
        assert isinstance(snapshot.notable_changes, list)
