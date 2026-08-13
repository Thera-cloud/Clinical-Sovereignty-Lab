"""Seam 5: per-coach LinkedIn, History poll, Drive encrypt, SendGrid markers."""

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
