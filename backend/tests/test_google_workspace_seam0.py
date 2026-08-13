"""Seam 0: envelope cipher, split OAuth scopes, googleSvc freeze. Offline."""

import inspect
import os
from pathlib import Path

import pytest

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[2]


def test_183_calendar_scopes_have_no_gmail_or_drive():
    from app.services.google_calendar_client import GOOGLE_SCOPES, build_oauth_url

    blob = GOOGLE_SCOPES.lower()
    assert "gmail" not in blob
    assert "drive" not in blob
    assert "calendar.events" in blob
    src = inspect.getsource(build_oauth_url)
    assert "GOOGLE_SCOPES" in src
    assert "GOOGLE_WS_SCOPES" not in src


def test_workspace_scopes_are_full_grant_without_gmail_send():
    from app.services.google_workspace_oauth import GOOGLE_WS_SCOPES, build_workspace_oauth_url

    blob = GOOGLE_WS_SCOPES.lower()
    assert "gmail.compose" in blob
    assert "gmail.readonly" in blob
    assert "drive.file" in blob
    assert "gmail.send" not in blob
    url = build_workspace_oauth_url("cid", "https://example/cb", "state")
    assert "include_granted_scopes=false" in url
    assert "gmail.send" not in url


def test_envelope_kek_must_not_equal_token_cipher_key():
    from app.services import client_envelope_cipher as cec

    shared = Fernet.generate_key().decode()
    os.environ["CLIENT_ENVELOPE_KEK"] = shared
    os.environ["SKYEYE_TOKEN_ENCRYPTION_KEY"] = shared
    with pytest.raises(cec.EnvelopeUnavailable):
        cec._kek()
    os.environ["CLIENT_ENVELOPE_KEK"] = Fernet.generate_key().decode()
    kek = cec._kek()
    dek = cec.generate_dek()
    wrapped = cec.wrap_dek(dek)
    assert cec.unwrap_dek(wrapped) == dek
    ct = cec.encrypt_with_dek(dek, b"draft-body")
    assert cec.decrypt_with_dek(dek, ct) == b"draft-body"


@pytest.mark.asyncio
async def test_destroy_keys_blocked_when_erasure_flag_off(monkeypatch):
    from app.services.client_envelope_cipher import ErasureDisabled, destroy_client_keys

    monkeypatch.setenv("ENABLE_CLINICAL_ERASURE", "false")
    with pytest.raises(ErasureDisabled):
        await destroy_client_keys(None, "CLIENT_X")


@pytest.mark.asyncio
async def test_google_svc_flag_off_and_vault_blocked(monkeypatch):
    from app.services.google_workspace_service import (
        FlagOff,
        VaultBlocked,
        get_google_svc,
    )

    monkeypatch.setenv("ENABLE_WS_OAUTH", "false")
    monkeypatch.setenv("ENABLE_WS_CALENDAR_SYNC", "false")
    monkeypatch.setenv("ENABLE_WS_GMAIL_DRAFTS", "false")
    monkeypatch.setenv("ENABLE_WS_DRIVE_DELIVERY", "true")
    svc = get_google_svc(db_pool=None)
    st = await svc.status("COACH_HW")
    assert st["connected"] is False
    assert st["oauth_enabled"] is False
    up = await svc.calendar.upsertSession("COACH_HW", "SES_1")
    assert up["reason"] == "flag_off"
    with pytest.raises(FlagOff):
        await svc.gmail.createDraft("COACH_HW", {"body": "hi", "client_id": "CLIENT_X"})
    with pytest.raises(VaultBlocked):
        await svc.drive.writeClientFile("COACH_HW", "CLIENT_X")


def test_envelope_module_does_not_import_token_cipher():
    src = (ROOT / "backend/app/services/client_envelope_cipher.py").read_text()
    assert "from app.services.skyeye_platform_base import TokenCipher" not in src
    assert "CLIENT_ENVELOPE_KEK" in src


def test_workspace_connect_gated_in_source():
    src = (ROOT / "backend/app/routers/google_workspace_api.py").read_text()
    assert "ENABLE_WS_OAUTH" in src
    assert "os.getenv(\"GOOGLE_CLIENT_ID\"" not in src
    assert "require_coach" in src


def test_migration_328_is_additive():
    sql = (ROOT / "backend/migrations/328_google_workspace_voice_campaign.sql").read_text()
    assert "DROP TABLE" not in sql.upper()
    assert "client_data_keys" in sql
    assert "google_workspace_connection" in sql
    assert "workspace_identity" in sql
    assert "uq_users_hardware_id" in sql
    assert "token_app" in sql
    assert "consent_records" in sql
    assert "content_id BIGINT" in sql
    assert "linkedin_post" in sql
    low = sql.lower()
    assert "drop column" not in low
