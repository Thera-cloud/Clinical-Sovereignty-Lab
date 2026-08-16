"""Coach campaign Preview / Edit / Photo (Dispatch-condensed)."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[2]


class _FakeConn:
    def __init__(self, row=None):
        self.calls = []
        self.row = row or {
            "id": 7,
            "title": "Campaign — LinkedIn day 0",
            "content_type": "linkedin_post",
            "status": "pending_review",
            "campaign_id": None,
            "coach_id": "COACH_HW",
            "post_urn": None,
            "draft_body": "Invite a conversation.",
            "hero_image_prompt": "",
            "hero_image_url": None,
            "hero_image_r2_key": None,
            "hero_image_generated_at": None,
            "updated_at": None,
            "created_at": None,
        }

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        if "UPDATE" in sql and "not_this" in sql:
            return None
        return self.row

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return None


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, row=None):
        self.conn = _FakeConn(row)

    def acquire(self):
        return _Acquire(self.conn)


def test_default_prompt_is_editorial_not_clinical():
    from app.services.coach_campaign_editor import default_hero_prompt

    p = default_hero_prompt("Presence", "linkedin_post", "invite")
    assert "linkedin post" in p.lower()
    assert "no photorealistic identifiable faces" in p
    assert "Little Nate Dispatch" not in p


def test_preview_html_escapes_and_embeds_image():
    from app.services.coach_campaign_editor import render_preview_html

    html = render_preview_html(
        {"title": "<x>", "content_type": "drip_touch", "draft_body": "a & b"},
        hero_data_uri="data:image/png;base64,AAA",
    )
    assert "&lt;x&gt;" in html
    assert "a &amp; b" in html
    assert "data:image/png;base64,AAA" in html
    assert "#C9A962" in html


@pytest.mark.asyncio
async def test_update_item_scopes_to_coach_and_editable_status():
    from app.services.coach_campaign_editor import update_item

    pool = _FakePool()
    out = await update_item(
        pool, 7, coach_id="COACH_HW", title="New", draft_body="Body"
    )
    assert out["ok"] is True
    sql = pool.conn.calls[0][1]
    assert "coach_id" in sql
    assert "post_urn" in sql
    assert "pending_review" in str(pool.conn.calls[0][2]) or "ANY" in sql


@pytest.mark.asyncio
async def test_generate_hero_mocked(monkeypatch, tmp_path):
    from app.services import coach_campaign_editor as ed

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ENABLE_NEWSLETTER_HERO_IMAGE", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    async def _bytes(prompt):
        return (b"\x89PNG\r\n\x1a\n" + b"0" * 600, "gemini")

    monkeypatch.setattr(
        "app.services.newsletter_imagery.generate_hero_bytes", _bytes
    )
    monkeypatch.setattr(
        "app.services.newsletter_imagery.hero_enabled", lambda: True
    )
    r2 = AsyncMock()
    monkeypatch.setattr("app.services.r2_storage.upload_bytes_async", r2)

    pool = _FakePool()
    out = await ed.generate_hero(pool, 7, coach_id="COACH_HW", prompt_override="lantern")
    assert out["ok"] is True
    assert out["provider"] == "gemini"
    assert (tmp_path / "coach_campaigns" / "7-hero.png").is_file()


@pytest.mark.asyncio
async def test_rewrite_item_requires_instruction_and_does_not_save():
    from app.services.coach_campaign_editor import rewrite_item

    pool = _FakePool()
    short = await rewrite_item(pool, 7, coach_id="COACH_HW", instruction="fix")
    assert short["ok"] is False
    assert short["reason"] == "instruction_too_short"


def test_style_schema_has_writing_structure():
    from app.services.coach_voice_profile_service import heuristic_style, merge_style

    h = heuristic_style(
        "I greet slowly. I name the feeling. We stay with one question. "
        "I never rush grief. The door stays open."
    )
    for key in (
        "preface_style",
        "introduction_style",
        "body_style",
        "climax_style",
        "conclusion_style",
        "word_patterns",
    ):
        assert key in h
    merged = merge_style(
        h,
        {
            "preface_style": "quiet hello",
            "tone": "warm",
            "presence_style": "slow, warm, leaves space",
            "voice_biometrics": {"voice_warmth_index": 0.7, "pause_ratio": 0.3},
        },
    )
    assert merged["preface_style"] == "quiet hello"
    assert merged["body_style"]
    assert merged["presence_style"].startswith("slow")
    assert merged["voice_biometrics"]["voice_warmth_index"] == 0.7


def test_wav_pcm_and_presence_mapping():
    import io
    import math
    import struct
    import wave

    from app.services.coach_voice_biometrics import (
        pcm16_from_wav,
        presence_from_metrics,
        style_presence_block,
    )

    buf = io.BytesIO()
    rate = 16000
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(4000 * math.sin(2 * math.pi * 220 * i / rate)))
            for i in range(rate)
        )
        wav.writeframes(frames)
    pcm, got_rate = pcm16_from_wav(buf.getvalue())
    assert got_rate == 16000
    assert len(pcm) >= 512
    warm = presence_from_metrics(
        {
            "voice_warmth_index": 0.7,
            "pause_ratio": 0.3,
            "speech_rate": 90,
            "voice_stress_index": 0.2,
        }
    )
    assert "space" in warm["presence_style"]
    assert warm["cadence"] == "unhurried"
    block = style_presence_block(warm)
    assert "Spoken presence" in block
    assert "biometrics" in block.lower() or "pace" in block.lower()


def test_api_and_flutter_wire_preview_edit_photo():
    api = (ROOT / "backend/app/routers/coach_integrations_api.py").read_text()
    assert "/campaigns/{content_id}/preview" in api
    assert "/campaigns/{content_id}/generate-image" in api
    assert "/campaigns/{content_id}/rewrite" in api
    assert "update_campaign_item" in api
    dart = (ROOT / "mobile/lib/widgets/coach_integrations_hub.dart").read_text()
    assert "Preview" in dart
    assert "Edit draft" in dart
    assert "Rewrite in my voice" in dart
    assert "Tell Nate what to change" in dart
    assert "Generate photo" in dart
    assert "Image descriptor" in dart
    assert "Record interview" in dart
    assert "coach_web_recorder.dart" in dart
    bio = (ROOT / "backend/app/services/coach_voice_biometrics.py").read_text()
    assert "VoiceBiometricExtractor" in bio
    assert "faster-whisper" not in bio
    ingest = (ROOT / "backend/app/services/voice_campaign_ingest.py").read_text()
    assert "extract_campaign_biometrics" in ingest
    assert "COACH_CAMPAIGN_STT_URL" in ingest
    sql = (ROOT / "backend/migrations/333_coach_campaign_item_editor.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS hero_image_prompt" in sql
    assert "DROP" not in sql.upper()
