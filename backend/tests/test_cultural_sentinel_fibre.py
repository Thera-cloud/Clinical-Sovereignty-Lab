"""
Tests for CulturalSentinelFibre — cultural context monitoring and sentiment analysis.
"""

import pytest
from uuid import uuid4

from app.fibres.cultural_sentinel import CulturalSentinelFibre
from app.models.fibre import FibreConfig, FibreType, FibreTask, FibreResult


# ─── Helpers ───────────────────────────────────────────────────────────────────

def make_fibre(fake_pool):
    config = FibreConfig(
        fibre_type=FibreType.CULTURAL_SENTINEL,
        name="Test Cultural Sentinel Fibre",
        domain_tags=["cultural", "monitoring"],
        wisdom_seed={
            "cultural_context": "gen_z_mental_health",
            "platforms": ["tiktok", "instagram"],
        },
    )
    return CulturalSentinelFibre(config=config, db_pool=fake_pool)


def make_task(fibre, task_type, payload=None):
    return FibreTask(
        fibre_id=fibre.fibre_id,
        task_type=task_type,
        payload=payload or {},
    )


# ─── Tests ─────────────────────────────────────────────────────────────────────

class TestCulturalSentinelScanSentiment:
    @pytest.mark.asyncio
    async def test_scan_sentiment_success(self, fake_pool):
        """scan_sentiment should return a successful FibreResult with sentiment data."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "scan_sentiment", {"hours": 24})

        result = await fibre._execute_impl(task)

        assert isinstance(result, FibreResult)
        assert result.success is True
        assert "cultural_context" in result.output
        assert result.output["cultural_context"] == "gen_z_mental_health"
        assert "sentiment_data" in result.output


class TestCulturalSentinelDetectShift:
    @pytest.mark.asyncio
    async def test_detect_shift_insufficient_history(self, fake_pool):
        """detect_shift should report insufficient history when no observations exist."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "detect_shift")

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert result.output["shift_detected"] is False
        assert "Insufficient" in result.output.get("reason", "")


class TestCulturalSentinelCalculateIncoherence:
    @pytest.mark.asyncio
    async def test_calculate_incoherence_success(self, fake_pool):
        """calculate_incoherence should return incoherence index."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "calculate_incoherence")

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert "incoherence_index" in result.output
        assert "internal_score" in result.output
        assert "external_score" in result.output


class TestCulturalSentinelGenerateReport:
    @pytest.mark.asyncio
    async def test_report_success(self, fake_pool):
        """report should return a cultural intelligence report."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "report")

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert "report" in result.output
        assert result.output["report"]["cultural_context"] == "gen_z_mental_health"


class TestCulturalSentinelObserve:
    @pytest.mark.asyncio
    async def test_observe_returns_expected_structure(self, fake_pool):
        """observe() should return dict with cultural_sentinel observation type."""
        fibre = make_fibre(fake_pool)
        obs = await fibre.observe()

        assert isinstance(obs, dict)
        assert obs["observation_type"] == "cultural_sentinel"
        assert obs["cultural_context"] == "gen_z_mental_health"
        assert "fibre_id" in obs
        assert "timestamp" in obs


class TestCulturalSentinelUnknownTask:
    @pytest.mark.asyncio
    async def test_unknown_task_type_returns_error(self, fake_pool):
        """Unknown task type should return error FibreResult."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "nonexistent_task")

        result = await fibre._execute_impl(task)

        assert isinstance(result, FibreResult)
        assert result.success is False
        assert "error" in result.output
