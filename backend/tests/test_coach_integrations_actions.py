"""Integration write actions. No LinkedIn, Google, email, or live secret rotation."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


class _Conn:
    def __init__(self, row=None):
        self.sql = []
        self.args = []
        self.row = row

    async def fetchrow(self, query, *args):
        self.sql.append(query)
        self.args.append(args)
        return self.row

    async def execute(self, query, *args):
        self.sql.append(query)
        self.args.append(args)
        return "UPDATE 1"


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_exc):
        return False


class _Req:
    def __init__(self, pool, body=None):
        self.app = type("App", (), {})()
        self.app.state = type("State", (), {"db_pool": pool})()
        self._body = body or {}

    async def json(self):
        return self._body


def test_overview_list_paths_match_workspace_routes():
    dart = (ROOT / "mobile/lib/widgets/coach_integrations_hub.dart").read_text()
    api = (ROOT / "backend/app/routers/google_workspace_api.py").read_text()
    for path in ("/tasks", "/libraries", "/credentials"):
        assert f"path: '/api/workspace/google{path}'" in dart
        assert f'@router.get("{path}")' in api
    assert "Could not load" in dart
    assert "Vault sync failed" in dart


@pytest.mark.asyncio
async def test_review_approves_without_publishing(monkeypatch):
    from app.services.voice_campaign_generator import set_review_status

    async def _skip(*_a, **_k):
        return None

    monkeypatch.setattr(
        "app.services.coach_voice_profile_service.crystallize_approved_draft",
        _skip,
    )
    conn = _Conn(
        {
            "id": 7,
            "status": "approved",
            "post_urn": "",
            "title": "t",
            "draft_body": "b",
            "audience": "clients",
        }
    )
    out = await set_review_status(_Pool(conn), 7, coach_id="COACH_HW", status="approved")
    assert out == {"ok": True, "id": 7, "status": "approved", "published": False}
    assert "post_urn" not in conn.sql[0].split("SET", 1)[1].split("WHERE", 1)[0]


@pytest.mark.asyncio
async def test_publish_refuses_unapproved_and_skips_linkedin(monkeypatch):
    from app.services.coach_linkedin_publisher import publish_approved_post

    monkeypatch.setenv("ENABLE_COACH_LINKEDIN", "true")
    calls = {"n": 0}

    async def _token(*_a, **_k):
        return "token"

    async def _post(*_a, **_k):
        calls["n"] += 1
        return "urn"

    monkeypatch.setattr(
        "app.services.coach_linkedin_publisher.load_coach_linkedin_token", _token
    )
    monkeypatch.setattr(
        "app.services.coach_linkedin_publisher.linkedin_ugc_post", _post
    )
    conn = _Conn(
        {
            "id": 3,
            "title": "t",
            "draft_body": "b",
            "status": "draft",
            "content_type": "linkedin_post",
            "person_urn": "urn:li:person:x",
        }
    )
    out = await publish_approved_post(_Pool(conn), coach_id="COACH_HW", content_id=3)
    assert out["ok"] is False
    assert out["reason"] == "not_approved_linkedin_post"
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_publish_flag_off(monkeypatch):
    from app.services.coach_linkedin_publisher import publish_approved_post
    from app.services.google_workspace_service import FlagOff

    monkeypatch.setenv("ENABLE_COACH_LINKEDIN", "false")
    with pytest.raises(FlagOff):
        await publish_approved_post(None, coach_id="COACH_HW", content_id=1)


@pytest.mark.asyncio
async def test_generate_rejects_bad_audience_and_non_master(monkeypatch):
    from app.services.voice_campaign_generator import generate_campaign

    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "true")
    with pytest.raises(ValueError):
        await generate_campaign(None, "COACH_HW", title="T", audience="public")

    async def _not_master(*_a, **_k):
        return False

    monkeypatch.setattr(
        "app.services.voice_campaign_generator.coach_is_master", _not_master
    )
    with pytest.raises(PermissionError):
        await generate_campaign(
            object(), "COACH_HW", title="T", audience="assistant_coaches"
        )


@pytest.mark.asyncio
async def test_voice_ingest_blocks_when_vault_sync_off(monkeypatch):
    from app.services.google_workspace_service import VaultBlocked
    from app.services.voice_campaign_ingest import store_voice_recording

    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "true")

    async def _off(*_a, **_k):
        return False

    monkeypatch.setattr(
        "app.services.voice_campaign_ingest.client_vault_sync", _off
    )
    with pytest.raises(VaultBlocked):
        await store_voice_recording(
            object(),
            "COACH_HW",
            "CLIENT_HW",
            b"abc",
            content_type="audio/webm",
            defer_heavy=True,
        )


@pytest.mark.asyncio
async def test_video_ingest_respects_flag(monkeypatch):
    from app.services.google_workspace_service import FlagOff
    from app.services.voice_campaign_ingest import store_voice_recording

    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "true")
    monkeypatch.setenv("ENABLE_COACH_VIDEO_INGEST", "false")
    with pytest.raises(FlagOff):
        await store_voice_recording(
            object(),
            "COACH_HW",
            "",
            b"abc",
            media_kind="video",
            content_type="video/mp4",
        )


@pytest.mark.asyncio
async def test_task_flag_and_scope(monkeypatch):
    from app.services.coach_task_service import create_task
    from app.services.google_workspace_service import FlagOff

    monkeypatch.setenv("ENABLE_COACH_TASKS", "false")
    with pytest.raises(FlagOff):
        await create_task(object(), "COACH_HW", client_id="CLIENT_HW", title="Call")

    monkeypatch.setenv("ENABLE_COACH_TASKS", "true")

    async def _out(*_a, **_k):
        return False

    monkeypatch.setattr("app.services.coach_task_service.client_in_scope", _out)
    with pytest.raises(PermissionError):
        await create_task(object(), "COACH_HW", client_id="CLIENT_HW", title="Call")


@pytest.mark.asyncio
async def test_crisis_and_clone_stay_idle_when_flags_off(monkeypatch):
    from app.services.coach_campaign_clone import register_clone
    from app.services.crisis_escalation import escalate
    from app.services.google_workspace_service import FlagOff

    monkeypatch.setenv("ENABLE_CRISIS_ESCALATION", "false")
    monkeypatch.setenv("ENABLE_COACH_VOICE_CLONE", "false")
    with pytest.raises(FlagOff):
        await escalate(None, coach_id="COACH_HW", client_id="CLIENT_HW", note="check")
    assert await register_clone(b"x" * 300, "COACH_HW") is False


@pytest.mark.asyncio
async def test_crisis_queues_locally_when_flag_on(monkeypatch):
    from app.services.crisis_escalation import escalate

    monkeypatch.setenv("ENABLE_CRISIS_ESCALATION", "true")
    conn = _Conn()
    out = await escalate(
        _Pool(conn), coach_id="COACH_HW", client_id="CLIENT_HW", note="check in"
    )
    assert out["ok"] is True and out["queued"] is True
    assert "skyeye_activity" in conn.sql[0]
    assert "crisis_escalation" in conn.args[0]


@pytest.mark.asyncio
async def test_vault_sync_scope_and_rotate_stores_ciphertext(monkeypatch):
    import os

    from fastapi import HTTPException

    os.environ.setdefault("JWT_SECRET", "integration-action-test-secret")
    from app.routers.coach_integrations_api import rotate_studio_secret, set_vault_sync

    async def _out(*_a, **_k):
        return False

    monkeypatch.setattr("app.services.effective_scope.client_in_scope", _out)
    with pytest.raises(HTTPException) as denied:
        await set_vault_sync(
            "CLIENT_HW",
            _Req(_Pool(_Conn()), {"vault_sync": True}),
            {"hardware_id": "COACH_HW", "role": "COACH"},
        )
    assert denied.value.status_code == 403

    async def _in(*_a, **_k):
        return True

    monkeypatch.setattr("app.services.effective_scope.client_in_scope", _in)
    conn = _Conn()
    out = await set_vault_sync(
        "CLIENT_HW",
        _Req(_Pool(conn), {"vault_sync": True}),
        {"hardware_id": "COACH_HW", "role": "COACH"},
    )
    assert out["vault_sync"] is True
    assert "UPDATE users SET vault_sync" in conn.sql[0]

    class _Cipher:
        def encrypt(self, text):
            return "enc:" + text

    class _TokenCipher:
        @staticmethod
        def get():
            return _Cipher()

    monkeypatch.setattr(
        "app.services.skyeye_platform_base.TokenCipher", _TokenCipher
    )
    secret_conn = _Conn()
    rotated = await rotate_studio_secret(
        _Req(_Pool(secret_conn)),
        {"hardware_id": "COACH_HW", "role": "COACH"},
    )
    stored = secret_conn.args[0][1]
    assert rotated["secret"]
    assert stored == "enc:" + rotated["secret"]
    assert stored != rotated["secret"]
    assert "secret_ciphertext" in secret_conn.sql[0]
