import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.coach_handoff import (
    generate_handoff_summary,
    process_coach_handoff_accepted,
)
from app.services.little_nate_adaptive import SessionState, handle_coach_offer_response
from app.services.sensitive_alert_dispatcher import dispatch_sensitive_alert


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


class _RecordingConn:
    """Captures SQL issued by notify_coach / dispatch_sensitive_alert."""

    def __init__(self):
        self.fetchrow_calls = []
        self.execute_calls = []

    async def fetchrow(self, sql, *args):
        self.fetchrow_calls.append((sql, args))
        if "INSERT INTO coach_escalation_notifications" in sql:
            return {"id": 501}
        if "profile_data->>'phone'" in sql:
            return {"phone": "+15551234567", "email": "coach@example.com"}
        if "profile_data->>'email'" in sql:
            return {"email": "coach@example.com"}
        return None

    async def execute(self, sql, *args):
        self.execute_calls.append((sql, args))


@pytest.mark.asyncio
async def test_handle_coach_offer_response_accepts_yes():
    state = SessionState()
    assert handle_coach_offer_response(state, "yes please") == "accepted"


@pytest.mark.asyncio
async def test_generate_handoff_summary_uses_turn_context():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={"id": 1, "created_at": "2026-05-26T12:00:00Z"}
    )
    conn.fetch = AsyncMock(
        return_value=[
            {
                "user_text": "I feel stuck and alone lately.",
                "ai_text": "That sounds heavy.",
                "created_at": "2026-05-26T12:00:00Z",
            }
        ]
    )
    pool = _FakePool(conn)
    summary = await generate_handoff_summary(
        pool,
        "client_a",
        "turn-123",
        client_profile={"username": "client_a", "name": "Kristy Moore"},
    )
    assert "Kristy" in summary
    assert "turn-123" in summary or "stuck" in summary
    assert 150 <= len(summary.split()) <= 320


@pytest.mark.asyncio
async def test_process_handoff_acceptance_dispatch_and_idempotency():
    turn_id = "turn-handoff-001"
    client_profile = {
        "username": "client_a",
        "name": "Kristy Moore",
        "assigned_coach": "CoachN",
        "role": "CLIENT",
    }
    state = SessionState()

    idempotency_calls = {"count": 0}

    async def _fetchrow(sql, *args):
        if "sensitive_bridge_log" in sql and "handoff_source" in sql:
            idempotency_calls["count"] += 1
            if idempotency_calls["count"] > 1:
                return {"?column?": 1}
            return None
        if "INSERT INTO sensitive_bridge_log" in sql:
            return {"id": 9001}
        if "metadata->>'turn_id'" in sql:
            return {"id": 5, "created_at": "2026-05-26T12:00:00Z"}
        return None

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=_fetchrow)
    conn.fetch = AsyncMock(
        return_value=[
            {
                "user_text": "I need my coach.",
                "ai_text": "Would you like me to connect you?",
                "created_at": "2026-05-26T12:00:00Z",
            }
        ]
    )
    pool = _FakePool(conn)

    dispatch_receipt = {
        "event_id": 42,
        "coach_notified": True,
        "notification_id": 77,
        "email_sent": True,
        "redacted": True,
    }

    with patch(
        "app.services.sensitive_alert_dispatcher.dispatch_sensitive_alert",
        new=AsyncMock(return_value=dispatch_receipt),
    ) as dispatch_mock:
        first = await process_coach_handoff_accepted(
            pool, client_profile, turn_id, adaptive_state=state
        )
        second = await process_coach_handoff_accepted(
            pool, client_profile, turn_id, adaptive_state=state
        )

    assert first["status"] == "accepted"
    assert first["notification_id"] == 77
    assert first["audit_id"] == 9001
    assert first["email_sent"] is True
    assert second["status"] == "duplicate"
    dispatch_mock.assert_awaited_once()
    assert dispatch_mock.await_args.kwargs["alert_type"] == "client_initiated_handoff"
    assert turn_id in dispatch_mock.await_args.kwargs["keywords"]


@pytest.mark.asyncio
async def test_dispatch_chain_inserts_row_and_invokes_sms_email():
    """Real dispatch_sensitive_alert → notify_coach; only leaf I/O mocked."""
    conn = _RecordingConn()
    pool = _FakePool(conn)
    twilio_messages = MagicMock()
    twilio_client = MagicMock()
    twilio_client.messages.create = twilio_messages
    email_send = AsyncMock(return_value=True)

    env = {
        "TWILIO_ACCOUNT_SID": "AC_test",
        "TWILIO_AUTH_TOKEN": "tok_test",
        "TWILIO_PHONE_NUMBER": "+15550001111",
    }

    with patch(
        "app.services.crisis_events_writer.write_crisis_event",
        new=AsyncMock(return_value=99),
    ), patch(
        "app.services.pii_redaction.redact_pii",
        return_value=[{"role": "system", "content": "summary body"}],
    ), patch.dict(os.environ, env, clear=False), patch(
        "twilio.rest.Client",
        return_value=twilio_client,
    ), patch(
        "app.services.notifications_service.EmailService",
    ) as email_svc_cls:
        email_svc_cls.return_value.send_coach_handoff_request = email_send

        receipt = await dispatch_sensitive_alert(
            db_pool=pool,
            client_username="client_a",
            coach_username="CoachN",
            risk_level="high",
            reason="Kristy accepted coach handoff",
            raw_context="Kristy said she feels stuck.",
            alert_type="client_initiated_handoff",
            keywords=["client_initiated_handoff", "turn-xyz"],
        )

    inserts = [
        sql for sql, _ in conn.fetchrow_calls
        if "INSERT INTO coach_escalation_notifications" in sql
    ]
    channel_updates = [
        sql for sql, _ in conn.execute_calls
        if "UPDATE coach_escalation_notifications" in sql
    ]

    assert len(inserts) == 1
    assert channel_updates, "expected channels UPDATE after SMS"
    twilio_messages.assert_called_once()
    email_send.assert_awaited_once()
    assert receipt["notification_id"] == 501
    assert receipt["email_sent"] is True
    assert receipt["event_id"] == 99


@pytest.mark.asyncio
async def test_process_handoff_end_to_end_without_dispatch_stub():
    """process_coach_handoff_accepted runs real dispatch; leaf transports mocked."""
    turn_id = "turn-e2e-001"
    client_profile = {
        "username": "client_a",
        "name": "Kristy Moore",
        "assigned_coach": "CoachN",
    }
    recording = _RecordingConn()

    async def _fetchrow(sql, *args):
        recording.fetchrow_calls.append((sql, args))
        if "sensitive_bridge_log" in sql and "handoff_source" in sql:
            return None
        if "INSERT INTO sensitive_bridge_log" in sql:
            return {"id": 9002}
        if "metadata->>'turn_id'" in sql:
            return {"id": 5, "created_at": "2026-05-26T12:00:00Z"}
        if "INSERT INTO coach_escalation_notifications" in sql:
            return {"id": 502}
        if "profile_data->>'phone'" in sql:
            return {"phone": "+15551234567", "email": "coach@example.com"}
        if "profile_data->>'email'" in sql:
            return {"email": "coach@example.com"}
        return None

    recording.fetchrow = _fetchrow  # type: ignore[method-assign]
    recording.fetch = AsyncMock(
        return_value=[
            {
                "user_text": "I need my coach.",
                "ai_text": "Would you like me to connect you?",
                "created_at": "2026-05-26T12:00:00Z",
            }
        ]
    )
    pool = _FakePool(recording)

    twilio_messages = MagicMock()
    twilio_client = MagicMock()
    twilio_client.messages.create = twilio_messages
    email_send = AsyncMock(return_value=True)

    with patch(
        "app.services.coach_handoff.generate_handoff_summary",
        new=AsyncMock(return_value="summary " * 120),
    ), patch(
        "app.services.crisis_events_writer.write_crisis_event",
        new=AsyncMock(return_value=88),
    ), patch(
        "app.services.pii_redaction.redact_pii",
        return_value=[{"role": "system", "content": "redacted summary"}],
    ), patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "AC_test",
            "TWILIO_AUTH_TOKEN": "tok_test",
            "TWILIO_PHONE_NUMBER": "+15550001111",
        },
        clear=False,
    ), patch(
        "twilio.rest.Client",
        return_value=twilio_client,
    ), patch(
        "app.services.notifications_service.EmailService",
    ) as email_svc_cls:
        email_svc_cls.return_value.send_coach_handoff_request = email_send

        result = await process_coach_handoff_accepted(
            pool, client_profile, turn_id, adaptive_state=SessionState()
        )

    inserts = [
        s for s, _ in recording.fetchrow_calls
        if "INSERT INTO coach_escalation_notifications" in s
    ]
    assert result["status"] == "accepted"
    assert result["notification_id"] == 502
    assert len(inserts) == 1
    twilio_messages.assert_called_once()
    email_send.assert_awaited_once()
