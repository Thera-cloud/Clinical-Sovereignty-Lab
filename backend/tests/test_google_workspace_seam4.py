"""Seam 4: campaign generation lands in pending_review. No LinkedIn publish."""

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[2]


class _FakeConn:
    def __init__(self):
        self.calls = []
        self._n = 0

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        if "coach_marketing_campaigns" in sql and "INSERT" in sql:
            return {"id": UUID("22222222-2222-2222-2222-222222222222")}
        self._n += 1
        return {"id": self._n, "status": args[0] if "UPDATE" in sql else "pending_review", "post_urn": None}

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return []

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return getattr(self, "master_count", 0)


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self):
        self.conn = _FakeConn()

    def acquire(self):
        return _Acquire(self.conn)


@pytest.mark.asyncio
async def test_flag_off_skips_generation(monkeypatch):
    from app.services.google_workspace_service import FlagOff
    from app.services.voice_campaign_generator import generate_campaign

    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "false")
    pool = _FakePool()
    with pytest.raises(FlagOff):
        await generate_campaign(pool, "COACH_HW", title="Q3")
    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_generate_enqueues_pending_review_not_published(monkeypatch):
    from app.services.voice_campaign_generator import generate_campaign

    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "true")
    monkeypatch.setenv("ENABLE_COACH_NEWSLETTER", "false")
    pool = _FakePool()
    out = await generate_campaign(pool, "COACH_HW", title="Presence")
    assert out["published"] is False
    assert out["status"] == "pending_review"
    assert len(out["content_ids"]) == 2
    inserts = [c for c in pool.conn.calls if c[0] == "fetchrow" and "marketing_content" in c[1]]
    for _, sql, args in inserts:
        assert "pending_review" in args
        assert "published" not in args


@pytest.mark.asyncio
async def test_newsletter_gated(monkeypatch):
    from app.services.voice_campaign_generator import compose_day_n_pieces

    monkeypatch.setenv("ENABLE_COACH_NEWSLETTER", "false")
    types = {p["content_type"] for p in compose_day_n_pieces("T")}
    assert "newsletter_issue" not in types
    monkeypatch.setenv("ENABLE_COACH_NEWSLETTER", "true")
    types = {p["content_type"] for p in compose_day_n_pieces("T")}
    assert "newsletter_issue" in types


@pytest.mark.asyncio
async def test_approve_does_not_publish(monkeypatch):
    from app.services.voice_campaign_generator import set_review_status

    pool = _FakePool()
    out = await set_review_status(pool, 9, coach_id="COACH_HW", status="approved")
    assert out["published"] is False
    sql = pool.conn.calls[0][1]
    set_clause = sql.lower().split("set", 1)[1].split("where", 1)[0]
    assert "post_urn" not in set_clause
    assert "published" not in set_clause


@pytest.mark.asyncio
async def test_assistant_audience_requires_master(monkeypatch):
    from app.services.voice_campaign_generator import generate_campaign

    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "true")
    pool = _FakePool()
    pool.conn.master_count = 0
    with pytest.raises(PermissionError):
        await generate_campaign(
            pool, "COACH_HW", title="Train", audience="assistant_coaches"
        )


@pytest.mark.asyncio
async def test_length_days_unique_bodies(monkeypatch):
    from app.services.voice_campaign_generator import generate_campaign

    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "true")
    monkeypatch.setenv("ENABLE_COACH_NEWSLETTER", "false")
    pool = _FakePool()
    out = await generate_campaign(pool, "COACH_HW", title="Presence", length_days=3)
    assert out["length_days"] == 3
    assert len(out["content_ids"]) == 6
    bodies = [
        c[2][4]
        for c in pool.conn.calls
        if c[0] == "fetchrow" and "marketing_content" in c[1]
    ]
    assert len(bodies) == len(set(bodies))


def test_generator_links_style_crystals_and_schedule():
    src = (ROOT / "backend/app/services/voice_campaign_generator.py").read_text()
    assert "recall_crystals_for_context" in src
    assert 'source="coach_voice_interview"' in src
    assert "ORDER BY scheduled_at" in src
    assert "crystallize_approved_draft" in src
    assert "assistant_stance" in src
    assert "NateResponseValidator" in src


def test_generator_source_has_no_publishers():
    src = (ROOT / "backend/app/services/voice_campaign_generator.py").read_text()
    assert "skyeye_platform_tokens" not in src
    assert "linkedin" in src  # content_type / platform labels only
    assert "LinkedInAdapter" not in src
    assert "gmail.send" not in src
    assert "messages.send" not in src
    assert "ENABLE_VOICE_CAMPAIGN" in src
