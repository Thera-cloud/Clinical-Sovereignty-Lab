"""Seam tests for Ask Nate clinical intelligence pack (Sovereign Command)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "ask_nate_clinical_intelligence.py"
)
_spec = importlib.util.spec_from_file_location("ask_nate_ci_under_test", _PATH)
ci = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(ci)


def test_agent_capabilities_declare_live_and_reserved():
    ids = {c["id"] for c in ci.ASK_NATE_AGENT_CAPABILITIES}
    assert "recall_crystals" in ids
    assert "recall_main_chat" in ids
    assert "symbolic_verify" in ids
    assert "agent_tools" in ids
    live = [c for c in ci.ASK_NATE_AGENT_CAPABILITIES if c["status"] == "live"]
    reserved = [c for c in ci.ASK_NATE_AGENT_CAPABILITIES if c["status"] == "reserved"]
    assert len(live) >= 4
    assert len(reserved) >= 2


def test_ns_snapshot_formats_core_fields():
    snap = ci._ns_snapshot(
        {
            "C_emo": 0.72,
            "GAP": 0.31,
            "risk_level": "MODERATE",
            "pmb": {"reconsolidation_readiness": 0.61},
            "shame_profile": {"shame_index": 0.4},
        }
    )
    assert "C_emo=0.72" in snap
    assert "GAP=0.31" in snap
    assert "risk=MODERATE" in snap
    assert "reconsolidation_readiness=0.61" in snap


def test_agentic_envelope_structure():
    env = ci._agentic_envelope("CLIENT_X", "What patterns?")
    assert env["surface"] == "sovereign_command_ask_nate"
    assert env["odpe_domain"] == "clinical"
    assert "recall_crystals" in env["tools_live"]
    assert "agent_tools" in env["tools_reserved"]


@pytest.mark.asyncio
async def test_build_pack_client_mode_assembles_sources(monkeypatch):
    async def _crystals(db, cid, q):
        return "YOUR PERSONAL MEMORIES\ncrystal: abandonment fear"

    async def _chat(db, cid, limit=15):
        return "[MAIN CHAT MEMORY]\nClient: I feel alone"

    async def _metrics(db, cid):
        return "[NEVEDAL METRICS SNAPSHOT]\nC_emo=0.5, risk=LOW"

    async def _classroom(db, cid):
        return ""

    async def _wisdom(db, coach, client_id):
        return "[LIVED WISDOM]\nSession tip: stay with longing"

    async def _symbols(db, cid):
        return ""

    monkeypatch.setattr(ci, "_load_crystals", _crystals)
    monkeypatch.setattr(ci, "_load_main_chat", _chat)
    monkeypatch.setattr(ci, "_load_metrics", _metrics)
    monkeypatch.setattr(ci, "_load_classroom", _classroom)
    monkeypatch.setattr(ci, "_load_lived_wisdom", _wisdom)
    monkeypatch.setattr(ci, "_load_symbols", _symbols)

    pack = await ci.build_ask_nate_prompt_pack(
        None,
        coach_profile={"hardware_id": "COACH_X", "role": "ADMIN"},
        client_id="CLIENT_LETSGOLISA_ID",
        query="Recent patterns?",
    )
    prefix = pack["prompt_prefix"]
    meta = pack["meta"]
    assert "SOVEREIGN COMMAND" in prefix
    assert "ADMIN ADVISORY" in prefix
    assert "Never run therapy on the admin" in prefix or "do NOT therapy" in prefix.lower() or "NOT doing therapy" in prefix
    assert "abandonment" in prefix.lower()
    assert "MAIN CHAT MEMORY" in prefix
    assert "LIVED WISDOM" in prefix
    assert meta["memory_used"] is True
    assert "crystals" in meta["sources"]
    assert "main_chat" in meta["sources"]
    assert "lived_wisdom" in meta["sources"]
    assert meta["mode"] == "client"
    assert meta["agent_envelope"]["surface"] == "sovereign_command_ask_nate"


@pytest.mark.asyncio
async def test_build_pack_roster_mode_no_cross_phi(monkeypatch):
    async def _wisdom(db, coach, client_id):
        assert client_id is None
        return "[LIVED WISDOM — roster]\nCoach presence strong"

    monkeypatch.setattr(ci, "_load_lived_wisdom", _wisdom)

    pack = await ci.build_ask_nate_prompt_pack(
        None,
        coach_profile={"hardware_id": "COACH_X"},
        client_id="",
        query="Any risk indicators?",
    )
    assert pack["meta"]["mode"] == "roster"
    assert "Roster / population" in pack["prompt_prefix"] or "roster" in pack["prompt_prefix"].lower()
    assert "lived_wisdom_roster" in pack["meta"]["sources"]
    assert "NOT doing therapy" in pack["prompt_prefix"]
