"""Offline tests: the chat panel-context no longer self-seeds follow-up mode
from Little Nate's own replies, honours explicit release phrases, and refuses
to present a stale still as today's panel."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services import sse_panel_chat_context as spc


# ── regexes ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "I'm not talking about the panel, I want to talk about my week",
    "Forget the scene for now.",
    "Can we move on from this story?",
    "Something else is on my mind today",
    "I feel like we're going in circles — a new season, a new adventure",
    "You keep bringing up that scene every day",
    "I'm done with this panel",
])
def test_release_regex_hits(text):
    assert spc._PANEL_RELEASE_RE.search(text)


@pytest.mark.parametrize("text", [
    "What does the hooded figure in this scene mean?",
    "Tell me more about the panel",
    "sure",
    "I had a hard day at work",
])
def test_release_regex_misses(text):
    assert not spc._PANEL_RELEASE_RE.search(text)


@pytest.mark.parametrize("text", [
    "That sunset was beautiful",
    "I was looking at my phone all night",
    "what is that supposed to mean?",
])
def test_visual_follow_regex_no_longer_fires_on_everyday_words(text):
    assert not spc._VISUAL_FOLLOW_RE.search(text)


@pytest.mark.parametrize("text", [
    "who is the knight in this scene?",
    "what about the figure on the bridge in the panel",
    "the scribe — what is he writing?",
])
def test_visual_follow_regex_still_fires_on_panel_nouns(text):
    assert spc._VISUAL_FOLLOW_RE.search(text)


# ── thread state ──────────────────────────────────────────────────────────────

def test_thread_state_ignores_ai_text_and_protocol_words():
    rows = [
        {"user_text": "ok", "ai_text": "DEEP REFLECTION PROTOCOL ... focus topics ... Sovereign Journey story panel"},
        {"user_text": "how was your day", "ai_text": "the scribe on the bridge..."},
    ]
    assert spc._thread_state_from_rows(rows) is False


def test_thread_state_true_on_client_panel_marker():
    rows = [
        {"user_text": "and then?"},
        {"user_text": "(asking about my Sovereign Journey story panel image id:abc) what is this"},
    ]
    assert spc._thread_state_from_rows(rows) is True


def test_thread_state_release_newer_than_marker_wins():
    rows = [  # newest first
        {"user_text": "let's talk about something else"},
        {"user_text": "(asking about my Sovereign Journey story panel image id:abc)"},
    ]
    assert spc._thread_state_from_rows(rows) is False


def test_thread_state_marker_newer_than_release_wins():
    rows = [  # newest first
        {"user_text": "tell me about the story panel again"},
        {"user_text": "let's talk about something else"},
    ]
    assert spc._thread_state_from_rows(rows) is True


class _Pool:
    def __init__(self, rows):
        self.rows, self.sql = rows, ""

    async def fetch(self, sql, *args):
        self.sql = sql
        return self.rows


@pytest.mark.asyncio
async def test_recent_panel_thread_queries_user_text_within_window_only():
    pool = _Pool([{"user_text": "sure"}])
    assert await spc._recent_panel_thread(pool, ["u"]) is False
    assert "SELECT user_text" in pool.sql
    assert "ai_text" not in pool.sql
    assert "INTERVAL '2 hours'" in pool.sql
    assert "ORDER BY created_at DESC" in pool.sql


@pytest.mark.asyncio
async def test_last_discussed_panel_id_bounded_to_current_thread_window():
    """Production check (LetsGoLisa): her last tagged panel was the Aug 4
    journey still, 8h old — explicit follow-up words resolved back to it.
    The prior-tag lookup must share the 2h thread window."""
    pid = "0f3b2d9a-1c4e-4b7a-9d2f-6a8c1e5b7d30"
    pool = _Pool([{"user_text": f"(asking about my Sovereign Journey story panel image id:{pid})"}])
    assert await spc._last_discussed_panel_id(pool, ["u"]) == pid
    assert "INTERVAL '2 hours'" in pool.sql
    assert "SELECT user_text" in pool.sql and "ai_text" not in pool.sql


# ── build_sse_panel_chat_context routing ──────────────────────────────────────

NOW = datetime.now(timezone.utc)


class _CtxPool:
    """Fake pool: conversation_history has a stale panel marker; the only
    panel row is 97 days old (journey) — the Lisa shape."""

    def __init__(self, history_rows, journey_row=None, delivery_row=None):
        self.history_rows = history_rows
        self.journey_row, self.delivery_row = journey_row, delivery_row

    async def fetch(self, sql, *args):
        if "FROM conversation_history" in sql:
            return self.history_rows
        return []

    async def fetchrow(self, sql, *args):
        if "FROM sse_panel_log" in sql and "panel_id = $1::uuid" in sql:
            return None
        if "FROM sse_delivery_generation_log" in sql and "log_id = $1::uuid" in sql:
            return None
        if "FROM sse_panel_log" in sql:
            return self.journey_row
        if "FROM sse_delivery_generation_log" in sql:
            return self.delivery_row
        if "FROM sse_user_journeys" in sql or "FROM users" in sql:
            return None
        return None

    async def fetchval(self, sql, *args):
        return None


PROFILE = {"hardware_id": "CLIENT_T_ID", "username": "tester"}


@pytest.mark.asyncio
async def test_release_phrase_returns_release_block_without_db():
    pool = _CtxPool([])
    text, ctx, img = await spc.build_sse_panel_chat_context(pool, PROFILE, "Let's talk about something else today")
    assert "[SSE PANEL RELEASED]" in ctx
    assert "Do not reference any prior journey panel scene" in ctx
    assert img is None


@pytest.mark.asyncio
async def test_plain_message_without_thread_gets_no_panel_context():
    pool = _CtxPool([{"user_text": "I had a hard day"}], journey_row=_old_journey())
    _, ctx, _ = await spc.build_sse_panel_chat_context(pool, PROFILE, "I had a hard day")
    assert ctx == ""


def _old_journey():
    return {
        "panel_id": "11111111-1111-1111-1111-111111111111",
        "panel_type": "journey",
        "r2_url": "mock://old.png",
        "narrative_text": "an old scene",
        "biome": "drift_valley",
        "character_manifest": "Scribe",
        "panel_tone": "calm",
        "crystal_domains_used": None,
        "generated_at": NOW - timedelta(days=97),
        "panel_metadata": None,
        "region": "origin",
    }


@pytest.mark.asyncio
async def test_followup_on_stale_fallback_adds_stale_note_not_continue(monkeypatch):
    async def _no_evidence(*a, **k):
        return {"chat": "", "crystals": "", "cycles": "", "reply_therapy": ""}
    monkeypatch.setattr(spc, "_gather_therapeutic_evidence", _no_evidence)
    history = [{"user_text": "(asking about my Sovereign Journey story panel image) what is this"}]
    pool = _CtxPool(history, journey_row=_old_journey())
    _, ctx, _ = await spc.build_sse_panel_chat_context(pool, PROFILE, "and then?")
    assert "[SSE PANEL STALE]" in ctx
    assert "No panel was minted today" in ctx
    assert "Continue THIS scene" not in ctx


@pytest.mark.asyncio
async def test_followup_prefers_todays_delivery_panel(monkeypatch):
    async def _no_evidence(*a, **k):
        return {"chat": "", "crystals": "", "cycles": "", "reply_therapy": ""}
    monkeypatch.setattr(spc, "_gather_therapeutic_evidence", _no_evidence)
    history = [{"user_text": "(asking about my Sovereign Journey story panel image) what is this"}]
    delivery = {
        "panel_id": "22222222-2222-2222-2222-222222222222",
        "generation_type": "daily_panel",
        "r2_url": "mock://today.png",
        "client_narrative_text": "a fresh chapter scene",
        "storyboard_id": "the_father_and_broken_sons",
        "generated_at": NOW - timedelta(hours=1),
    }
    pool = _CtxPool(history, journey_row=_old_journey(), delivery_row=delivery)
    _, ctx, _ = await spc.build_sse_panel_chat_context(pool, PROFILE, "and then?")
    assert "a fresh chapter scene" in ctx
    assert "an old scene" not in ctx
    assert "[SSE PANEL STALE]" not in ctx
    assert "Continue THIS scene" in ctx
