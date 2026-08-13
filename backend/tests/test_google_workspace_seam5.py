"""Seam 5: per-coach LinkedIn, History poll, Drive encrypt, SendGrid markers."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[2]


class _FakeConn:
    def __init__(self):
        self.calls = []

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        if "coach_linkedin_connection" in sql and "SELECT access_token" in sql:
            return None
        return {"id": 1}

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))


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
async def test_linkedin_missing_token_stays_in_queue(monkeypatch):
    from app.services.coach_linkedin_publisher import publish_approved_post

    monkeypatch.setenv("ENABLE_COACH_LINKEDIN", "true")
    ugc = AsyncMock(return_value="urn:li:share:1")
    monkeypatch.setattr("app.services.coach_linkedin_publisher.linkedin_ugc_post", ugc)
    out = await publish_approved_post(_FakePool(), coach_id="COACH_HW", content_id=9)
    assert out["reason"] == "connect_linkedin"
    assert out["published"] is False
    ugc.assert_not_awaited()


def test_linkedin_never_reads_skyeye_tokens():
    src = (ROOT / "backend/app/services/coach_linkedin_publisher.py").read_text()
    assert "FROM skyeye_platform_tokens" not in src
    assert "skyeye_platform_tokens" not in src
    assert "coach_linkedin_connection" in src


def test_gmail_history_no_watch_or_send():
    src = (ROOT / "backend/app/services/gmail_reply_listener.py").read_text()
    body = src.split('"""', 2)[-1]
    assert "users/me/history" in src
    assert "users.watch" not in body
    assert "/watch" not in body
    assert "gmail.send" not in body
    assert "messages.send" not in body


@pytest.mark.asyncio
async def test_drive_vault_blocked_skips_google(monkeypatch):
    from app.services.drive_workspace_writer import write_client_file
    from app.services.google_workspace_service import VaultBlocked

    monkeypatch.setenv("ENABLE_WS_DRIVE_DELIVERY", "true")
    drive = AsyncMock(return_value="file_should_not")
    monkeypatch.setattr("app.services.drive_workspace_writer.drive_create_file", drive)
    monkeypatch.setattr(
        "app.services.drive_workspace_writer.client_vault_sync",
        AsyncMock(return_value=False),
    )
    with pytest.raises(VaultBlocked):
        await write_client_file(
            _FakePool(), "COACH", "CLIENT", content=b"PII", access_token="tok"
        )
    drive.assert_not_awaited()


@pytest.mark.asyncio
async def test_drip_marker_flag_and_no_send(monkeypatch):
    from app.services.campaign_drip_markers import enqueue_drip_marker
    from app.services.google_workspace_service import FlagOff

    monkeypatch.setenv("ENABLE_CAMPAIGN_NUDGES", "false")
    with pytest.raises(FlagOff):
        await enqueue_drip_marker(_FakePool(), coach_id="C", content_id=1)
    monkeypatch.setenv("ENABLE_CAMPAIGN_NUDGES", "true")
    out = await enqueue_drip_marker(_FakePool(), coach_id="C", content_id=1)
    assert out["channel"] == "sendgrid"
    assert out["sent"] is False


def test_migration_330_additive():
    sql = (ROOT / "backend/migrations/330_coach_linkedin_gmail_history.sql").read_text()
    assert "DROP TABLE" not in sql.upper()
    assert "coach_linkedin_connection" in sql
    assert "gmail_history_id" in sql
    assert "skyeye_platform_tokens" not in sql


def test_canonicalize_duplicate_linkedin_host(monkeypatch):
    from app.services.coach_linkedin_oauth import canonicalize_linkedin_redirect

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.sovereignsanctuary.net")
    dup = (
        "https://api.sovereignsanctuary.net/api.sovereignsanctuary.net"
        "/api/skyeye/platforms/linkedin/callback"
    )
    out = canonicalize_linkedin_redirect(dup)
    assert out.count("api.sovereignsanctuary.net") == 1
    assert out.endswith("/api/skyeye/platforms/linkedin/callback")


def test_skyeye_app_uses_registered_redirect(monkeypatch):
    from app.services.coach_linkedin_oauth import coach_linkedin_credentials

    monkeypatch.delenv("LINKEDIN_COACH_CLIENT_ID", raising=False)
    monkeypatch.delenv("LINKEDIN_COACH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("LINKEDIN_COACH_REGISTERED_REDIRECT_URI", raising=False)
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "77wz5scwctl85s")
    monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv(
        "LINKEDIN_COACH_REDIRECT_URI",
        "https://api.sovereignsanctuary.net/api/coach/integrations/linkedin/callback",
    )
    cid, secret, redirect = coach_linkedin_credentials()
    assert cid == "77wz5scwctl85s"
    assert secret == "secret"
    assert redirect.endswith("/api/skyeye/platforms/linkedin/callback")
    assert "/api/coach/integrations/linkedin/callback" not in redirect


def test_dedicated_coach_app_uses_coach_callback(monkeypatch):
    from app.services.coach_linkedin_oauth import coach_linkedin_credentials

    monkeypatch.setenv("LINKEDIN_COACH_CLIENT_ID", "coach-app")
    monkeypatch.setenv("LINKEDIN_COACH_CLIENT_SECRET", "coach-secret")
    monkeypatch.setenv(
        "LINKEDIN_COACH_REDIRECT_URI",
        "https://api.sovereignsanctuary.net/api/coach/integrations/linkedin/callback",
    )
    cid, secret, redirect = coach_linkedin_credentials()
    assert cid == "coach-app"
    assert secret == "coach-secret"
    assert redirect.endswith("/api/coach/integrations/linkedin/callback")


def test_skyeye_callback_intercepts_coach_state():
    src = (ROOT / "backend/app/routers/skyeye_api.py").read_text()
    assert "try_complete_coach_linkedin_callback" in src
    oauth = (ROOT / "backend/app/services/coach_linkedin_oauth.py").read_text()
    assert "INTO skyeye_platform_tokens" not in oauth
    assert "FROM skyeye_platform_tokens" not in oauth
    assert "coach_linkedin_connection" in oauth
    assert "coach_li_oauth_state" in oauth


@pytest.mark.asyncio
async def test_coach_callback_persists_per_hardware_id(monkeypatch):
    from app.services.coach_linkedin_oauth import try_complete_coach_linkedin_callback

    persisted = {}

    class _Redis:
        def __init__(self):
            self.store = {
                "coach_li_oauth_state:st1": json.dumps(
                    {"hardware_id": "COACH_A_ID", "user_id": "CoachA", "role": "COACH"}
                )
            }

        async def get(self, key):
            return self.store.get(key)

        async def delete(self, key):
            self.store.pop(key, None)

    class _State:
        auth_redis = _Redis()
        db_pool = object()

    class _Req:
        app = type("A", (), {"state": _State()})()

    async def _ex(_code):
        return {"access_token": "tok-a", "refresh_token": "", "person_urn": "urn:li:person:a"}

    async def _persist(_pool, coach_id, tokens):
        persisted["coach_id"] = coach_id
        persisted["token"] = tokens["access_token"]

    monkeypatch.setattr(
        "app.services.coach_linkedin_oauth.exchange_coach_linkedin_code", _ex
    )
    monkeypatch.setattr(
        "app.services.coach_linkedin_oauth.persist_coach_linkedin", _persist
    )
    resp = await try_complete_coach_linkedin_callback(_Req(), "code", "st1")
    assert persisted["coach_id"] == "COACH_A_ID"
    assert persisted["token"] == "tok-a"
    assert "linkedin=connected" in resp.headers.get("location", resp.headers.get("Location", ""))
    none_resp = await try_complete_coach_linkedin_callback(_Req(), "code", "missing")
    assert none_resp is None
