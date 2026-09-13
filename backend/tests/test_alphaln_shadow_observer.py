"""Offline tests for AlphaLN Loop A (shadow observer) — no live DB."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

import pytest

from app.services.alphaln_shadow_observer import (
    AlphaLNShadowObserver,
    _reply_hash,
    _score_reply,
    is_enabled,
    pulse_from_app_state,
)


class _FakeConn:
    def __init__(self, state: Dict[str, Any]):
        self._state = state

    async def fetch(self, query: str, *args, **kwargs):
        q = " ".join(query.split())
        if "FROM conversation_history" in q:
            return list(self._state["ch"])
        if "SELECT reply_hash FROM alphaln_shadow_observations" in q:
            return [{"reply_hash": h} for h in self._state["hashes"]]
        return []

    async def fetchrow(self, query: str, *args, **kwargs):
        q = " ".join(query.split())
        if "AVG(score)" in q:
            scores = self._state.get("ledger_scores") or []
            if not scores:
                return {"mean_s": None, "n": 0}
            return {"mean_s": sum(scores) / len(scores), "n": len(scores)}
        return None

    async def execute(self, query: str, *args, **kwargs):
        if "INSERT INTO alphaln_shadow_observations" in query:
            self._state["hashes"].add(args[2])
            self._state["inserts"].append(args)
        return "INSERT 0 1"


class _Acquire:
    def __init__(self, state: Dict[str, Any]):
        self._state = state

    async def __aenter__(self):
        return _FakeConn(self._state)

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, state: Dict[str, Any]):
        self._state = state

    def acquire(self):
        return _Acquire(self._state)


def test_score_reply_heuristic():
    s = _score_reply("It sounds like this has been sitting with you for a while. What is one piece you want to stay with?")
    assert 0.0 <= s["score"] <= 1.0
    assert s["dims"]["inquiry"] == 1.0
    assert s["dims"]["reflective"] == 1.0
    assert s["score_method"] == "heuristic_v1"


@pytest.mark.asyncio
async def test_flag_off_writes_nothing(monkeypatch):
    monkeypatch.delenv("ENABLE_ALPHALN_SHADOW_OBSERVER", raising=False)
    assert is_enabled() is False
    state = {"ch": [{"id": 1, "user_id": "u1", "ai_text": "hello?", "created_at": None}],
             "hashes": set(), "inserts": []}
    obs = AlphaLNShadowObserver(_FakePool(state), app_state=SimpleNamespace())
    out = await obs._tick()
    assert out["status"] == "flag_off"
    assert out["written"] == 0
    assert state["inserts"] == []
    assert obs.app_state.alphaln_shadow_pulse["status"] == "flag_off"


@pytest.mark.asyncio
async def test_dedup_skips_existing_hash(monkeypatch):
    monkeypatch.setenv("ENABLE_ALPHALN_SHADOW_OBSERVER", "true")
    text = "It sounds like a hard week. What wants attention first?"
    rh = _reply_hash(text)
    state = {
        "ch": [{"id": 9, "user_id": "alice", "ai_text": text, "created_at": None}],
        "hashes": {rh},
        "inserts": [],
        "ledger_scores": [0.5],
    }
    obs = AlphaLNShadowObserver(_FakePool(state), app_state=SimpleNamespace())
    out = await obs._tick()
    assert out["written"] == 0
    assert out["skipped"] == 1
    assert state["inserts"] == []


@pytest.mark.asyncio
async def test_write_then_pulse(monkeypatch):
    monkeypatch.setenv("ENABLE_ALPHALN_SHADOW_OBSERVER", "true")
    text = "It sounds like a hard week. What wants attention first?"
    state: Dict[str, Any] = {
        "ch": [{"id": 9, "user_id": "alice", "ai_text": text, "created_at": None}],
        "hashes": set(),
        "inserts": [],
        "ledger_scores": [0.667],
    }
    ns = SimpleNamespace()
    obs = AlphaLNShadowObserver(_FakePool(state), app_state=ns)
    out = await obs._tick()
    assert out["written"] == 1
    assert out["status"] == "wrote"
    assert len(state["inserts"]) == 1
    assert state["inserts"][0][2] == _reply_hash(text)
    assert ns.alphaln_shadow_pulse["written"] == 1
    assert pulse_from_app_state(ns)["written"] == 1


def test_pulse_from_app_state_empty():
    assert pulse_from_app_state(None) == {}
    assert pulse_from_app_state(SimpleNamespace()) == {}


def test_alphaln_shadow_watch_meta():
    from app.websocket.cli_dual_coo import alphaln_shadow_watch_meta

    ns = SimpleNamespace(alphaln_shadow_pulse={"written": 2, "mean_24h": 0.4})
    meta = alphaln_shadow_watch_meta(ns)
    assert meta["alphaln_shadow"]["written"] == 2
    assert alphaln_shadow_watch_meta(None) == {}


@pytest.mark.asyncio
async def test_closer_alphaln_watch_idle():
    from app.services.dual_coo_loop_closer import DualCooLoopCloser

    closer = DualCooLoopCloser(None, app_state=SimpleNamespace())
    out = await closer._cycle_alphaln_watch()
    assert out["status"] == "idle"
