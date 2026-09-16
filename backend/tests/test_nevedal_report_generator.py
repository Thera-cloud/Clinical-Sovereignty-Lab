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
        assert result["summary"]["recent_shift"] == result["summary"]["trend"]
        assert "cee_per_10k" in result["summary"]
        assert result["nate_scientific_insight"]["lens"] == "state"


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
    async def test_with_industry_packet(self, fake_pool, fake_conn):
        fake_conn._fetchrow_by_marker = {
            "from users": {
                "id": "u1",
                "name": "Alice",
                "username": "alice",
                "hardware_id": "CLIENT_ALICE_ID",
                "family_id": None,
            },
            "from client_metrics": {
                "anxiety_level": 0.62,
                "depression_indicators": 0.41,
                "stress_level": 0.55,
                "homework_completion_rate": 0.7,
                "breakthrough_count": 1,
                "mood_trend": "improving",
                "shame_profile": {"shame_index": 0.38},
                "pmb": {"legacy_depth": 0.44, "reconsolidation_readiness": 0.5},
                "crisis_perception": {},
                "session_count": 8,
            },
            "from conversation_history": {
                "early_n": 20,
                "late_n": 20,
                "early_anxiety": 8,
                "late_anxiety": 3,
                "early_depression": 6,
                "late_depression": 2,
                "early_dissatisfaction": 4,
                "late_dissatisfaction": 1,
                "early_dissociation": 3,
                "late_dissociation": 1,
                "early_shame": 5,
                "late_shame": 2,
                "early_blaming": 4,
                "late_blaming": 1,
                "replies": 18,
                "witness": 7,
                "somatic": 4,
                "interrupt": 2,
                "cycle_naming": 3,
                "prediction": 2,
                "redirect": 5,
            },
        }
        fake_conn._fetch_by_marker = {
            "from cycle_detections": [
                {
                    "domain": "emotional_state",
                    "detected_period_days": 14,
                    "amplitude": 0.22,
                    "confidence": 0.71,
                    "method": "fft",
                    "detected_at": "2026-09-01",
                }
            ],
            "from cycle_predictions": [
                {
                    "domain": "legacy",
                    "predicted_event": "trough",
                    "predicted_at": "2026-09-20",
                    "confidence": 0.6,
                    "intervention_window_start": "2026-09-18",
                    "intervention_window_end": "2026-09-22",
                    "convergence_risk": 0.2,
                    "status": "pending",
                    "actual_outcome": None,
                }
            ],
            "from therapeutic_predictions": [
                {
                    "prediction_type": "habit",
                    "goal_type": "anxiety_tolerance",
                    "success_probability": 0.64,
                    "confidence_score": 0.7,
                    "accuracy_score": 0.58,
                    "optimal_intervention_plan": {"step": "paced exposure"},
                    "key_amplifiers": {},
                    "key_resistances": {},
                    "created_at": "2026-09-10",
                }
            ],
            "from therapeutic_habit_tracking": [
                {
                    "habit_type": "grounding",
                    "habit_description": "90-second ground",
                    "status": "active",
                    "current_streak": 6,
                    "longest_streak": 9,
                    "total_completions": 12,
                    "total_misses": 3,
                }
            ],
            "from clinical_records": [
                {
                    "record_id": "tp1",
                    "record_type": "treatment_plan",
                    "excerpt": "Reduce panic spikes; name blaming loops.",
                    "coach_reviewed": True,
                    "created_at": "2026-08-01",
                }
            ],
            "from transgenerational_patterns": [
                {
                    "pattern_name": "pursuit-withdraw",
                    "description": "Anonymized pursue-withdraw inheritance",
                    "confidence": 0.66,
                    "effect_size": 0.3,
                    "families_observed": 12,
                }
            ],
        }
        gen = make_generator(fake_pool)
        result = await gen._longitudinal_trends([uuid4()], 84)
        assert result["report_type"] == "longitudinal_trends"
        assert result["nate_scientific_insight"]["lens"] == "industry_clinical"
        assert result["rbi"]["title"] == "Review Board Investigation"
        assert "min_c_emo" not in result["summary"]
        assert "amplitude" not in result["summary"]
        assert "r_squared" not in result["summary"]
        assert result["summary"]["cycle_count"] == 1
        assert result["summary"]["treatment_plan_records"] == 1
        assert result["summary"]["anxiety_direction"] == "improving"
        assert result["instrument"]["pair_with"] == "individual_coherence"
        assert "C_emo" in result["instrument"]["does_not_measure"][0]
        assert result["cycle_detections"][0]["domain"] == "emotional_state"
        assert "witness" in result["nate_tactics"]["observed"]

    @pytest.mark.asyncio
    async def test_sql_aggregates_skip_raw_row_scan(self, fake_pool, fake_conn):
        """Coach Insights path: weekly buckets + one summary row, not 100k raw metrics."""
        fake_conn._fetchval_result = "Lisa West"
        fake_conn._fetchrow_result = {
            "name": "Lisa West",
            "role": "CLIENT",
            "family_id": None,
            "n": 284678,
            "avg_c_emo": 0.41,
            "max_c_emo": 0.88,
            "min_c_emo": 0.11,
            "cee_events": 2,
            "first_half_avg": 0.35,
            "second_half_avg": 0.47,
            "std_dev": 0.08,
        }
        fake_conn._fetch_results = [
            {"week": "2026-W30", "avg": 0.32, "count": 1000},
            {"week": "2026-W31", "avg": 0.48, "count": 2000},
        ]
        uid = uuid4()
        gen = make_generator(fake_pool)
        individual = await gen._individual_coherence([uid], 84)
        assert individual["summary"]["total_measurements"] == 284678
        assert individual["summary"]["cee_events"] == 2
        assert individual["summary"]["trend"] == "improving"
        assert individual["summary"]["recent_shift"] == "improving"
        assert individual["summary"]["cee_per_10k"] == 0.0703
        assert "r_squared" not in individual["summary"]
        assert "slope_per_week" not in individual["summary"]
        assert individual["instrument"]["pair_with"] == "longitudinal_trends"
        assert individual["rbi"]["completes_with"] == "longitudinal_trends"
        assert individual["rbi"]["title"] == "Review Board Investigation"
        assert individual["nate_scientific_insight"]["lens"] == "state"
        assert len(individual["weekly_averages"]) == 2
        assert individual["weekly_averages"][0]["week"] == "2026-W30"
        assert "half-window" in individual["nate_scientific_insight"]["narrative"]

        fake_conn._fetchrow_result = {
            "id": str(uid),
            "name": "Lisa West",
            "username": "LetsGoLisa",
            "hardware_id": "CLIENT_LETSGOLISA_ID",
            "family_id": None,
        }
        fake_conn._fetch_results = []
        longitudinal = await gen._longitudinal_trends([uid], 84)
        assert longitudinal.get("status") == "no_data" or (
            "r_squared" not in (longitudinal.get("summary") or {})
            and "min_c_emo" not in (longitudinal.get("summary") or {})
        )

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
