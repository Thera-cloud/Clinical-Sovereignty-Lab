"""Unit tests for Nate-mediated session negotiation (option 1)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    path = _ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


sns = _load("session_negotiation_service", "app/services/session_negotiation_service.py")
snb = _load("session_negotiation_bridge", "app/services/session_negotiation_bridge.py")


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setenv("ENABLE_NATE_SESSION_NEGOTIATION", "true")


def test_parse_coach_chat_decisions():
    assert sns.parse_coach_chat("Yes, approve that time") == "approve"
    assert sns.parse_coach_chat("I'm busy then") == "busy"
    assert sns.parse_coach_chat("Can we suggest a different time?") == "alt"
    assert sns.parse_coach_chat("How was your week?") is None


def test_parse_client_chat_decisions():
    assert sns.parse_client_chat("Yes that works") == "accept_alt"
    assert sns.parse_client_chat("None of those work") == "reject_alt"


def test_parse_chosen_slot_index():
    assert sns.parse_chosen_slot_index("I'll take the first one") == 0
    assert sns.parse_chosen_slot_index("option 2 please") == 1


@pytest.mark.asyncio
async def test_open_and_coach_approve():
    start = datetime.now(timezone.utc) + timedelta(days=1)
    end = start + timedelta(minutes=50)
    neg_id = "11111111-1111-1111-1111-111111111111"
    stored = {
        "id": neg_id,
        "session_id": "SESS_1",
        "client_id": "CLIENT_HW",
        "coach_id": "COACH_HW",
        "status": "awaiting_coach",
        "proposed_start": start,
        "proposed_end": end,
        "alt_slots": [],
        "round": 1,
        "max_rounds": 3,
        "metadata": {},
    }

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[None, stored])
    pool = MagicMock()
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__.return_value = conn
    acquire_cm.__aexit__.return_value = False
    pool.acquire.return_value = acquire_cm

    opened = await sns.open_from_pending_session(
        pool,
        {
            "session_id": "SESS_1",
            "client_id": "CLIENT_HW",
            "coach_id": "COACH_HW",
            "status": "pending_approval",
            "scheduled_start": start.isoformat(),
            "scheduled_end": end.isoformat(),
            "client_name": "Pat",
        },
    )
    assert opened["ok"] is True
    assert opened["coach_notify"]["type"] == "session_negotiation_update"
    assert "approve" in opened["coach_notify"]["actions"]

    conn2 = AsyncMock()
    conn2.fetchrow = AsyncMock(side_effect=[stored, {**stored, "status": "approved"}])
    pool2 = MagicMock()
    cm2 = AsyncMock()
    cm2.__aenter__.return_value = conn2
    cm2.__aexit__.return_value = False
    pool2.acquire.return_value = cm2

    decided = await sns.coach_decide(
        pool2, coach_id="COACH_HW", session_id="SESS_1", decision="approve"
    )
    assert decided["ok"] is True
    assert decided["bridge_action"] == "approve_session"


@pytest.mark.asyncio
async def test_coach_busy_offers_alts():
    start = datetime.now(timezone.utc) + timedelta(days=1)
    stored = {
        "id": "22222222-2222-2222-2222-222222222222",
        "session_id": "SESS_2",
        "client_id": "CLIENT_HW",
        "coach_id": "COACH_HW",
        "status": "awaiting_coach",
        "proposed_start": start,
        "proposed_end": start + timedelta(minutes=50),
        "alt_slots": [],
        "round": 1,
        "max_rounds": 3,
        "metadata": {},
    }
    alts = [{"start": (start + timedelta(days=1)).isoformat(), "end": None}]
    updated = {**stored, "status": "alt_proposed", "alt_slots": alts}

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[stored, updated])
    pool = MagicMock()
    cm = AsyncMock()
    cm.__aenter__.return_value = conn
    cm.__aexit__.return_value = False
    pool.acquire.return_value = cm

    with patch.object(sns, "suggest_alt_slots", AsyncMock(return_value=alts)):
        decided = await sns.coach_decide(
            pool, coach_id="COACH_HW", session_id="SESS_2", decision="busy"
        )
    assert decided["ok"] is True
    assert decided["negotiation"]["status"] == "alt_proposed"
    assert decided["client_notify"]["alt_slots"]


@pytest.mark.asyncio
async def test_flag_off_blocks_open(monkeypatch):
    monkeypatch.setenv("ENABLE_NATE_SESSION_NEGOTIATION", "false")
    out = await sns.open_from_pending_session(MagicMock(), {"status": "pending_approval"})
    assert out["ok"] is False
    assert out["error"] == "flag_off"


@pytest.mark.asyncio
async def test_apply_bridge_action_reschedule():
    sessions = [
        {
            "session_id": "SESS_3",
            "client_id": "CLIENT_HW",
            "coach_id": "COACH_HW",
            "status": "pending_approval",
            "scheduled_start": "2026-07-20T15:00:00+00:00",
            "scheduled_end": "2026-07-20T15:50:00+00:00",
        }
    ]
    saved = {}

    def load():
        return sessions

    def save(s):
        saved["sessions"] = s

    result = {
        "bridge_action": "reschedule_and_approve",
        "session_id": "SESS_3",
        "new_start": "2026-07-21T16:00:00+00:00",
        "new_end": "2026-07-21T16:50:00+00:00",
        "negotiation": {
            "client_id": "CLIENT_HW",
            "coach_id": "COACH_HW",
            "status": "approved",
        },
        "client_nate_text": "Booked",
    }
    client_ws = AsyncMock()
    out = await snb.apply_bridge_action(
        result,
        load_sessions=load,
        save_sessions=save,
        connected_clients={"CLIENT_HW": client_ws},
        connected_coaches={},
    )
    assert out["session"]["status"] == "scheduled"
    assert out["session"]["scheduled_start"] == "2026-07-21T16:00:00+00:00"
    assert saved["sessions"][0]["status"] == "scheduled"


snn = _load("session_negotiation_notify", "app/services/session_negotiation_notify.py")


def test_neg_token_roundtrip(monkeypatch):
    monkeypatch.setenv("SESSION_ACTION_SECRET", "test-secret-negotiation")
    nid = "22222222-2222-2222-2222-222222222222"
    tok = snn.make_neg_token(nid, "busy")
    parsed = snn.verify_neg_token(tok)
    assert parsed == (nid, "busy", "")
    tok2 = snn.make_neg_token(nid, "accept_alt", slot="2026-07-20T16:00:00+00:00")
    parsed2 = snn.verify_neg_token(tok2)
    assert parsed2[0] == nid
    assert parsed2[1] == "accept_alt"
    assert "2026-07-20" in parsed2[2]


def test_mailto_and_parse_decision():
    nid = "33333333-3333-3333-3333-333333333333"
    url = snn.mailto_action_url(nid, "approve", "Session request")
    assert url.startswith("mailto:")
    assert "APPROVE" in url.upper() or "approve" in url.lower()
    assert snn.extract_neg_id_from_text(f"Re: x [#neg:{nid}]") == nid
    assert snn.parse_neg_decision("BUSY\n\n[#neg:x]") == "busy"
    assert snn.parse_neg_decision("ALT") == "alt"
    assert snn.parse_neg_decision("ACCEPT") == "accept_alt"
    assert snn.parse_neg_decision("REJECT") == "reject_alt"


def test_staging_public_api_base(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("PUBLIC_API_BASE", "https://api.sovereignsanctuary.net")
    # Loopback staging base is ignored — phone-reachable prod API used instead
    monkeypatch.setenv("STAGING_PUBLIC_API_BASE", "http://127.0.0.1:8011")
    url = snn.negotiation_action_url("44444444-4444-4444-4444-444444444444", "approve")
    assert url.startswith("https://api.sovereignsanctuary.net/")


def test_parse_accept_slot_index():
    assert snn.parse_accept_slot_index("ACCEPT 2\n[#neg:x]") == 1
    assert snn.parse_accept_slot_index("accept #1") == 0
    assert snn.parse_accept_slot_index("ACCEPT") is None
    assert snn.parse_accept_slot_index("REJECT") is None


def test_staging_inbound_fallback_flag(monkeypatch):
    monkeypatch.delenv("ENABLE_STAGING_NEGOTIATION_INBOUND_FALLBACK", raising=False)
    assert snn.staging_inbound_fallback_enabled() is False
    monkeypatch.setenv("ENABLE_STAGING_NEGOTIATION_INBOUND_FALLBACK", "true")
    assert snn.staging_inbound_fallback_enabled() is True
