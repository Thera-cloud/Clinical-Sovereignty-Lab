"""
Tests for QuizFunnelFibre — quiz creation, CTA optimization, and funnel management.
"""

import pytest
from uuid import uuid4

from app.fibres.quiz_funnel import QuizFunnelFibre
from app.models.fibre import FibreConfig, FibreType, FibreTask, FibreResult


# ─── Helpers ───────────────────────────────────────────────────────────────────

def make_fibre(fake_pool):
    config = FibreConfig(
        fibre_type=FibreType.QUIZ_FUNNEL,
        name="Test Quiz Funnel Fibre",
        domain_tags=["marketing", "quiz"],
    )
    return QuizFunnelFibre(config=config, db_pool=fake_pool)


def make_task(fibre, task_type, payload=None):
    return FibreTask(
        fibre_id=fibre.fibre_id,
        task_type=task_type,
        payload=payload or {},
    )


# ─── Tests ─────────────────────────────────────────────────────────────────────

class TestQuizFunnelCreateQuiz:
    @pytest.mark.asyncio
    async def test_create_quiz_success(self, fake_pool):
        """create_quiz should return a successful FibreResult with quiz design."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "create_quiz", {
            "target_audience": "couples",
            "title": "Couples Coherence Assessment",
            "questions": 10,
        })

        result = await fibre._execute_impl(task)

        assert isinstance(result, FibreResult)
        assert result.success is True
        assert "quiz_design" in result.output
        assert result.output["quiz_design"]["target_audience"] == "couples"


class TestQuizFunnelOptimizeCta:
    @pytest.mark.asyncio
    async def test_optimize_cta_success(self, fake_pool):
        """optimize_cta should return CTA optimization data."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "optimize_cta", {"quiz_id": str(uuid4())})

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert "cta_optimization" in result.output


class TestQuizFunnelAnalyzeFunnel:
    @pytest.mark.asyncio
    async def test_analyze_funnel_success(self, fake_pool):
        """analyze_funnel should return funnel analysis data."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "analyze_funnel")

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert "funnel_analysis" in result.output


class TestQuizFunnelAbTestQuiz:
    @pytest.mark.asyncio
    async def test_ab_test_quiz_success(self, fake_pool):
        """ab_test_quiz should return A/B test plan."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "ab_test_quiz", {"quiz_id": str(uuid4()), "variants": 2})

        result = await fibre._execute_impl(task)

        assert result.success is True
        assert "ab_test" in result.output
        assert result.output["ab_test"]["variants"] == 2


class TestQuizFunnelObserve:
    @pytest.mark.asyncio
    async def test_observe_returns_expected_structure(self, fake_pool):
        """observe() should return dict with quiz_funnel observation type."""
        fibre = make_fibre(fake_pool)
        obs = await fibre.observe()

        assert isinstance(obs, dict)
        assert obs["observation_type"] == "quiz_funnel"
        assert "fibre_id" in obs
        assert "timestamp" in obs


class TestQuizFunnelUnknownTask:
    @pytest.mark.asyncio
    async def test_unknown_task_type_returns_error(self, fake_pool):
        """Unknown task type should return error FibreResult."""
        fibre = make_fibre(fake_pool)
        task = make_task(fibre, "nonexistent_task")

        result = await fibre._execute_impl(task)

        assert isinstance(result, FibreResult)
        assert result.success is False
        assert "error" in result.output
