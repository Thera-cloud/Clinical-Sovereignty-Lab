"""
Crystal attribution contract test (WIRE_WHAT_EXISTS Commit 2 — STEP 1).

Verifies the two hand-offs that make a Nate response attributable to the
crystals recalled for it:

  1. crystal_recall_bridge.recall_crystals_for_context() exposes the
     recalled crystal ids as a `.crystal_ids` attribute on its returned
     string (a str subclass — existing callers see a plain string).
  2. bridge_server._persist_chat_to_conversation_history() writes those
     ids into conversation_history.metadata as {"crystal_ids": [...]}
     alongside the existing {"turn_id": ...} key, capped at 50, gated by
     ENABLE_CRYSTAL_ATTRIBUTION (default True).

_persist_chat_to_conversation_history is extracted from bridge_server.py
via regex + exec (same convention as test_dojo_model_tier_routing.py) —
bridge_server.py is a 27k-line module with module-level `str | None`
syntax that is not importable under the Python 3.9 test runner.
"""

import asyncio
import json
import logging
import os
import pathlib
import re
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# Part 1 — recall_crystals_for_context() exposes .crystal_ids
# ---------------------------------------------------------------------------


class _FakeAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, user_uuid="user-uuid-123"):
        self._user_uuid = user_uuid

    async def fetchval(self, *args, **kwargs):
        return self._user_uuid


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquireCtx(self._conn)


@pytest.mark.asyncio
async def test_recall_context_exposes_crystal_ids(monkeypatch):
    import app.websocket.crystal_recall_bridge as crb

    async def _fake_fast_recall(conn, user_uuid, query_text, max_user=5, max_global=3):
        return (
            [{"id": 11, "crystal_text": "Personal memory.", "confidence": 0.8, "domain": "clinical"}],
            [{"id": 22, "crystal_text": "General insight.", "confidence": 0.9, "domain": "general"}],
            {11, 22},
        )

    reinforced = {}

    async def _fake_reinforce(db_pool, hardware_id, crystal_ids, source):
        reinforced["ids"] = list(crystal_ids)

    async def _fake_deep_recall(*args, **kwargs):
        return None

    monkeypatch.setattr(crb, "_fast_recall_crystals", _fake_fast_recall)
    monkeypatch.setattr(crb, "_reinforce_recalled_crystals", _fake_reinforce)
    monkeypatch.setattr(crb, "_deep_recall_crystals", _fake_deep_recall)
    monkeypatch.setattr(crb, "_get_deep_cache", lambda *a, **k: None)
    monkeypatch.setattr(crb, "_ENABLE_CRYSTAL_ATTRIBUTION", True)

    ctx = await crb.recall_crystals_for_context(
        _FakePool(_FakeConn()), "hw_abc", max_results=8, source="bridge_chat",
    )
    await asyncio.sleep(0)  # let the fire-and-forget reinforce task run

    assert isinstance(ctx, str)
    assert "Personal memory." in ctx
    assert "General insight." in ctx
    assert sorted(getattr(ctx, "crystal_ids", [])) == [11, 22]
    assert reinforced["ids"] == [11, 22]


@pytest.mark.asyncio
async def test_recall_context_flag_off_omits_crystal_ids(monkeypatch):
    """ENABLE_CRYSTAL_ATTRIBUTION=False must not attach .crystal_ids — the
    returned value must remain a behaviorally identical plain string."""
    import app.websocket.crystal_recall_bridge as crb

    async def _fake_fast_recall(conn, user_uuid, query_text, max_user=5, max_global=3):
        return (
            [],
            [{"id": 22, "crystal_text": "General insight.", "confidence": 0.9, "domain": "general"}],
            {22},
        )

    async def _fake_reinforce(*args, **kwargs):
        return None

    monkeypatch.setattr(crb, "_fast_recall_crystals", _fake_fast_recall)
    monkeypatch.setattr(crb, "_reinforce_recalled_crystals", _fake_reinforce)
    monkeypatch.setattr(crb, "_deep_recall_crystals", _fake_reinforce)
    monkeypatch.setattr(crb, "_get_deep_cache", lambda *a, **k: None)
    monkeypatch.setattr(crb, "_ENABLE_CRYSTAL_ATTRIBUTION", False)

    ctx = await crb.recall_crystals_for_context(
        _FakePool(_FakeConn()), "hw_abc", max_results=8, source="bridge_chat",
    )
    await asyncio.sleep(0)

    assert "General insight." in ctx
    assert getattr(ctx, "crystal_ids", None) in (None, [])


@pytest.mark.asyncio
async def test_recall_context_caps_crystal_ids_at_50(monkeypatch):
    import app.websocket.crystal_recall_bridge as crb

    many_globals = [
        {"id": i, "crystal_text": f"insight {i}", "confidence": 0.5, "domain": "general"}
        for i in range(1, 71)
    ]

    async def _fake_fast_recall(conn, user_uuid, query_text, max_user=5, max_global=3):
        return ([], many_globals, set(range(1, 71)))

    async def _fake_reinforce(*args, **kwargs):
        return None

    monkeypatch.setattr(crb, "_fast_recall_crystals", _fake_fast_recall)
    monkeypatch.setattr(crb, "_reinforce_recalled_crystals", _fake_reinforce)
    monkeypatch.setattr(crb, "_deep_recall_crystals", _fake_reinforce)
    monkeypatch.setattr(crb, "_get_deep_cache", lambda *a, **k: None)
    monkeypatch.setattr(crb, "_ENABLE_CRYSTAL_ATTRIBUTION", True)

    ctx = await crb.recall_crystals_for_context(
        _FakePool(_FakeConn()), "hw_abc", max_results=100, source="bridge_chat",
    )
    await asyncio.sleep(0)

    assert len(getattr(ctx, "crystal_ids", [])) <= 50


# ---------------------------------------------------------------------------
# Part 2 — _persist_chat_to_conversation_history() writes crystal_ids
# ---------------------------------------------------------------------------


def _load_persist_function():
    """
    Extract _persist_chat_to_conversation_history from bridge_server.py via
    regex + exec. Avoids importing bridge_server.py (27k lines; contains
    module-level `str | None` syntax that raises TypeError under the
    Python 3.9 test runner — see test_dojo_model_tier_routing.py for the
    established convention this follows).
    """
    bridge_path = (
        pathlib.Path(__file__).resolve().parents[1] / "app" / "websocket" / "bridge_server.py"
    )
    src = bridge_path.read_text()
    m = re.search(
        r"^async def _persist_chat_to_conversation_history\(" r"[\s\S]*?"
        r"^        logger\.warning\(\"_persist_chat_to_conversation_history: %s\", e\)\n",
        src,
        re.MULTILINE,
    )
    assert m, "_persist_chat_to_conversation_history not found in bridge_server.py"
    ns = {
        "os": os,
        "json": json,
        "logger": logging.getLogger("test_persist_fn"),
        "Optional": Optional,
    }
    exec(compile(m.group(0), "bridge_server._persist_chat_to_conversation_history", "exec"), ns)
    return ns["_persist_chat_to_conversation_history"]


class _RecordingConn:
    def __init__(self):
        self.calls = []

    async def execute(self, query, *args):
        self.calls.append((query, args))


class _RecordingPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquireCtx(self._conn)


@pytest.fixture()
def persist_fn():
    return _load_persist_function()


@pytest.mark.asyncio
async def test_persist_writes_exact_crystal_ids(monkeypatch, persist_fn):
    monkeypatch.setenv("ENABLE_CRYSTAL_ATTRIBUTION", "true")
    conn = _RecordingConn()
    pool = _RecordingPool(conn)

    await persist_fn(
        pool, "alice", "hello", "hi there", session_id="sess-1",
        turn_id="turn-abc", crystal_ids=[9, 3, 3, 5],
    )

    assert len(conn.calls) == 1
    _query, args = conn.calls[0]
    meta = json.loads(args[4])
    assert meta["turn_id"] == "turn-abc"
    assert meta["crystal_ids"] == [9, 3, 3, 5]


@pytest.mark.asyncio
async def test_persist_caps_crystal_ids_at_50(monkeypatch, persist_fn):
    monkeypatch.setenv("ENABLE_CRYSTAL_ATTRIBUTION", "true")
    conn = _RecordingConn()
    pool = _RecordingPool(conn)

    await persist_fn(
        pool, "alice", "hello", "hi there",
        crystal_ids=list(range(1, 71)),
    )

    _query, args = conn.calls[0]
    meta = json.loads(args[4])
    assert len(meta["crystal_ids"]) == 50
    assert meta["crystal_ids"] == list(range(1, 51))


@pytest.mark.asyncio
async def test_persist_flag_off_omits_crystal_ids(monkeypatch, persist_fn):
    monkeypatch.setenv("ENABLE_CRYSTAL_ATTRIBUTION", "false")
    conn = _RecordingConn()
    pool = _RecordingPool(conn)

    await persist_fn(
        pool, "alice", "hello", "hi there",
        turn_id="turn-abc", crystal_ids=[9, 3],
    )

    _query, args = conn.calls[0]
    meta = json.loads(args[4])
    assert meta == {"turn_id": "turn-abc"}
    assert "crystal_ids" not in meta


@pytest.mark.asyncio
async def test_persist_no_ids_no_turn_id_writes_empty_metadata(monkeypatch, persist_fn):
    monkeypatch.setenv("ENABLE_CRYSTAL_ATTRIBUTION", "true")
    conn = _RecordingConn()
    pool = _RecordingPool(conn)

    await persist_fn(pool, "alice", "hello", "hi there")

    _query, args = conn.calls[0]
    assert json.loads(args[4]) == {}


@pytest.mark.asyncio
async def test_persist_empty_crystal_ids_list_omits_key(monkeypatch, persist_fn):
    """An empty list is falsy — matches Commit 2's spec: 'Only when
    non-empty; cap at 50 ids.'"""
    monkeypatch.setenv("ENABLE_CRYSTAL_ATTRIBUTION", "true")
    conn = _RecordingConn()
    pool = _RecordingPool(conn)

    await persist_fn(pool, "alice", "hello", "hi there", turn_id="t1", crystal_ids=[])

    _query, args = conn.calls[0]
    meta = json.loads(args[4])
    assert meta == {"turn_id": "t1"}
