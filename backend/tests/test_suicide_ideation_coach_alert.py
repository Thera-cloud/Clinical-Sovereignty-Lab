import os
from unittest.mock import AsyncMock, patch

import pytest

from app.services.suicide_ideation_coach_alert import maybe_dispatch_si_coach_alert
from app.services.suicide_ideation_lexicon import match_user_text


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AcquireCtx(self._conn)


def test_lexicon_matches_active_si():
    assert "kill myself" in match_user_text("I want to kill myself tonight")
    assert match_user_text("I'm going to die laughing") == []


def test_lexicon_self_harm_phrases():
    hits = match_user_text("I've been cutting myself again")
    assert "cut myself" in hits or "self-harm" in hits or "hurt myself" in hits


@pytest.mark.asyncio
async def test_maybe_dispatch_disabled_when_flag_off():
    pool = _FakePool(AsyncMock())
    with patch.dict(os.environ, {"ENABLE_UNIVERSAL_SI_COACH_ALERT": "false"}, clear=False):
        result = await maybe_dispatch_si_coach_alert(
            pool,
            {"username": "client_a", "role": "CLIENT", "assigned_coach": "CoachN"},
            "I want to kill myself",
        )
    assert result["status"] == "disabled"


@pytest.mark.asyncio
async def test_maybe_dispatch_skips_dojo_simulation():
    pool = _FakePool(AsyncMock())
    with patch.dict(os.environ, {"ENABLE_UNIVERSAL_SI_COACH_ALERT": "true"}, clear=False):
        result = await maybe_dispatch_si_coach_alert(
            pool,
            {"username": "client_a", "role": "CLIENT", "assigned_coach": "CoachN"},
            "[DOJO SIMULATION] I want to kill myself",
        )
    assert result["status"] == "skipped"
    assert result["reason"] == "simulation_or_synthesis"


@pytest.mark.asyncio
async def test_maybe_dispatch_dispatches_on_match():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()
    pool = _FakePool(conn)
    profile = {
        "username": "client_a",
        "role": "CLIENT",
        "assigned_coach": "CoachN",
        "hardware_id": "CLIENT_A_ID",
    }
    dispatch_receipt = {
        "event_id": 11,
        "coach_notified": True,
        "notification_id": 88,
        "email_sent": True,
    }

    with patch.dict(
        os.environ,
        {"ENABLE_UNIVERSAL_SI_COACH_ALERT": "true", "SI_COACH_ALERT_DEDUP_HOURS": "24"},
        clear=False,
    ), patch(
        "app.services.sensitive_alert_dispatcher.dispatch_sensitive_alert",
        new=AsyncMock(return_value=dispatch_receipt),
    ) as dispatch_mock:
        result = await maybe_dispatch_si_coach_alert(
            pool, profile, "I want to kill myself", turn_id="turn-si-1"
        )

    assert result["status"] == "dispatched"
    assert result["notification_id"] == 88
    dispatch_mock.assert_awaited_once()
    assert dispatch_mock.await_args.kwargs["alert_type"] == "suicidal_ideation_escalation"
    assert dispatch_mock.await_args.kwargs["risk_level"] == "critical"
    assert "kill myself" in dispatch_mock.await_args.kwargs["keywords"]


@pytest.mark.asyncio
async def test_maybe_dispatch_dedup_skips_second_alert():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"?column?": 1})
    pool = _FakePool(conn)
    profile = {"username": "client_a", "role": "CLIENT", "assigned_coach": "CoachN"}

    with patch.dict(os.environ, {"ENABLE_UNIVERSAL_SI_COACH_ALERT": "true"}, clear=False), patch(
        "app.services.sensitive_alert_dispatcher.dispatch_sensitive_alert",
        new=AsyncMock(),
    ) as dispatch_mock:
        result = await maybe_dispatch_si_coach_alert(pool, profile, "I want to kill myself")

    assert result["status"] == "duplicate"
    dispatch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_dispatch_no_coach():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    pool = _FakePool(conn)
    profile = {"username": "client_a", "role": "CLIENT"}

    with patch.dict(os.environ, {"ENABLE_UNIVERSAL_SI_COACH_ALERT": "true"}, clear=False), patch(
        "app.services.coach_handoff._resolve_assigned_coach_username",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.sensitive_alert_dispatcher.dispatch_sensitive_alert",
        new=AsyncMock(),
    ) as dispatch_mock:
        result = await maybe_dispatch_si_coach_alert(pool, profile, "I want to kill myself")

    assert result["status"] == "error"
    assert result["reason"] == "no_assigned_coach"
    dispatch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_fallback_for_si_alert_type():
    from app.services.coach_notifications import notify_coach

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"id": 601},
        {"phone": "5865243969", "email": "coach@example.com"},
    ])
    conn.execute = AsyncMock()
    pool = _FakePool(conn)

    with patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "AC_test",
            "TWILIO_AUTH_TOKEN": "tok_test",
            "TWILIO_PHONE_NUMBER": "+15550001111",
        },
        clear=False,
    ), patch(
        "app.services.coach_notifications._send_coach_sms",
        return_value=False,
    ), patch(
        "app.services.coach_notifications._send_coach_voice_ping",
        return_value=True,
    ) as voice_mock:
        result = await notify_coach(
            pool,
            "CoachN",
            {
                "urgency": "critical",
                "subject": "SI alert",
                "message": "Suicidal language detected",
                "payload": {
                    "alert_type": "suicidal_ideation_escalation",
                    "event_id": 1,
                    "risk_level": "critical",
                },
            },
        )

    assert "voice" in result["channels"]
    voice_mock.assert_called_once()
    assert "suicidal" in voice_mock.call_args[0][1].lower()
