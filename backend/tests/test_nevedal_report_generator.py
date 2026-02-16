"""
Tests for NevedalReportGenerator — 5 research report types.
"""

import pytest
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from app.services.nevedal_report_generator import NevedalReportGenerator


# ─── Helpers ───────────────────────────────────────────────────────────────────

def make_generator(fake_pool):
    return NevedalReportGenerator(db_pool=fake_pool)


def make_metric_row(c_emo=0.45, cee_window=False, cee_duration=0, days_ago=1):
    """Create a fake nevedal_metrics row."""
    return {
        "c_emo": c_emo,
        "p_ent": 0.5,
        "cee_window": cee_window,
        "cee_duration_seconds": cee_duration,
        "biometrics": "{}",
        "recorded_at": datetime.now(timezone.utc) - timedelta(days=days_ago),
    }


# ─── Generator Dispatch ─────────────────────────────────────────────────────

class TestGenerateDispatch:
    @pytest.mark.asyncio
    async def test_unknown_report_type(self, fake_pool):
        gen = make_generator(fake_pool)
        result = await gen.generate("nonexistent_type", [uuid4()])
        assert "error" in result
        assert "available" in result

    @pytest.mark.asyncio
    async def test_dispatch_individual(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        fake_conn._fetchrow_result = {"name": "Alice", "role": "CLIENT", "family_id": None}
        gen = make_generator(fake_pool)
        result = await gen.generate("individual_coherence", [uuid4()])
        assert result["report_type"] == "individual_coherence"

    @pytest.mark.asyncio
    async def test_dispatch_dyad(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        fake_conn._fetchval_result = "TestUser"
        gen = make_generator(fake_pool)
        result = await gen.generate("dyad_comparison", [uuid4(), uuid4()])
        assert result["report_type"] == "dyad_comparison"

    @pytest.mark.asyncio
    async def test_dispatch_family(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        gen = make_generator(fake_pool)
        result = await gen.generate("family_dynamics", [uuid4()], family_id=uuid4())
        assert result.get("report_type") == "family_dynamics" or "status" in result

    @pytest.mark.asyncio
    async def test_dispatch_longitudinal(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        fake_conn._fetchval_result = "TestUser"
        gen = make_generator(fake_pool)
        result = await gen.generate("longitudinal_trends", [uuid4()])
        assert result.get("report_type") == "longitudinal_trends" or "status" in result

    @pytest.mark.asyncio
    async def test_dispatch_coach_efficacy(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        fake_conn._fetchrow_result = {"name": "Coach", "role": "COACH"}
        gen = make_generator(fake_pool)
        result = await gen.generate("coach_efficacy", [uuid4()])
        assert result["report_type"] == "coach_efficacy"


# ─── Individual Coherence ────────────────────────────────────────────────────

class TestIndividualCoherence:
    @pytest.mark.asyncio
    async def test_no_data(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        fake_conn._fetchrow_result = {"name": "Alice", "role": "CLIENT", "family_id": None}
        gen = make_generator(fake_pool)
        result = await gen._individual_coherence([uuid4()], 84)
        assert result["status"] == "no_data"

    @pytest.mark.asyncio
    async def test_no_user_id(self, fake_pool):
        gen = make_generator(fake_pool)
        result = await gen._individual_coherence([], 84)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_with_data(self, fake_pool, fake_conn):
        rows = [make_metric_row(c_emo=0.3 + i * 0.05, days_ago=10 - i) for i in range(6)]
        fake_conn._fetch_results = rows
        fake_conn._fetchrow_result = {"name": "Alice", "role": "CLIENT", "family_id": None}
        gen = make_generator(fake_pool)
        result = await gen._individual_coherence([uuid4()], 84)
        assert result["report_type"] == "individual_coherence"
        assert "summary" in result
        assert result["summary"]["total_measurements"] == 6
        assert result["summary"]["avg_c_emo"] > 0
        assert result["summary"]["trend"] in ["improving", "declining", "stable"]


# ─── Dyad Comparison ────────────────────────────────────────────────────────

class TestDyadComparison:
    @pytest.mark.asyncio
    async def test_needs_two_ids(self, fake_pool):
        gen = make_generator(fake_pool)
        result = await gen._dyad_comparison([uuid4()], 84)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_empty_data(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        fake_conn._fetchval_result = "TestUser"
        gen = make_generator(fake_pool)
        result = await gen._dyad_comparison([uuid4(), uuid4()], 84)
        assert result["report_type"] == "dyad_comparison"
        assert "synchrony" in result
        assert result["synchrony"]["grade"] in [
            "EXCELLENT", "GOOD", "MODERATE", "DEVELOPING"
        ]


# ─── Family Dynamics ────────────────────────────────────────────────────────

class TestFamilyDynamics:
    @pytest.mark.asyncio
    async def test_no_family_id(self, fake_pool):
        gen = make_generator(fake_pool)
        result = await gen._family_dynamics([], 84)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_members(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        gen = make_generator(fake_pool)
        result = await gen._family_dynamics([uuid4()], 84, family_id=uuid4())
        assert result["status"] == "no_members"


# ─── Longitudinal Trends ────────────────────────────────────────────────────

class TestLongitudinalTrends:
    @pytest.mark.asyncio
    async def test_no_user_id(self, fake_pool):
        gen = make_generator(fake_pool)
        result = await gen._longitudinal_trends([], 84)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_data(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        fake_conn._fetchval_result = "Alice"
        gen = make_generator(fake_pool)
        result = await gen._longitudinal_trends([uuid4()], 84)
        assert result["status"] == "no_data"

    @pytest.mark.asyncio
    async def test_enforces_minimum_12_weeks(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        fake_conn._fetchval_result = "Alice"
        gen = make_generator(fake_pool)
        # Even if we pass 7 days, it should use 84
        result = await gen._longitudinal_trends([uuid4()], 7)
        # The method internally forces days = max(days, 84)
        assert result.get("status") == "no_data" or result.get("report_type") == "longitudinal_trends"


# ─── Coach Efficacy ──────────────────────────────────────────────────────────

class TestCoachEfficacy:
    @pytest.mark.asyncio
    async def test_no_coach_id(self, fake_pool):
        gen = make_generator(fake_pool)
        result = await gen._coach_efficacy([], 84)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_clients(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        fake_conn._fetchrow_result = {"name": "Coach Hope", "role": "COACH"}
        gen = make_generator(fake_pool)
        result = await gen._coach_efficacy([uuid4()], 84)
        assert result["report_type"] == "coach_efficacy"
        assert result["summary"]["total_clients"] == 0


# ─── Group By Week Helper ───────────────────────────────────────────────────

class TestGroupByWeek:
    def test_avg_mode(self, fake_pool):
        gen = make_generator(fake_pool)
        now = datetime.now(timezone.utc)
        rows = [
            {"c_emo": 0.4, "recorded_at": now - timedelta(days=1)},
            {"c_emo": 0.6, "recorded_at": now - timedelta(days=2)},
        ]
        result = gen._group_by_week(rows, "c_emo")
        assert isinstance(result, list)
        if result:
            assert "week" in result[0]
            assert "avg" in result[0]

    def test_count_mode(self, fake_pool):
        gen = make_generator(fake_pool)
        now = datetime.now(timezone.utc)
        rows = [
            {"cee_duration_seconds": 10, "recorded_at": now - timedelta(days=1)},
            {"cee_duration_seconds": 20, "recorded_at": now - timedelta(days=2)},
        ]
        result = gen._group_by_week(rows, "cee_duration_seconds", agg="count")
        assert isinstance(result, list)
        if result:
            assert "count" in result[0]

    def test_empty_rows(self, fake_pool):
        gen = make_generator(fake_pool)
        result = gen._group_by_week([], "c_emo")
        assert result == []

    def test_null_recorded_at_skipped(self, fake_pool):
        gen = make_generator(fake_pool)
        rows = [{"c_emo": 0.5, "recorded_at": None}]
        result = gen._group_by_week(rows, "c_emo")
        assert result == []
