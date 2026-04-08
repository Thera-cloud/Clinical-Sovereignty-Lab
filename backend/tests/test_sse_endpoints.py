"""Tests for SSE client-facing REST endpoints."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
import json


# ---------------------------------------------------------------------------
# Fixtures — lightweight ASGI test client
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db_pool():
    pool = AsyncMock()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.fixture
def mock_user():
    return {"hardware_id": "TEST_HW_001", "username": "test_user", "role": "CLIENT"}


# ---------------------------------------------------------------------------
# Widget Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_widget_endpoint_returns_data(mock_db_pool, mock_user):
    pool, conn = mock_db_pool
    with patch("app.sse.widget_engine.get_widget_content", new_callable=AsyncMock,
               return_value={"primary_text": "Stay steady", "widget_background_color": "#1a2332"}):
        from app.sse.widget_engine import get_widget_content
        result = await get_widget_content("TEST_HW_001", pool)
    assert result["primary_text"] == "Stay steady"


# ---------------------------------------------------------------------------
# Quest / Mission Creation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quest_create_free_text(mock_db_pool):
    pool, conn = mock_db_pool
    conn.fetchrow.return_value = None  # no existing active quest
    conn.fetchval.return_value = None
    with patch("app.sse.quest_mission_engine.create_quest") as mock_create:
        mock_create.return_value = {"quest_id": "q1", "goal": "learn patience", "status": "active"}
        from app.sse.quest_mission_engine import create_quest
        result = await create_quest("TEST_HW_001", "learn patience", pool)
    assert result["goal"] == "learn patience"
    assert result["status"] == "active"


@pytest.mark.asyncio
async def test_mission_create_free_text(mock_db_pool):
    pool, conn = mock_db_pool
    with patch("app.sse.quest_mission_engine.create_mission") as mock_create:
        mock_create.return_value = {"mission_id": "m1", "relationship_target": "my mother", "status": "active"}
        from app.sse.quest_mission_engine import create_mission
        result = await create_mission("TEST_HW_001", "my mother", "parent", pool)
    assert result["relationship_target"] == "my mother"


# ---------------------------------------------------------------------------
# Identity Status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_identity_status_returns_archetype(mock_db_pool):
    pool, conn = mock_db_pool
    conn.fetchrow.return_value = {
        "completed": True,
        "dominant_character": "seraph",
        "archetype_image_url": "https://r2.example.com/seraph.webp",
    }
    row = await conn.fetchrow("SELECT * FROM sse_identity_forge WHERE user_id=$1", "TEST_HW_001")
    assert row["dominant_character"] == "seraph"
    assert row["completed"] is True


@pytest.mark.asyncio
async def test_identity_reset_clears_forge(mock_db_pool):
    pool, conn = mock_db_pool
    conn.execute.return_value = None
    await conn.execute(
        "DELETE FROM sse_identity_forge WHERE user_id=$1", "TEST_HW_001")
    conn.execute.assert_called_once()
