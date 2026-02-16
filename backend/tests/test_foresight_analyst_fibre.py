"""
Tests for ForesightAnalystFibre — predictive foresight from 4 data streams.
"""

import pytest
from uuid import uuid4

from app.fibres.foresight_analyst import ForesightAnalystFibre
from app.models.fibre import FibreConfig, FibreType, FibreTask, FibreResult


# ─── Helpers ───────────────────────────────────────────────────────────────────

def make_fibre(fake_pool):
    config = FibreConfig(
        fibre_type=FibreType.FORESIGHT_ANALYST,
        name="Test Foresight Analyst Fibre",
        domain_tags=["foresight", "analytics"],
    )
    return ForesightAnalystFibre(config=config, db_pool=fake_pool)


def make_task(fibre, task_type, payload=None):
    return FibreTask(
        fibre_id=fibre.fibre_id,
        task_type=task_type,
        payload=payload or {},
    )


# ─── Tests ─────────────────────────────────────────────────────────────────────

class TestForesightAnalystSynthesize:
    @pytest.mark.asyncio
    async def test_synthesize_success(self, fake_pool):
        """synthesize should return a successful FibreResult with synthesis data."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "synthesize")

        result = await fibre._execute_impl(task)

        assert isinstance(result, FibreResult)
        assert result.success is True
        assert "synthesis" in result.output
        assert "overall_confidence" in result.output
        assert "data_streams_active" in result.output


class TestForesightAnalystPredict:
    @pytest.mark.asyncio
    async def test_predict_success(self, fake_pool):
        """predict should return predictions (possibly empty with no data)."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "predict")

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert "predictions" in result.output
        assert "prediction_count" in result.output
        assert isinstance(result.output["predictions"], list)


class TestForesightAnalystValidate:
    @pytest.mark.asyncio
    async def test_validate_success(self, fake_pool):
        """validate should return validated predictions count."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "validate")

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert "validated_predictions" in result.output
        assert "average_accuracy" in result.output


class TestForesightAnalystTrendAnalysis:
    @pytest.mark.asyncio
    async def test_trend_analysis_success(self, fake_pool):
        """trend_analysis should return trends list."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "trend_analysis")

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert "trends" in result.output
        assert isinstance(result.output["trends"], list)


class TestForesightAnalystObserve:
    @pytest.mark.asyncio
    async def test_observe_returns_expected_structure(self, fake_pool):
        """observe() should return dict with foresight_analyst observation type."""
        fibre = make_fibre(fake_pool)
        obs = await fibre.observe()

        assert isinstance(obs, dict)
        assert obs["observation_type"] == "foresight_analyst"
        assert "data_streams" in obs
        assert "fibre_id" in obs
        assert "timestamp" in obs


class TestForesightAnalystUnknownTask:
    @pytest.mark.asyncio
    async def test_unknown_task_type_returns_error(self, fake_pool):
        """Unknown task type should return error FibreResult."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "nonexistent_task")

        result = await fibre._execute_impl(task)

        assert isinstance(result, FibreResult)
        assert result.success is False
        assert "error" in result.output
