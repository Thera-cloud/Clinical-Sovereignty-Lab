"""
Tests for CoachSupportFibre — real-time augmentation for human coaches.
"""

import pytest
from uuid import uuid4

from app.fibres.coach_support import CoachSupportFibre
from app.models.fibre import FibreConfig, FibreType, FibreTask, FibreResult


# ─── Helpers ───────────────────────────────────────────────────────────────────

def make_fibre(fake_pool):
    config = FibreConfig(
        fibre_type=FibreType.COACH_SUPPORT,
        name="Test Coach Support Fibre",
        domain_tags=["coaching"],
        wisdom_seed={"coach_id": "coach-1", "client_ids": ["client-1"]},
    )
    return CoachSupportFibre(config=config, db_pool=fake_pool)


def make_task(fibre, task_type, payload=None):
    return FibreTask(
        fibre_id=fibre.fibre_id,
        task_type=task_type,
        payload=payload or {},
    )


# ─── Tests ─────────────────────────────────────────────────────────────────────

class TestCoachSupportPreSessionBrief:
    @pytest.mark.asyncio
    async def test_pre_session_brief_success(self, fake_pool):
        """pre_session_brief should return a successful FibreResult with brief."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "pre_session_brief", {"client_id": "client-1"})

        result = await fibre._execute_impl(task)

        assert isinstance(result, FibreResult)
        assert result.success is True
        assert "brief" in result.output

    @pytest.mark.asyncio
    async def test_pre_session_brief_requires_client_id(self, fake_pool):
        """pre_session_brief without client_id should fail."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "pre_session_brief", {})

        result = await fibre._execute_impl(task)

        assert result.success is False
        assert "client_id required" in result.output.get("error", "")


class TestCoachSupportInterventionSuggestion:
    @pytest.mark.asyncio
    async def test_intervention_suggestion_success(self, fake_pool):
        """intervention_suggestion should return suggestions list."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "intervention_suggestion", {"client_id": "client-1"})

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert "suggestions" in result.output


class TestCoachSupportPostSessionAnalysis:
    @pytest.mark.asyncio
    async def test_post_session_analysis_success(self, fake_pool):
        """post_session_analysis should return analysis dict."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "post_session_analysis", {"session_id": str(uuid4())})

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert "analysis" in result.output


class TestCoachSupportFamilyContext:
    @pytest.mark.asyncio
    async def test_family_context_success(self, fake_pool):
        """family_context should return context dict."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "family_context", {"client_id": "client-1"})

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert "context" in result.output


class TestCoachSupportObserve:
    @pytest.mark.asyncio
    async def test_observe_returns_expected_structure(self, fake_pool):
        """observe() should return dict with coach_support observation type."""
        fibre = make_fibre(fake_pool)
        obs = await fibre.observe()

        assert isinstance(obs, dict)
        assert obs["observation_type"] == "coach_support"
        assert obs["coach_id"] == "coach-1"
        assert "fibre_id" in obs
        assert "timestamp" in obs


class TestCoachSupportUnknownTask:
    @pytest.mark.asyncio
    async def test_unknown_task_type_returns_error(self, fake_pool):
        """Unknown task type should return error FibreResult."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "nonexistent_task")

        result = await fibre._execute_impl(task)

        assert isinstance(result, FibreResult)
        assert result.success is False
        assert "error" in result.output
