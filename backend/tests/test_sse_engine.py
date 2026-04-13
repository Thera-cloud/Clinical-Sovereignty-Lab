"""Tests for SSE engine core — widget, biome transitions, character mapping, degradation."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class FakeConn:
    """Minimal asyncpg connection mock for widget/engine tests."""

    def __init__(self, rows=None):
        self._rows = rows or {}

    async def fetchrow(self, query, *args):
        for key, val in self._rows.items():
            if key in query:
                return val
        return None

    async def fetchval(self, query, *args):
        row = await self.fetchrow(query, *args)
        if row and isinstance(row, dict):
            return list(row.values())[0]
        return row

    async def fetch(self, query, *args):
        return []

    async def execute(self, query, *args):
        pass


class FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        pass


def _pool(rows=None):
    return FakePool(FakeConn(rows))


# ---------------------------------------------------------------------------
# Widget Engine
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_widget_engine_returns_content():
    from app.sse.widget_engine import get_widget_content
    result = await get_widget_content("test_user", _pool({
        "sse_user_journeys": {"current_biome": "fortress_plains"},
    }))
    assert isinstance(result, dict)
    assert "primary_text" in result
    assert "background_color" in result
    assert result["background_color"]  # not empty


@pytest.mark.asyncio
async def test_widget_engine_empty_user():
    from app.sse.widget_engine import get_widget_content
    result = await get_widget_content("nonexistent_user_xyz", _pool())
    assert isinstance(result, dict)
    assert result.get("primary_text")  # should have fallback content


# ---------------------------------------------------------------------------
# Biome Transitions
# ---------------------------------------------------------------------------

def test_biome_transition_thresholds():
    from app.sse.thera_world_engine import BIOME_THRESHOLDS
    assert len(BIOME_THRESHOLDS) >= 5
    biomes = [b["biome"] for b in BIOME_THRESHOLDS]
    assert biomes[0] == "dark_forest"
    assert biomes[-1] == "open_sky"
    for i in range(1, len(BIOME_THRESHOLDS)):
        assert BIOME_THRESHOLDS[i]["min_sessions"] > BIOME_THRESHOLDS[i - 1]["min_sessions"]
        assert BIOME_THRESHOLDS[i]["min_crystals"] > BIOME_THRESHOLDS[i - 1]["min_crystals"]


# ---------------------------------------------------------------------------
# Crystal → Character Mapping
# ---------------------------------------------------------------------------

def test_crystal_to_character_mapping():
    from app.sse.thera_world_engine import CRYSTAL_TO_CHARACTER, _DEFAULT_CHARACTER
    expected_domains = {"anger", "shame", "grief", "fear", "attachment",
                        "identity", "control", "faith"}
    mapped = set(CRYSTAL_TO_CHARACTER.keys())
    assert expected_domains.issubset(mapped), f"Missing domains: {expected_domains - mapped}"
    for domain, (name, visual) in CRYSTAL_TO_CHARACTER.items():
        assert name, f"Empty character name for domain {domain}"
        assert visual, f"Empty visual prompt for domain {domain}"
    assert _DEFAULT_CHARACTER[0], "Default character name is empty"


# ---------------------------------------------------------------------------
# Graceful Degradation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_graceful_degradation_empty_db():
    """Widget should return valid content even with a completely empty database."""
    from app.sse.widget_engine import get_widget_content
    result = await get_widget_content("brand_new_user", _pool())
    assert result.get("primary_text"), "Degradation failed — no primary_text for empty DB"
    assert result.get("background_color"), "No background color in degraded mode"


# ---------------------------------------------------------------------------
# Narrative Fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compose_narrative_fallback():
    """When LLM fails, compose_journey_narrative should return a template."""
    from app.sse.thera_world_engine import compose_journey_narrative, _DEFAULT_CHARACTER
    profile = {
        "current_biome": "dark_forest",
        "dominant_domain": "anger",
        "session_count": 3,
        "crystal_count": 5,
    }
    journey = {"current_phase": "the_becoming"}
    biome = {"biome": "dark_forest", "description": "fog and mystery"}
    with patch("app.sse.llm_fallback.chat_completion_with_fallback",
               new_callable=AsyncMock, return_value=None):
        result = await compose_journey_narrative(
            profile, journey, biome, _DEFAULT_CHARACTER, _pool(),
            user_id="test_user",
        )
    assert isinstance(result, dict)
    assert result.get("narrative_text"), "Fallback narrative_text is empty"
    assert result.get("image_prompt"), "Fallback image_prompt is empty"
