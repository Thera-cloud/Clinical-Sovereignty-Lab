"""Seam 3: Gmail drafts (no send), VaultBlocked, voice ingest, audio briefs."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[2]


class _FakeConn:
    def __init__(self):
        self.rows = []

    async def fetchrow(self, sql, *args):
        self.rows.append(("fetchrow", sql, args))
        return {"id": UUID("11111111-1111-1111-1111-111111111111")}

    async def execute(self, sql, *args):
        self.rows.append(("execute", sql, args))

    async def fetchval(self, sql, *args):
        return None


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
async def test_vault_blocked_never_calls_gmail(monkeypatch):
    from app.services.gmail_draft_service import create_coach_draft
    from app.services.google_workspace_service import VaultBlocked

    monkeypatch.setenv("ENABLE_WS_GMAIL_DRAFTS", "true")
    gmail = AsyncMock(return_value="draft_should_not")
    monkeypatch.setattr("app.services.gmail_draft_service.gmail_create_draft", gmail)
    monkeypatch.setattr(
        "app.services.gmail_draft_service.client_vault_sync",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.client_envelope_cipher.encrypt_for_client",
        AsyncMock(return_value="cipher"),
    )
    pool = _FakePool()
    with pytest.raises(VaultBlocked):
        await create_coach_draft(
            pool,
            "COACH_HW",
            {"client_id": "CLIENT_X", "body": "SSN 000-00-0000", "to": "a@b.c"},
            access_token="ya29.secret",
        )
    gmail.assert_not_awaited()
    assert any("email_drafts" in r[1] for r in pool.conn.rows)
    assert any(r[2][7] == "blocked" for r in pool.conn.rows if r[0] == "fetchrow")


@pytest.mark.asyncio
async def test_flag_off_skips_gmail_and_insert(monkeypatch):
    from app.services.gmail_draft_service import create_coach_draft
    from app.services.google_workspace_service import FlagOff

    monkeypatch.setenv("ENABLE_WS_GMAIL_DRAFTS", "false")
    gmail = AsyncMock(return_value="x")
    monkeypatch.setattr("app.services.gmail_draft_service.gmail_create_draft", gmail)
    pool = _FakePool()
    with pytest.raises(FlagOff):
        await create_coach_draft(pool, "COACH_HW", {"body": "hi"}, access_token="t")
    gmail.assert_not_awaited()
    assert pool.conn.rows == []


@pytest.mark.asyncio
async def test_vault_ok_pushes_drafts_create_only(monkeypatch):
    from app.services.gmail_draft_service import create_coach_draft

    monkeypatch.setenv("ENABLE_WS_GMAIL_DRAFTS", "true")
    gmail = AsyncMock(return_value="gd_1")
    monkeypatch.setattr("app.services.gmail_draft_service.gmail_create_draft", gmail)
    monkeypatch.setattr(
        "app.services.gmail_draft_service.client_vault_sync",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.client_envelope_cipher.encrypt_for_client",
        AsyncMock(return_value="cipher"),
    )
    pool = _FakePool()
    out = await create_coach_draft(
        pool,
        "COACH_HW",
        {"client_id": "CLIENT_X", "body": "ok", "to": "a@b.c", "subject": "Hi"},
        access_token="tok",
    )
    gmail.assert_awaited_once()
    assert out["gmail_draft_id"] == "gd_1"
    assert out["status"] == "pushed"
    assert out["encrypted"] is True


def test_gmail_draft_source_never_sends():
    src = (ROOT / "backend/app/services/gmail_draft_service.py").read_text()
    assert "users/me/drafts" in src
    assert "gmail.send" not in src.split('"""', 2)[-1]
    assert "/send" not in src.split('"""', 2)[-1]
    assert "messages.send" not in src.split('"""', 2)[-1]


def test_audio_synthesis_not_therapy_pipeline():
    src = (ROOT / "backend/app/services/audio_synthesis_service.py").read_text()
    body = src.split('"""', 2)[-1]
    assert "twilio_grok_xtts_pipeline" not in body
    assert "ENABLE_AUDIO_BRIEFS" in src
    brief = (ROOT / "backend/app/services/morning_brief_composer.py").read_text()
    assert "audio_synthesis_service" in brief


def test_morning_brief_script():
    from app.services.morning_brief_composer import compose_script

    s = compose_script(coach_name="Hope", tasks=[{"title": "Call Kim", "status": "open"}])
    assert "Hope" in s
    assert "Call Kim" in s


@pytest.mark.asyncio
async def test_voice_ingest_blocked_and_no_publish(monkeypatch):
    from app.services.google_workspace_service import FlagOff, VaultBlocked
    from app.services.voice_campaign_ingest import store_voice_recording

    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "false")
    with pytest.raises(FlagOff):
        await store_voice_recording(None, "COACH", "CLIENT", b"wav")
    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "true")
    monkeypatch.setattr(
        "app.services.voice_campaign_ingest.client_vault_sync",
        AsyncMock(return_value=False),
    )
    with pytest.raises(VaultBlocked):
        await store_voice_recording(_FakePool(), "COACH", "CLIENT", b"wav")


def test_migration_329_additive():
    sql = (ROOT / "backend/migrations/329_coach_voice_campaign.sql").read_text()
    assert "DROP TABLE" not in sql.upper()
    assert "DROP INDEX" not in sql.upper()
    assert "coach_voice_recordings" in sql
    assert "coach_voice_campaigns/" in (
        ROOT / "backend/app/services/voice_campaign_ingest.py"
    ).read_text()


@pytest.mark.asyncio
async def test_coach_self_ingest_skips_vault(monkeypatch):
    from app.services.voice_campaign_ingest import store_voice_recording

    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "true")
    vault = AsyncMock(return_value=False)
    monkeypatch.setattr("app.services.voice_campaign_ingest.client_vault_sync", vault)
    monkeypatch.setattr(
        "app.services.voice_campaign_ingest._transcribe",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        "app.services.voice_campaign_ingest.encrypt_coach_bytes",
        lambda data: "coach-cipher",
    )
    out = await store_voice_recording(_FakePool(), "COACH", "", b"wav-bytes")
    assert out["subject"] == "coach"
    assert out["published"] is False
    vault.assert_not_awaited()


@pytest.mark.asyncio
async def test_video_ingest_flag_off(monkeypatch):
    from app.services.google_workspace_service import FlagOff
    from app.services.voice_campaign_ingest import store_voice_recording

    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "true")
    monkeypatch.setenv("ENABLE_COACH_VIDEO_INGEST", "false")
    with pytest.raises(FlagOff):
        await store_voice_recording(
            _FakePool(), "COACH", "", b"mp4", media_kind="video", content_type="video/mp4"
        )


def test_migration_334_additive():
    sql = (ROOT / "backend/migrations/334_coach_campaign_windows.sql").read_text()
    assert "DROP TABLE" not in sql.upper()
    assert "ALTER COLUMN client_id DROP NOT NULL" in sql
    assert "length_days" in sql
    assert "style_json" in sql


@pytest.mark.asyncio
async def test_video_inherits_voice_when_unset(monkeypatch):
    from app.services.voice_campaign_ingest import store_voice_recording

    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "true")
    monkeypatch.delenv("ENABLE_COACH_VIDEO_INGEST", raising=False)
    monkeypatch.setattr(
        "app.services.voice_campaign_ingest.encrypt_coach_bytes",
        lambda data: "coach-cipher",
    )
    monkeypatch.setattr(
        "app.services.voice_campaign_ingest._transcribe",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        "app.services.voice_campaign_ingest._put_r2",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.coach_voice_profile_service.upsert_voice_profile",
        AsyncMock(return_value={}),
    )
    out = await store_voice_recording(
        _FakePool(),
        "COACH",
        "",
        b"mp4-bytes-here",
        media_kind="video",
        content_type="video/mp4",
    )
    assert out["media_kind"] == "video"
    assert out["subject"] == "coach"


@pytest.mark.asyncio
async def test_transcript_only_coach_ingest(monkeypatch):
    from app.services.voice_campaign_ingest import store_voice_recording

    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "true")
    monkeypatch.setattr(
        "app.services.voice_campaign_ingest.encrypt_coach_bytes",
        lambda data: "coach-cipher",
    )
    monkeypatch.setattr(
        "app.services.voice_campaign_ingest._put_r2",
        AsyncMock(return_value=False),
    )
    upsert = AsyncMock(return_value={"tone": "warm"})
    monkeypatch.setattr(
        "app.services.coach_voice_profile_service.upsert_voice_profile",
        upsert,
    )
    text = "I greet guarded clients slowly and I never diagnose in public copy."
    out = await store_voice_recording(
        _FakePool(), "COACH", "", b"", transcript=text
    )
    assert out["transcribed"] is True
    assert out["subject"] == "coach"
    upsert.assert_awaited()


@pytest.mark.asyncio
async def test_defer_heavy_returns_before_stt(monkeypatch):
    from app.services.voice_campaign_ingest import store_voice_recording

    async def _slow(*_a, **_k):
        await asyncio.sleep(30)
        return "late"

    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "true")
    monkeypatch.setattr(
        "app.services.voice_campaign_ingest.encrypt_coach_bytes",
        lambda data: "coach-cipher",
    )
    monkeypatch.setattr("app.services.voice_campaign_ingest._transcribe", _slow)
    monkeypatch.setattr(
        "app.services.voice_campaign_ingest._put_r2",
        AsyncMock(return_value=False),
    )
    out = await store_voice_recording(
        _FakePool(), "COACH", "", b"wav-bytes", defer_heavy=True
    )
    assert out["ok"] is True
    assert out.get("processing") is True
    assert out["transcribed"] is False
    current = asyncio.current_task()
    for task in asyncio.all_tasks():
        if task is not current and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


def test_style_merge_and_crystal_surface():
    from app.services.coach_voice_profile_service import merge_style

    merged = merge_style(
        {"topics": ["A"], "phrases": ["hi"], "version": 1},
        {"topics": ["B"], "tone": "warm", "assistant_stance": "steady"},
    )
    assert "A" in merged["topics"] and "B" in merged["topics"]
    assert merged["version"] == 2
    assert merged["source"] == "merged"
    src = (ROOT / "backend/app/services/coach_voice_profile_service.py").read_text()
    assert "subject = 'coach'" in src
    assert 'origin_surface="coach_voice_interview"' in src
    ingest = (ROOT / "backend/app/services/voice_campaign_ingest.py").read_text()
    enc = ingest.split("def encrypt_coach_bytes", 1)[1].split("def decrypt_coach_bytes", 1)[0]
    assert "TokenCipher.get" not in enc
    assert "_kek().encrypt" in enc
