import importlib.util
import os
import sys
import uuid
from datetime import datetime, timezone

import pytest


_SERVICES = os.path.join(os.path.dirname(__file__), "..", "app", "services")


def _load(name: str, filename: str):
    path = os.path.join(_SERVICES, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_sse = _load("sse_panel_chat_context_test", "sse_panel_chat_context.py")
build_sse_panel_chat_context = _sse.build_sse_panel_chat_context


class _FakeDB:
    def __init__(self, row=None, chat_rows=None, crystal_rows=None, cycle_rows=None,
                 reply_therapy=None, delivery_row=None):
        self._row = row
        self._chat_rows = chat_rows or []
        self._crystal_rows = crystal_rows or []
        self._cycle_rows = cycle_rows or []
        self._reply_therapy = reply_therapy
        self._delivery_row = delivery_row
        self._user_uuid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    async def fetchrow(self, query, *_args, **_kwargs):
        q = " ".join(query.split()).lower()
        if "from sse_panel_log" in q:
            return self._row
        if "from sse_delivery_generation_log" in q:
            return self._delivery_row
        if "reply_therapy" in q:
            if self._reply_therapy is None:
                return None
            return {"reply_therapy": self._reply_therapy}
        return None

    async def fetch(self, query, *_args, **_kwargs):
        q = " ".join(query.split()).lower()
        if "from conversation_history" in q:
            return self._chat_rows
        if "from nate_intelligence_crystals" in q:
            return self._crystal_rows
        if "from cycle_detections" in q:
            return self._cycle_rows
        return []

    async def fetchval(self, query, *_args, **_kwargs):
        q = " ".join(query.split()).lower()
        if "select id from users" in q:
            return self._user_uuid
        return None


@pytest.mark.asyncio
async def test_sse_panel_ref_injects_character_map_and_themes():
    row = {
        "panel_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "panel_type": "journey",
        "r2_url": None,
        "narrative_text": "In the open sky, Curiosity waits by an open door.",
        "biome": "open_sky",
        "character_manifest": "Curiosity",
        "panel_tone": "meditative",
        "crystal_domains_used": {"themes": ["loneliness", "growth", "wonder"], "domains": ["clinical"]},
        "generated_at": datetime(2026, 6, 25, tzinfo=timezone.utc),
    }
    chat_rows = [
        {"user_text": "I feel alone even when people are around.", "ai_text": "...", "created_at": datetime(2026, 6, 24, tzinfo=timezone.utc)},
    ]
    crystal_rows = [
        {"crystal_text": "Client opens up about loneliness and wonder.", "domain": "clinical", "confidence": 0.72, "created_at": datetime(2026, 6, 1, tzinfo=timezone.utc)},
    ]
    db = _FakeDB(row=row, chat_rows=chat_rows, crystal_rows=crystal_rows)
    profile = {"hardware_id": "CLIENT_1_ID", "username": "client1"}
    text = "[SSE Panel:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee] Explain this image"
    new_text, ctx, img = await build_sse_panel_chat_context(db, profile, text)
    assert "Sovereign Journey story panel" in new_text
    assert "[SSE Panel:" not in new_text
    assert "MEMORY → CORE CHARACTER MAP" in ctx
    assert "Core character manifested: Curiosity" in ctx
    assert "loneliness" in ctx
    assert "DEEP REFLECTION PROTOCOL" in ctx
    assert "SIFT" in ctx
    assert "Three focus topics for today" in ctx
    assert "RECENT CHAT" in ctx
    assert "alone even when people" in ctx
    assert "CRYSTAL HISTORY" in ctx
    assert img is None


@pytest.mark.asyncio
async def test_legacy_story_panel_gets_map_without_db_row():
    db = _FakeDB(row=None)
    profile = {"hardware_id": "CLIENT_1_ID"}
    text = "[Story Panel: journey] Biome: open sky. What does the serpent mean?"
    _new_text, ctx, img = await build_sse_panel_chat_context(db, profile, text)
    assert "MEMORY → CORE CHARACTER MAP" in ctx
    assert "Serpent" in ctx
    assert "DEEP REFLECTION PROTOCOL" in ctx
    assert img is None


@pytest.mark.asyncio
async def test_reply_therapy_snapshot_in_context():
    row = {
        "panel_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "panel_type": "journey",
        "r2_url": None,
        "narrative_text": "Mirror reflects two paths.",
        "biome": "forest",
        "character_manifest": "Mirror",
        "panel_tone": "gentle",
        "crystal_domains_used": {"themes": ["trust"], "domains": ["clinical"]},
        "generated_at": datetime(2026, 6, 25, tzinfo=timezone.utc),
    }
    reply_therapy = {
        "active_reply_theme": "abandonment",
        "themes": {
            "abandonment": {
                "mismatch_count": 3,
                "reconsolidation_count": 2,
                "evocative_recall_count": 1,
                "threshold_met": False,
                "mismatch_events": [{"preview": "They left when I needed them most."}],
            }
        },
    }
    db = _FakeDB(row=row, reply_therapy=reply_therapy)
    profile = {"hardware_id": "CLIENT_1_ID", "username": "client1"}
    text = "[SSE Panel:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee] Explain"
    _new_text, ctx, _img = await build_sse_panel_chat_context(db, profile, text)
    assert "REPLY THERAPY 3+3+3" in ctx
    assert "abandonment" in ctx
    assert "left when I needed" in ctx


@pytest.mark.asyncio
async def test_delivery_log_panel_resolves_by_log_id():
    delivery_row = {
        "log_id": uuid.UUID("11111111-2222-3333-4444-555555555555"),
        "generation_type": "weekly_clip",
        "r2_url": None,
        "client_narrative_text": "A moving moment from your week on the path.",
        "storyboard_id": "sb_lisa",
        "generated_at": datetime(2026, 6, 28, tzinfo=timezone.utc),
    }
    db = _FakeDB(row=None, delivery_row=delivery_row)
    profile = {"hardware_id": "CLIENT_1_ID", "username": "client1"}
    text = "[SSE Panel:11111111-2222-3333-4444-555555555555] Explain this"
    new_text, ctx, _img = await build_sse_panel_chat_context(db, profile, text)
    assert "[SSE Panel:" not in new_text
    # Resolved via delivery log → full panel block, not the no-row fallback
    assert "SOVEREIGN JOURNEY PANEL — client asked about this image" in ctx
    assert "moving moment from your week" in ctx
    assert "Core character manifested: Mirror" in ctx
    assert "DEEP REFLECTION PROTOCOL" in ctx


@pytest.mark.asyncio
async def test_daily_panel_infers_serpent_from_narrative():
    narrative = (
        "You stand at the river's bend with the Cartographer refining his map when "
        "the Archivist kneels nearby. The Serpent rises from the crystal waters."
    )
    delivery_row = {
        "log_id": uuid.UUID("ea20896b-7220-499b-9ee9-d40ad1e190a5"),
        "generation_type": "daily_panel",
        "r2_url": None,
        "client_narrative_text": narrative,
        "storyboard_id": "sb_lisa",
        "generated_at": datetime(2026, 7, 2, tzinfo=timezone.utc),
    }
    db = _FakeDB(row=None, delivery_row=delivery_row)
    profile = {"hardware_id": "CLIENT_001", "username": "JohnD"}
    text = f"[SSE Panel:ea20896b-7220-499b-9ee9-d40ad1e190a5] Explain symbols"
    _new_text, ctx, _img = await build_sse_panel_chat_context(db, profile, text)
    assert "Core character manifested: Serpent" in ctx
    assert "Cartographer" in ctx
    assert "Never claim a figure is absent" in ctx
    assert "SSE PANEL CONTRACT" in ctx
    assert "WRITE THIS BEFORE SIFT" in ctx


def test_http_get_bytes_is_sync_not_coroutine():
    import inspect
    assert inspect.iscoroutinefunction(_sse._http_get_bytes) is False


def test_ensure_three_focus_topics_completes_cutoff():
    ctx = (
        "Core character manifested: Curiosity\n"
        "Crystal themes that drove this panel: loneliness, growth\n"
        "[SOVEREIGN JOURNEY DEEP REFLECTION PROTOCOL — follow this structure in your reply]\n"
    )
    cut = (
        "SIFT is a doorway.\n"
        "For today, here are three focus topics for reflection or journaling:\n"
        "1."
    )
    out = _sse.ensure_three_focus_topics(cut, ctx)
    assert _sse.focus_topics_complete(out)
    assert "1." in out and "2." in out and "3." in out
    assert out.count("1.") >= 1


def test_ensure_three_focus_topics_leaves_complete_alone():
    ctx = "[SOVEREIGN JOURNEY DEEP REFLECTION PROTOCOL — follow this structure in your reply]"
    ok = "Intro.\n1. First complete topic here today.\n2. Second complete topic here today.\n3. Third complete topic here today.\n"
    assert _sse.ensure_three_focus_topics(ok, ctx) == ok


def test_sse_should_complete_on_panel_rewrite_and_cut_followup():
    ctx = "[SOVEREIGN JOURNEY DEEP REFLECTION PROTOCOL — follow this structure in your reply]"
    assert _sse.sse_should_complete_focus_topics(
        "I am curious.(asking about my Sovereign Journey story panel image)", ctx
    )
    assert _sse.sse_should_complete_focus_topics(
        "thank you, the 3 Focus topics got cut off. Could you please post them again?", ctx
    )
    assert not _sse.sse_should_complete_focus_topics("hi", ctx)


@pytest.mark.asyncio
async def test_focus_topic_followup_reinjects_latest_panel():
    row = {
        "panel_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "panel_type": "journey",
        "r2_url": None,
        "narrative_text": "Curiosity waits by an open door.",
        "biome": "open_sky",
        "character_manifest": "Curiosity",
        "panel_tone": "meditative",
        "crystal_domains_used": {"themes": ["loneliness"], "domains": ["clinical"]},
        "generated_at": datetime(2026, 6, 25, tzinfo=timezone.utc),
    }
    db = _FakeDB(row=row)
    profile = {"hardware_id": "CLIENT_1_ID", "username": "client1"}
    text = "thank you, little Nate, the 3 Focus topics got cut off. Could you please post them again?"
    new_text, ctx, img = await build_sse_panel_chat_context(db, profile, text)
    assert new_text == text
    assert "DEEP REFLECTION PROTOCOL" in ctx
    assert "SSE PANEL FOLLOW-UP" in ctx
    assert "Curiosity" in ctx
    assert img is None


@pytest.mark.asyncio
async def test_short_ack_reinjects_when_recent_panel_thread():
    row = {
        "panel_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "panel_type": "journey",
        "r2_url": None,
        "narrative_text": "Mirror reflects two paths.",
        "biome": "forest",
        "character_manifest": "Mirror",
        "panel_tone": "gentle",
        "crystal_domains_used": {"themes": ["trust"], "domains": ["clinical"]},
        "generated_at": datetime(2026, 6, 25, tzinfo=timezone.utc),
    }
    chat_rows = [
        {
            "user_text": "(asking about my Sovereign Journey story panel image)",
            "ai_text": "For today, here are three focus topics: 1.",
            "created_at": datetime(2026, 8, 28, tzinfo=timezone.utc),
        },
    ]
    db = _FakeDB(row=row, chat_rows=chat_rows)
    profile = {"hardware_id": "CLIENT_1_ID", "username": "client1"}
    _new_text, ctx, _img = await build_sse_panel_chat_context(db, profile, "for me or for you")
    assert "DEEP REFLECTION PROTOCOL" in ctx
    assert "SSE PANEL FOLLOW-UP" in ctx


@pytest.mark.asyncio
async def test_plain_hi_does_not_reinject_panel():
    db = _FakeDB(row=None)
    profile = {"hardware_id": "CLIENT_1_ID"}
    new_text, ctx, img = await build_sse_panel_chat_context(db, profile, "hi")
    assert new_text == "hi"
    assert ctx == ""
    assert img is None
