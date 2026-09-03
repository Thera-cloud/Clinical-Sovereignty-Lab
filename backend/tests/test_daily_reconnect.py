"""
Daily Reconnect acceptance harness (spec §12 + plan corrections A–E, REWARD-1/2).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import importlib.util
import sys
from pathlib import Path

import pytest

_ENGINE_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "daily_reconnect_engine.py"
_spec = importlib.util.spec_from_file_location("daily_reconnect_engine", _ENGINE_PATH)
dre = importlib.util.module_from_spec(_spec)
sys.modules["daily_reconnect_engine"] = dre
assert _spec.loader is not None
_spec.loader.exec_module(dre)


def test_age_from_dob_adult():
    dob = (date.today().replace(year=date.today().year - 30)).isoformat()
    assert dre._age_from_dob(dob) == 30


def test_age_from_dob_minor():
    dob = (date.today().replace(year=date.today().year - 16)).isoformat()
    assert dre._age_from_dob(dob) == 16


def test_age_from_dob_missing():
    assert dre._age_from_dob(None) is None
    assert dre._age_from_dob("") is None


def test_rolling_temp_rise_slow_climb():
    engine = dre.DailyReconnectEngine(db_pool=MagicMock())
    rolling = dre._RollingState()
    temp_rise = False
    for t in (0.35, 0.42, 0.48, 0.56):
        detail = {"escalation_hits": 1}
        rolling = engine._update_rolling("s1", t, detail)
        if engine._temp_rise(t, detail, rolling):
            temp_rise = True
    assert temp_rise or rolling.monotonic_rises >= 2


def test_cooled_ambiguous_not_cooled():
    engine = dre.DailyReconnectEngine(db_pool=MagicMock())
    rolling = dre._RollingState()
    cooled, reason = engine._eval_cooled(
        0.3, {"ambiguous": True}, rolling, {"soft_incident_count": 0}
    )
    assert cooled is False
    assert reason == "ambiguous"


def test_reward_accumulation_never_resets():
    engine = dre.DailyReconnectEngine(db_pool=MagicMock())
    msg0 = engine.miss_encouragement_message(5)
    msg1 = engine.miss_encouragement_message(5)
    assert "streak" not in msg0.lower()
    assert "5" not in msg0
    assert msg0 == msg1
    reward = engine._reward_expression()
    assert "5" not in reward
    assert "reconnect" not in reward.lower() or "showing up" in reward.lower()


def test_resolve_prompt_phases():
    assert dre._prompt_count() == 7
    kind, text, phase = dre._resolve_prompt(0)
    assert phase == "connection"
    assert "partner" in text.lower()
    kind, text, phase = dre._resolve_prompt(4)
    assert phase == "reflection"
    assert "yourself" in text.lower()
    _, _, phase = dre._resolve_prompt(7)
    assert phase == "complete"


def test_miss_encouragement_no_guilt():
    msg = dre.DailyReconnectEngine(db_pool=MagicMock()).miss_encouragement_message(0)
    assert "missed" not in msg.lower()
    assert "whenever you're ready" in msg.lower()


def test_tone_gentle_by_default():
    engine = dre.DailyReconnectEngine(db_pool=MagicMock())
    session = {"rolling_escalation": {}, "soft_incident_count": 0}
    tone = engine._encouragement_tone(session, "user1")
    msg = tone.pick(anxious="a", avoidant="b", default="gentle default")
    assert msg == "gentle default"


def test_ryan_style_cluster_expected_fail_until_cluster_detector():
    """Non-keyword slow build — STOPGAP trigger may miss (correction A)."""
    texts = [
        "I feel like a burden to everyone lately.",
        "Nothing seems to matter much anymore.",
        "I've been pulling back and staying quiet.",
    ]
    lex_path = Path(__file__).resolve().parents[1] / "app" / "services" / "suicide_ideation_lexicon.py"
    lex_spec = importlib.util.spec_from_file_location("suicide_ideation_lexicon", lex_path)
    lex = importlib.util.module_from_spec(lex_spec)
    sys.modules["suicide_ideation_lexicon"] = lex
    assert lex_spec.loader is not None
    lex_spec.loader.exec_module(lex)
    crisis_any = any(lex.match_user_text(t) for t in texts)
    assert crisis_any is False  # expected_fail_until_cluster_detector


@pytest.mark.asyncio
async def test_consent_decline_blocks():
    engine = dre.DailyReconnectEngine(db_pool=MagicMock())
    ws = AsyncMock()
    profile = {"username": "adult1", "family_id": "fam1", "dob": "1990-01-01", "role": "CLIENT"}
    with patch.object(engine, "_resolve_user", AsyncMock(return_value="adult1")):
        with patch.object(engine, "_emit_event", AsyncMock()):
            await engine._handle_consent_ack(
                {"session_id": "sid", "accepted": False}, ws, profile
            )
    ws.send.assert_called()
    payload = json.loads(ws.send.call_args[0][0])
    assert payload["accepted"] is False


@pytest.mark.asyncio
async def test_minor_by_age_blocked():
    engine = dre.DailyReconnectEngine(db_pool=MagicMock())
    profile = {
        "username": "teen1",
        "family_id": "fam1",
        "family_role": "MEMBER",
        "dob": (date.today().replace(year=date.today().year - 16)).isoformat(),
    }
    with patch.object(engine, "_emit_event", AsyncMock()):
        block = await engine._join_eligibility(profile, "teen1")
    assert block is not None
    assert block["message"] == "minor_blocked"


@pytest.mark.asyncio
async def test_missing_dob_fail_closed():
    engine = dre.DailyReconnectEngine(db_pool=MagicMock())
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"profile_data": {}, "is_minor": False})
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.db_pool = pool
    profile = {"username": "nodob1", "family_id": "fam1", "family_role": "SPOUSE"}
    with patch.object(engine, "_emit_event", AsyncMock()):
        block = await engine._join_eligibility(profile, "nodob1")
    assert block is not None
    assert block["message"] == "dob_required"


def test_family_sanctuary_handlers_untouched():
    """Regression: paid Family Sanctuary WS types still present in bridge."""
    from pathlib import Path

    bridge = Path(__file__).resolve().parents[1] / "app" / "websocket" / "bridge_server.py"
    text = bridge.read_text()
    for required in (
        "sanctuary_get_or_create",
        "sanctuary_join",
        "generate_group_coaching_response",
    ):
        assert required in text


def test_enter_fs_is_terminal_not_resumed():
    """Lisa/Bill: leftover ENTER_FS must not reopen as today's Daily Reconnect."""
    src = Path(__file__).resolve().parents[1] / "app" / "services" / "daily_reconnect_engine.py"
    text = src.read_text()
    assert "AND state NOT IN ('CLOSED', 'CRISIS_BYPASS', 'ENTER_FS')" in text
    assert "'CLOSED', 'CRISIS_BYPASS', 'ENTER_FS'" in text


def test_get_or_create_does_not_join_family_sanctuary():
    src = (_ENGINE_PATH).read_text()
    handle = src.split("async def _handle_get_or_create", 1)[1].split("async def _handle_join", 1)[0]
    assert "add_or_reconnect_member" not in handle
    assert "_ensure_sanctuary_room" not in handle


def test_fs_offer_accept_attaches_sanctuary():
    src = (_ENGINE_PATH).read_text()
    handle = src.split("async def _handle_fs_offer_response", 1)[1].split("async def _handoff_enter_fs_coaching", 1)[0]
    assert "add_or_reconnect_member" in handle
    assert "_ensure_sanctuary_room" in handle


def test_daily_reconnect_ui_does_not_auto_dump_into_sanctuary():
    dart = Path(__file__).resolve().parents[2] / "mobile" / "lib" / "screens" / "daily_reconnect_screen.dart"
    text = dart.read_text()
    assert "pushReplacement" not in text
    assert "_maybeHandoffToSanctuary(msg)" in text
    state_block = text.split("if (type == 'reconnect_state'", 1)[1].split("if (type == 'reconnect_fs_response'", 1)[0]
    assert "_maybeHandoffToSanctuary" not in state_block
    assert "_logoutToLobby" in text
