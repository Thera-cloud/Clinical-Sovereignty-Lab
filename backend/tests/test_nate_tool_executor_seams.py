"""Seam tests for nate_tool_executor propose/confirm + nudge persist (Phase 2)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.nate_tool_executor import (
    check_and_execute_confirmation,
    detect_tool_intent,
    maybe_propose_from_utterance,
    propose_tool_action,
    _memory_pending,
)


@pytest.fixture(autouse=True)
def _clear_pending():
    _memory_pending.clear()
    yield
    _memory_pending.clear()


@pytest.fixture
def mock_pool():
    conn = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool, conn


def test_detect_book_session():
    intent = detect_tool_intent("Can you book a session with my coach tomorrow?")
    assert intent is not None
    assert intent["tool_name"] == "book_session"
    assert "slot_start" in intent["params"]


def test_detect_reminder():
    intent = detect_tool_intent("Remind me to call my mom tomorrow")
    assert intent is not None
    assert intent["tool_name"] == "set_reminder"
    assert "call my mom" in intent["params"]["text"].lower() or "mom" in intent["params"]["text"].lower()


def test_detect_resource():
    intent = detect_tool_intent("Send me a resource about anxiety")
    assert intent is not None
    assert intent["tool_name"] == "queue_resource"
    assert "anxiety" in intent["params"]["topic"].lower()


def test_detect_ignores_small_talk():
    assert detect_tool_intent("I feel tired today") is None


@pytest.mark.asyncio
async def test_propose_and_confirm_yes_flow(mock_pool):
    pool, conn = mock_pool
    conn.fetchval = AsyncMock(return_value="11111111-1111-1111-1111-111111111111")
    conn.fetchrow = AsyncMock(
        return_value={"id": "22222222-2222-2222-2222-222222222222"}
    )

    with patch.dict("os.environ", {"ENABLE_NATE_TOOL_EXECUTOR": "true"}):
        prop = await maybe_propose_from_utterance(
            "HW_TEST", "Remind me to practice breathing tomorrow"
        )
        assert prop and prop["handled"] is True
        assert "yes" in prop["text"].lower() or "reminder" in prop["text"].lower()

        confirmed = await check_and_execute_confirmation(
            "HW_TEST", "yes", db_pool=pool
        )
        assert confirmed and confirmed["handled"] is True
        assert confirmed["confirmed"] is True
        assert confirmed["result"]["success"] is True
        assert confirmed["result"]["status"] == "scheduled"
        conn.fetchrow.assert_awaited()


@pytest.mark.asyncio
async def test_confirm_no_clears_pending():
    with patch.dict("os.environ", {"ENABLE_NATE_TOOL_EXECUTOR": "true"}):
        await propose_tool_action(
            "HW_NO",
            "c1",
            "set_reminder",
            {"text": "x", "scheduled_at": "2026-07-21T10:00:00+00:00"},
        )
        assert "HW_NO" in _memory_pending
        out = await check_and_execute_confirmation("HW_NO", "no thanks")
        assert out["handled"] is True
        assert out["confirmed"] is False
        assert "HW_NO" not in _memory_pending


@pytest.mark.asyncio
async def test_disabled_flag_noop():
    with patch.dict("os.environ", {"ENABLE_NATE_TOOL_EXECUTOR": "false"}):
        assert await maybe_propose_from_utterance("HW", "book a session please") is None
        assert await check_and_execute_confirmation("HW", "yes") is None


@pytest.mark.asyncio
async def test_confirmation_returns_handled_key():
    """Bridge WS requires handled + text (was broken: confirmed without handled)."""
    with patch.dict("os.environ", {"ENABLE_NATE_TOOL_EXECUTOR": "true"}):
        await propose_tool_action(
            "HW_H",
            "",
            "queue_resource",
            {"topic": "grief"},
        )
        out = await check_and_execute_confirmation("HW_H", "yeah")
        # no db → persist fails but still handled
        assert out["handled"] is True
        assert "text" in out


@pytest.mark.asyncio
async def test_sync_redis_client_stores_pending():
    """Bridge passes sync redis-py client; helpers must use to_thread."""
    from app.services import nate_tool_executor as te

    store = {}

    class SyncRedis:
        def get(self, key):
            return store.get(key)

        def setex(self, key, ttl, payload):
            store[key] = payload
            return True

        def delete(self, key):
            store.pop(key, None)

    sync = SyncRedis()
    with patch.dict("os.environ", {"ENABLE_NATE_TOOL_EXECUTOR": "true"}):
        result = await propose_tool_action(
            "HW_SYNC",
            "",
            "set_reminder",
            {"text": "breathe", "scheduled_at": "2026-07-21T10:00:00+00:00"},
            redis_client=sync,
        )
        assert result["proposed"] is True
        assert te._pending_key("HW_SYNC") in store
        loaded = await te._load_pending("HW_SYNC", sync)
        assert loaded and loaded["tool_name"] == "set_reminder"
