"""
Tests for CommunityFibre — community coherence monitoring and facilitation.
"""

import pytest
from uuid import uuid4

from app.fibres.community_fibre import CommunityFibre
from app.models.fibre import FibreConfig, FibreType, FibreTask, FibreResult


# ─── Helpers ───────────────────────────────────────────────────────────────────

def make_fibre(fake_pool):
    config = FibreConfig(
        fibre_type=FibreType.COMMUNITY,
        name="Test Community Fibre",
        domain_tags=["community"],
        wisdom_seed={"community_id": "test-community"},
    )
    return CommunityFibre(config=config, db_pool=fake_pool)


def make_task(fibre, task_type, payload=None):
    return FibreTask(
        fibre_id=fibre.fibre_id,
        task_type=task_type,
        payload=payload or {},
    )


# ─── Tests ─────────────────────────────────────────────────────────────────────

class TestCommunityMonitorHealth:
    @pytest.mark.asyncio
    async def test_monitor_health_success(self, fake_pool):
        """monitor_health should return a successful FibreResult with health data."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "monitor_health")

        result = await fibre._execute_impl(task)

        assert isinstance(result, FibreResult)
        assert result.success is True
        assert "health" in result.output


class TestCommunityIdentifyThemes:
    @pytest.mark.asyncio
    async def test_identify_themes_success(self, fake_pool):
        """identify_themes should return themes list."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "identify_themes")

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert "themes" in result.output
        assert isinstance(result.output["themes"], list)


class TestCommunityEngagementReport:
    @pytest.mark.asyncio
    async def test_engagement_report_success(self, fake_pool):
        """engagement_report should return engagement metrics."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "engagement_report", {"days": 30})

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert "engagement" in result.output


class TestCommunityGrowthAnalysis:
    @pytest.mark.asyncio
    async def test_growth_analysis_success(self, fake_pool):
        """growth_analysis should return growth data."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "growth_analysis")

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert "growth" in result.output


class TestCommunityObserve:
    @pytest.mark.asyncio
    async def test_observe_returns_expected_structure(self, fake_pool):
        """observe() should return dict with community observation type."""
        fibre = make_fibre(fake_pool)
        obs = await fibre.observe()

        assert isinstance(obs, dict)
        assert obs["observation_type"] == "community"
        assert obs["community_id"] == "test-community"
        assert "fibre_id" in obs
        assert "timestamp" in obs


class TestCommunityUnknownTask:
    @pytest.mark.asyncio
    async def test_unknown_task_type_returns_error(self, fake_pool):
        """Unknown task type should return error FibreResult."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "nonexistent_task")

        result = await fibre._execute_impl(task)

        assert isinstance(result, FibreResult)
        assert result.success is False
        assert "error" in result.output
