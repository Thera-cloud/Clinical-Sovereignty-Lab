"""
Tests for TransgenerationalPatternEngine — cross-generational pattern analysis.
"""

import pytest
from uuid import uuid4

from app.services.pattern_engine import TransgenerationalPatternEngine
from app.services.exceptions import InsufficientDataException


# ─── Helpers ───────────────────────────────────────────────────────────────────

def make_engine(fake_pool):
    return TransgenerationalPatternEngine(db_pool=fake_pool)


# ─── Tests ─────────────────────────────────────────────────────────────────────

class TestPatternEngineInit:
    def test_initialization(self, fake_pool):
        engine = make_engine(fake_pool)
        assert engine.db_pool is fake_pool
        assert engine.MIN_FAMILY_MEMBERS == 2


class TestFullAnalysis:
    @pytest.mark.asyncio
    async def test_full_analysis_returns_expected_structure(self, fake_pool):
        """full_analysis should return dict with all sub-analyses, even when DB is empty."""
        engine = make_engine(fake_pool)
        family_id = 1

        result = await engine.full_analysis(family_id)

        assert isinstance(result, dict)
        assert result["family_id"] == family_id
        assert "emotional_themes" in result
        assert "coping_inheritance" in result
        assert "trigger_patterns" in result
        assert "coherence_trajectories" in result
        assert "analyzed_at" in result


class TestEmotionalThemeCorrelation:
    @pytest.mark.asyncio
    async def test_insufficient_members_raises(self, fake_pool):
        """Should raise InsufficientDataException when family has < 2 members."""
        engine = make_engine(fake_pool)
        # FakeConnection.fetch returns [] → 0 members
        with pytest.raises(InsufficientDataException):
            await engine.analyze_emotional_themes(1)

    @pytest.mark.asyncio
    async def test_with_mocked_member_data(self, fake_pool, fake_conn):
        """Should return theme correlation when members and insights exist."""
        # Mock _get_family_members to return 2 members
        member_a_id = 100
        member_b_id = 200
        members = [
            {"id": member_a_id, "name": "Alice", "role": "client", "family_id": 1},
            {"id": member_b_id, "name": "Bob", "role": "client", "family_id": 1},
        ]

        call_count = 0

        async def mock_fetch(query, *args):
            nonlocal call_count
            call_count += 1
            # First call: _get_family_members
            if "FROM users" in query and "family_id" in query:
                return members
            # Insight queries
            if "FROM nate_insights" in query:
                return []
            # Session count
            if "COUNT" in query and "sessions" in query:
                return [{"cnt": 5}]
            return []

        fake_conn.fetch = mock_fetch

        engine = make_engine(fake_pool)
        result = await engine.analyze_emotional_themes(1)

        assert isinstance(result, dict)
        assert result["family_id"] == 1
        assert result["member_count"] == 2
        assert "theme_correlation" in result


class TestCopingMechanismInheritance:
    @pytest.mark.asyncio
    async def test_returns_dict(self, fake_pool):
        """Should return a dict even with empty data."""
        engine = make_engine(fake_pool)
        result = await engine.detect_coping_inheritance(1)
        assert isinstance(result, dict)
        assert "inheritance_rate" in result


class TestTriggerPatternMapping:
    @pytest.mark.asyncio
    async def test_returns_dict(self, fake_pool):
        """Should return a dict even with empty data."""
        engine = make_engine(fake_pool)
        result = await engine.map_trigger_patterns(1)
        assert isinstance(result, dict)
        assert "trigger_events" in result
        assert result["trigger_events"] == 0


class TestCoherenceTrajectoryCorrelation:
    @pytest.mark.asyncio
    async def test_returns_dict(self, fake_pool):
        """Should return a dict even with empty data."""
        engine = make_engine(fake_pool)
        result = await engine.correlate_trajectories(1)
        assert isinstance(result, dict)
        assert result.get("correlation_possible") is False
