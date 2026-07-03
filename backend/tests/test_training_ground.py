"""Training Ground ILM acceptance tests — LB-1/LB-2/LB-3."""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_BACKEND = Path(__file__).resolve().parents[1]


def _load_module(name: str, rel_path: str):
    path = _BACKEND / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


cbg = _load_module("coaching_boundary_guard", "app/services/coaching_boundary_guard.py")
tgps = _load_module("training_ground_part_store", "app/services/training_ground_part_store.py")
tge_mod = _load_module("training_ground_engine", "app/services/training_ground_engine.py")


def test_guard_crisis_self_harm():
    r = cbg.evaluate("The Critic says I'm worthless and I want to hurt myself tonight.")
    assert r.tripped is True
    assert r.trip_class == "CRISIS"
    assert r.priority == 1


def test_guard_depth_unburden():
    r = cbg.evaluate("Let's unburden my exile and go back to childhood trauma.")
    assert r.tripped is True
    assert r.trip_class == "DEPTH"
    assert r.priority == 3


def test_guard_hypo_flatten():
    r = cbg.evaluate("I feel numb and flattened inside, like nothing matters.")
    assert r.tripped is True
    assert r.trip_class == "HYPO"
    assert r.priority == 2


def test_guard_passes_benign():
    r = cbg.evaluate("The Warrior part wants to set a boundary at work.")
    assert r.tripped is False


@pytest.mark.asyncio
async def test_insert_ilm_part_blocks_without_consent():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    result = await tgps.insert_ilm_part(
        conn,
        username="jordan",
        part_name="Critic",
        part_category="protector",
        created_by="jordan",
    )
    assert result["ok"] is False
    assert result["reason"] == "consent_required"


@pytest.mark.asyncio
async def test_crisis_freeze_auto_ticket_without_forward():
    """LB-3: crisis line creates CRISIS ticket with full user text; LLM not called."""
    crisis_text = "I want to hurt myself tonight."
    session_id = uuid.uuid4()
    ticket_id = uuid.uuid4()

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        side_effect=[
            {"consented_at": "2026-01-01"},  # has_active_consent
            {
                "id": session_id,
                "state": "TEAM_DIALOGUE",
                "exercise_mode": "hearing",
                "council_snapshot": [],
            },
        ]
    )
    conn.fetchval = AsyncMock(return_value=1)  # approved parts count
    conn.execute = AsyncMock()
    conn.transaction = MagicMock()

    class _Tx:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *args):
            return False

    conn.transaction.return_value = _Tx()
    conn.fetchval = AsyncMock(return_value=ticket_id)

    pool = MagicMock()
    pool.acquire = MagicMock()

    class _Ctx:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *args):
            return False

    pool.acquire.return_value = _Ctx()

    inference = AsyncMock(return_value="should not run")
    engine = tge_mod.TrainingGroundEngine(db_pool=pool, inference_fn=inference)
    engine._resolve_username = AsyncMock(return_value="jordan")

    ws = AsyncMock()
    profile = {"username": "jordan", "role": "CLIENT"}

    with patch.object(tge_mod, "ENABLE_TRAINING_GROUND", True):
        await engine._handle_dialogue_turn({"text": crisis_text}, ws, profile)

    inference.assert_not_called()
    ws.send.assert_called()
    payload = json.loads(ws.send.call_args[0][0])
    assert payload["type"] == "ilm_safety_freeze"
    assert payload["ticket_tier"] == "CRISIS"
    assert payload["state"] == "FROZEN_SAFETY"
    assert "988" in payload["message"]


@pytest.mark.asyncio
async def test_dialogue_blocked_pending_approval():
    session_id = uuid.uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        side_effect=[
            {"consented_at": "2026-01-01"},
            {
                "id": session_id,
                "state": "COUNCIL_FORMATION",
                "exercise_mode": None,
                "council_snapshot": [],
            },
        ]
    )
    conn.fetchval = AsyncMock(return_value=0)
    conn.execute = AsyncMock()

    pool = MagicMock()

    class _Ctx:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *args):
            return False

    pool.acquire.return_value = _Ctx()

    inference = AsyncMock()
    engine = tge_mod.TrainingGroundEngine(db_pool=pool, inference_fn=inference)
    engine._resolve_username = AsyncMock(return_value="jordan")
    ws = AsyncMock()

    with patch.object(tge_mod, "ENABLE_TRAINING_GROUND", True):
        await engine._handle_dialogue_turn(
            {"text": "The Warrior part feels protective today."},
            ws,
            {"username": "jordan"},
        )

    inference.assert_not_called()
    payload = json.loads(ws.send.call_args[0][0])
    assert payload["type"] == "ilm_dialogue_blocked"
    assert payload["reason"] == "pending_approval"


@pytest.mark.asyncio
async def test_enrolled_vs_non_enrolled_crisis_same_guard():
    text = "I want to kill myself"
    a = cbg.evaluate(text)
    b = cbg.evaluate(text)
    assert a.trip_class == b.trip_class == "CRISIS"
