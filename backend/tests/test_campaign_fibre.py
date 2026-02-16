"""
Tests for CampaignFibre — autonomous social media campaign management.
"""

import pytest
from uuid import uuid4

from app.fibres.campaign_fibre import CampaignFibre
from app.models.fibre import FibreConfig, FibreType, FibreTask, FibreResult


# ─── Helpers ───────────────────────────────────────────────────────────────────

def make_fibre(fake_pool):
    config = FibreConfig(
        fibre_type=FibreType.CAMPAIGN,
        name="Test Campaign Fibre",
        domain_tags=["marketing", "content"],
    )
    return CampaignFibre(config=config, db_pool=fake_pool)


def make_task(fibre, task_type, payload=None):
    return FibreTask(
        fibre_id=fibre.fibre_id,
        task_type=task_type,
        payload=payload or {},
    )


# ─── Tests ─────────────────────────────────────────────────────────────────────

class TestCampaignFibreGeneratePost:
    @pytest.mark.asyncio
    async def test_generate_post_success(self, fake_pool):
        """generate_post should return a successful FibreResult."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "generate_post", {"platform": "tiktok"})

        result = await fibre._execute_impl(task)

        assert isinstance(result, FibreResult)
        assert result.success is True
        assert result.output["platform"] == "tiktok"
        assert "post" in result.output


class TestCampaignFibreAbTest:
    @pytest.mark.asyncio
    async def test_ab_test_success(self, fake_pool):
        """ab_test should return variants."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "ab_test", {"platform": "instagram", "num_variants": 3})

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert len(result.output["variants"]) == 3


class TestCampaignFibreEvaluatePerformance:
    @pytest.mark.asyncio
    async def test_evaluate_performance_success(self, fake_pool):
        """evaluate_performance should return metrics."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "evaluate_performance", {"days": 7})

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert "metrics" in result.output


class TestCampaignFibreAdjustStrategy:
    @pytest.mark.asyncio
    async def test_adjust_strategy_success(self, fake_pool):
        """adjust_strategy should return adjustments applied count."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "adjust_strategy", {"recommendations": ["more video"]})

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert result.output["adjustments_applied"] == 1


class TestCampaignFibreObserve:
    @pytest.mark.asyncio
    async def test_observe_returns_expected_structure(self, fake_pool):
        """observe() should return observation dict."""
        fibre = make_fibre(fake_pool)
        obs = await fibre.observe()

        assert isinstance(obs, dict)
        assert obs["observation_type"] == "campaign_status"
        assert "fibre_id" in obs
        assert "timestamp" in obs


class TestCampaignFibreUnknownTask:
    @pytest.mark.asyncio
    async def test_unknown_task_type_returns_error(self, fake_pool):
        """Unknown task type should return error FibreResult."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "nonexistent_task")

        result = await fibre._execute_impl(task)

        assert isinstance(result, FibreResult)
        assert result.success is False
        assert "error" in result.output
