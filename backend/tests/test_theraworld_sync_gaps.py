"""Smoke tests for the TheraWorld / vault sync enhancements. No live writes."""

import pytest

from app.services.main_chat_payload import (
    assemble_stride_prompt,
    shared_turn_note,
    theraworld_this_turn,
)
from app.services.sse_panel_chat_context import build_sse_panel_chat_context
from app.services.theraworld_turn import choose_picture
from app.sse.thera_world_engine import companion_response, select_companions
from app.websocket.crystal_recall_bridge import (
    _disclosure_beside_panel_ask,
    crystallize_from_conversation,
)

PROFILE = {"hardware_id": "CLIENT_T_ID", "username": "tester"}
_PANEL = (
    "[SOVEREIGN JOURNEY PANEL — client asked about this image]\n"
    "- Core character manifested: The Veiled Pilgrim\n"
    "- Scene narrative: a pilgrim walks beside the client without judgment\n"
    "[SSE PANEL IMAGE MISSING] Pixels did not load this turn."
)


def _prompt(**overrides):
    args = dict(
        name="A",
        user_text="hello",
        depth="extra",
        plan_block="",
        crystal_block="",
        history_block="",
        critical_block="",
        live_turns=[],
        panel_ctx="",
        max_tokens=900,
        autonomic_state="in_window",
        session_id="",
        stance_addendum="",
        safety_suffix="",
        ios_mode=False,
        has_vision=False,
        standing_request="",
        standing_confirmed=False,
        theraworld_setting=False,
    )
    args.update(overrides)
    return assemble_stride_prompt(**args)


class _Conn:
    def __init__(self):
        self.inserted = None
        self.calls = 0

    async def fetchval(self, *args):
        self.calls += 1
        return "00000000-0000-0000-0000-000000000001"

    async def fetchrow(self, sql, *args):
        self.calls += 1
        if "INSERT INTO nate_intelligence_crystals" in (sql or "") and args:
            self.inserted = args[0]
            return {"confidence": 0.5}
        return None

    async def execute(self, *args, **kwargs):
        return None


class _Pool:
    def __init__(self):
        self.conn = _Conn()

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *exc):
                return False

        return _Ctx()


class _EmptyPool:
    async def fetch(self, *args):
        return []

    async def fetchrow(self, *args):
        return None

    async def fetchval(self, *args):
        return None


def test_panel_tag_alone_is_not_a_disclosure():
    assert _disclosure_beside_panel_ask(
        "(asking about my Sovereign Journey story panel image id:abc)"
    ) == ""
    kept = _disclosure_beside_panel_ask(
        "I feel ashamed and the serpent is how my shame shows up "
        "[SSE Panel:11111111-1111-1111-1111-111111111111]"
    )
    assert "ashamed" in kept
    assert "Sovereign Journey" not in kept
    assert "[SSE Panel:" not in kept


@pytest.mark.asyncio
async def test_pure_panel_ask_does_not_crystallize():
    pool = _Pool()
    result = await crystallize_from_conversation(
        pool, "CLIENT_T_ID",
        "(asking about my Sovereign Journey story panel image id:abc)",
        "I am here with you.",
    )
    assert result is None
    assert pool.conn.calls == 0


@pytest.mark.asyncio
async def test_disclosure_beside_panel_ask_is_crystallized():
    pool = _Pool()
    text = (
        "I feel ashamed and the serpent is how my shame shows up in my body "
        "when I look at this (asking about my Sovereign Journey story panel image id:abc)"
    )
    result = await crystallize_from_conversation(
        pool, "CLIENT_T_ID", text, "I hear you. That shame has a shape.",
    )
    assert result
    assert pool.conn.inserted
    assert "ashamed" in pool.conn.inserted
    assert "Sovereign Journey story panel" not in pool.conn.inserted


def test_shared_note_keeps_the_scene_at_the_end():
    vault = "V" * 7000
    note = shared_turn_note(vault, _PANEL)
    assert len(note) <= 6000
    assert note.endswith("[SSE PANEL IMAGE MISSING] Pixels did not load this turn.")
    assert "The Veiled Pilgrim" in note
    assert "the end of this block was left out" in note


def test_switch_without_a_panel_does_not_open_the_journey():
    assert theraworld_this_turn("hello", "", True) is False
    assert theraworld_this_turn("hello", _PANEL, True) is True
    system, _, _ = _prompt(theraworld_setting=True, panel_ctx="", session_id="s-empty")
    assert "they opened it this turn" not in system
    assert "you may offer the journey once" not in system


def test_scene_line_survives_a_vault_file():
    system, _, _ = _prompt(
        user_text="what does this scene mean",
        panel_ctx=_PANEL,
        attachment_block="V" * 7000,
        theraworld_setting=False,
    )
    assert "The Veiled Pilgrim" in system
    assert "they opened it this turn" in system
    assert "Trust the picture over any caption" not in system
    assert "writing only" in system.lower() or "Do not say you can see it" in system


def test_vault_pixels_are_not_called_the_journey():
    system, _, _ = _prompt(
        panel_ctx=_PANEL + "\n[SCENE NOTES ARE WRITING ONLY] The attached picture is a vault file.",
        has_vision=True,
    )
    assert "A vault file is attached as pixels" in system
    assert "Trust the picture over any caption" not in system


def test_explicit_tag_chooses_the_picture():
    image, journey = choose_picture(
        "see [SSE Panel:abc] and [Vault:def]", "vault-img", "panel-img",
    )
    assert image == "panel-img" and journey is True
    image, journey = choose_picture("[Vault:def] please", "vault-img", "panel-img")
    assert image == "vault-img" and journey is False


def test_engaged_companion_returns_and_banished_waits():
    weaver = {"name": "The Weaver", "user_response": "engaged"}
    pilgrim = {"name": "The Veiled Pilgrim", "user_response": "banished"}
    monk = {"name": "The Stillwater Monk", "user_response": ""}
    chosen = select_companions([pilgrim, monk, weaver], panel_sequence=0, max_npcs=2)
    assert chosen[0]["name"] == "The Weaver"
    assert all(n["name"] != "The Veiled Pilgrim" for n in chosen)
    assert companion_response("The Weaver", ["I like The Weaver, tell me more"]) == "engaged"
    assert companion_response("The Veiled Pilgrim", ["The Veiled Pilgrim, please go away"]) == "banished"


@pytest.mark.asyncio
async def test_vault_file_does_not_continue_the_scene():
    text, ctx, img = await build_sse_panel_chat_context(
        _EmptyPool(), PROFILE, "the knight in this picture", vault_kind="file",
    )
    assert ctx == ""
    assert img is None
    assert "knight" in text


@pytest.mark.asyncio
async def test_that_character_loads_only_inside_an_open_thread(monkeypatch):
    import app.services.sse_panel_chat_context as spc

    row = {
        "character_manifest": "Scribe",
        "narrative_text": "the scribe waits by the gate",
        "biome": "fog",
        "panel_tone": "meditative",
        "generated_at": None,
        "crystal_domains_used": None,
        "r2_url": "",
        "panel_metadata": None,
    }

    async def _latest(*args, **kwargs):
        return row

    async def _evidence(*args, **kwargs):
        return {"chat": "", "crystals": "", "cycles": "", "reply_therapy": ""}

    async def _thread(*args, **kwargs):
        return False

    monkeypatch.setattr(spc, "_latest_journey_panel_row", _latest)
    monkeypatch.setattr(spc, "_gather_therapeutic_evidence", _evidence)
    monkeypatch.setattr(spc, "_recent_panel_thread", _thread)

    _, quiet, _ = await build_sse_panel_chat_context(
        _EmptyPool(), PROFILE, "what about that character", journey_open=False,
    )
    assert quiet == ""

    _, opened, _ = await build_sse_panel_chat_context(
        _EmptyPool(), PROFILE, "what about that character", journey_open=True,
    )
    assert "Scribe" in opened
    assert "the scribe waits by the gate" in opened

    _, plain, _ = await build_sse_panel_chat_context(
        _EmptyPool(), PROFILE, "I had a hard day", journey_open=True,
    )
    assert plain == ""
