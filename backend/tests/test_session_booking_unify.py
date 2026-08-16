"""One coach email + duration + negotiation close."""

from unittest.mock import AsyncMock, patch

import pytest


def test_session_duration_from_window():
    from app.services.session_approval import session_duration_minutes

    assert session_duration_minutes({"duration_minutes": 0}) == 50
    assert (
        session_duration_minutes(
            {
                "duration_minutes": 0,
                "scheduled_start": "2026-08-25T11:00:00+00:00",
                "scheduled_end": "2026-08-25T12:00:00+00:00",
            }
        )
        == 60
    )
    assert session_duration_minutes({"duration_minutes": 45}) == 45


@pytest.mark.asyncio
async def test_notify_coach_uses_negotiation_only_when_flagged(monkeypatch):
    from app.services import session_approval as sa

    monkeypatch.setenv("ENABLE_NATE_SESSION_NEGOTIATION", "true")
    after = AsyncMock()
    pending = AsyncMock()
    with patch("app.services.session_negotiation_bridge.after_pending_booking", after):
        with patch.object(sa, "send_pending_booking_email", pending):
            ok = await sa.notify_coach_of_pending(
                object(),
                {"status": "pending_approval", "session_id": "S1"},
                connected_clients={},
                connected_coaches={},
            )
    assert ok is True
    after.assert_awaited_once()
    pending.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_coach_legacy_when_flag_off(monkeypatch):
    from app.services import session_approval as sa

    monkeypatch.setenv("ENABLE_NATE_SESSION_NEGOTIATION", "false")
    pending = AsyncMock(return_value=True)
    with patch.object(sa, "send_pending_booking_email", pending):
        ok = await sa.notify_coach_of_pending(
            object(), {"status": "pending_approval", "session_id": "S1"}
        )
    assert ok is True
    pending.assert_awaited_once()


def test_close_pending_allows_approved():
    src = open("backend/app/services/session_approval.py").read()
    assert '"approved"' in src
    assert "declined" in src


def test_clone_voice_id():
    from app.services.coach_campaign_clone import voice_id_for

    assert voice_id_for("COACH_COACHN_ID").startswith("coach_")
    assert " " not in voice_id_for("Coach N")


def test_linkedin_share_payload_video():
    from app.services.coach_linkedin_publisher import linkedin_ugc_post
    import inspect

    src = inspect.getsource(linkedin_ugc_post)
    assert "VIDEO" in src
    assert "media_urn" in src


def test_merge_keeps_clone_voice_id():
    from app.services.coach_voice_profile_service import merge_style

    merged = merge_style({}, {"clone_voice_id": "coach_x", "tone": "warm"})
    assert merged["clone_voice_id"] == "coach_x"


@pytest.mark.asyncio
async def test_client_vault_ingest_upserts_coach_style(monkeypatch):
    from app.services.voice_campaign_ingest import store_voice_recording

    class _Conn:
        async def execute(self, *a, **k):
            return None

    class _Acquire:
        def __init__(self, c):
            self._c = c

        async def __aenter__(self):
            return self._c

        async def __aexit__(self, *e):
            return False

    class _Pool:
        def acquire(self):
            return _Acquire(_Conn())

    monkeypatch.setenv("ENABLE_VOICE_CAMPAIGN", "true")
    monkeypatch.setattr(
        "app.services.voice_campaign_ingest.client_vault_sync",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.voice_campaign_ingest._transcribe",
        AsyncMock(return_value="I greet slowly and leave space after each sentence here."),
    )
    monkeypatch.setattr(
        "app.services.client_envelope_cipher.encrypt_for_client",
        AsyncMock(return_value="enc"),
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
    out = await store_voice_recording(_Pool(), "COACH_HW", "CLIENT_HW", b"wav-bytes")
    assert out["subject"] == "client"
    upsert.assert_awaited()
