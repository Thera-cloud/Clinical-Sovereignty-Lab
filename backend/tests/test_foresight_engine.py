"""
Tests for ForesightEngine — predictive analytics and time-series forecasting.
"""

import pytest
import numpy as np
from uuid import uuid4

from app.services.foresight_engine import ForesightEngine


# ─── Helpers ───────────────────────────────────────────────────────────────────

def make_engine(fake_pool):
    return ForesightEngine(db_pool=fake_pool)


# ─── Tests ─────────────────────────────────────────────────────────────────────

class TestForesightEngineInit:
    def test_initialization(self, fake_pool):
        engine = make_engine(fake_pool)
        assert engine.db_pool is fake_pool
        assert "internal_therapeutic" in engine.STREAM_WEIGHTS
        assert "external_cultural" in engine.STREAM_WEIGHTS
        assert "historical_pattern" in engine.STREAM_WEIGHTS
        assert "contextual" in engine.STREAM_WEIGHTS


class TestSynthesizeStreams:
    @pytest.mark.asyncio
    async def test_synthesize_streams_returns_structure(self, fake_pool, fake_conn):
        """synthesize_streams should return streams + confidence even with empty DB."""
        # Mock fetchrow to return empty aggregates
        fake_conn._fetchrow_result = {"avg": None, "std": None, "cnt": 0}
        fake_conn._fetch_results = []

        engine = make_engine(fake_pool)
        result = await engine.synthesize_streams()

        assert isinstance(result, dict)
        assert "streams" in result
        assert "overall_confidence" in result
        assert "synthesized_at" in result
        assert isinstance(result["overall_confidence"], float)


class TestGenerateAlerts:
    @pytest.mark.asyncio
    async def test_generate_alerts_returns_list(self, fake_pool, fake_conn):
        """generate_alerts should return a list (possibly empty with sparse data)."""
        fake_conn._fetchrow_result = {"avg": None, "std": None, "cnt": 0}
        fake_conn._fetch_results = []

        engine = make_engine(fake_pool)
        alerts = await engine.generate_alerts()

        assert isinstance(alerts, list)


class TestLinearTrendFallback:
    def test_linear_trend_produces_forecast(self, fake_pool):
        """_linear_trend should produce a valid forecast array."""
        engine = make_engine(fake_pool)
        data = np.array([0.4, 0.42, 0.45, 0.43, 0.47, 0.5, 0.52])
        horizon = 3

        forecast, intervals = engine._linear_trend(data, horizon)

        assert len(forecast) == horizon
        assert len(intervals) == horizon
        # Forecast values should be clipped to [0, 1]
        assert all(0 <= v <= 1 for v in forecast)
        # Intervals should be (lower, upper) tuples
        for lower, upper in intervals:
            assert lower <= upper


class TestAccuracyReport:
    @pytest.mark.asyncio
    async def test_empty_accuracy_report(self, fake_pool, fake_conn):
        """Should return status=no_resolved_predictions when no data."""
        fake_conn._fetch_results = []

        engine = make_engine(fake_pool)
        report = await engine.get_accuracy_report()

        assert report["total_predictions"] == 0
        assert report["status"] == "no_resolved_predictions"
