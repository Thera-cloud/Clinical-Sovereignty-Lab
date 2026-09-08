"""PG-only pending bookings must be locatable for coach decline/approve."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    path = _ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


approval = _load("session_approval_under_test", "app/services/session_approval.py")
executor = _load("nate_tool_executor_under_test", "app/services/nate_tool_executor.py")


@pytest.mark.asyncio
async def test_locate_pending_from_json():
    sessions = [
        {
            "session_id": "SES_JSON",
            "coach_id": "COACH_X",
            "status": "pending_approval",
        }
    ]
    found = await approval.locate_pending_booking(None, sessions, "SES_JSON", "COACH_X")
    assert found is sessions[0]


@pytest.mark.asyncio
async def test_locate_pending_hydrates_pg_only_row():
    sessions = []
    pg_row = {
        "session_id": "SES_20260813_DD32F8",
        "coach_id": "COACH_COACHN_ID",
        "status": "pending_approval",
        "client_id": "CLIENT_LONGRA_ID",
    }
    loader = AsyncMock(return_value=[pg_row])
    found = await approval.locate_pending_booking(
        object(),
        sessions,
        "SES_20260813_DD32F8",
        "COACH_COACHN_ID",
        _pg_loader=loader,
    )
    assert found is pg_row
    assert sessions == [pg_row]


@pytest.mark.asyncio
async def test_merge_pg_pendings_appends_missing():
    sessions = [{"session_id": "SES_A", "status": "pending_approval"}]
    extra = {"session_id": "SES_B", "status": "pending_approval", "coach_id": "C1"}
    changed = await approval.merge_pg_pendings(
        object(), sessions, "C1", _pg_loader=AsyncMock(return_value=[extra])
    )
    assert changed is True
    assert any(s.get("session_id") == "SES_B" for s in sessions)


@pytest.mark.asyncio
async def test_merge_pg_upcoming_appends_and_drops_cancelled(monkeypatch):
    monkeypatch.setenv("SCHEDULE_PG_MERGE_CLIENT", "true")
    sessions = [
        {
            "session_id": "SES_JSON",
            "client_id": "CLIENT_A",
            "status": "scheduled",
        },
        {
            "session_id": "SES_DEAD",
            "client_id": "CLIENT_A",
            "status": "scheduled",
        },
    ]
    pg_rows = [
        {
            "session_id": "SES_PG",
            "client_id": "CLIENT_A",
            "status": "SCHEDULED",
            "payment_status": "pending",
            "price_cents": 12500,
        },
        {
            "session_id": "SES_DEAD",
            "client_id": "CLIENT_A",
            "status": "cancelled",
            "payment_status": "cancelled",
            "price_cents": 0,
        },
        {
            "session_id": "SES_JSON",
            "client_id": "CLIENT_A",
            "status": "scheduled",
            "payment_status": "paid",
            "price_cents": 9000,
        },
    ]
    changed = await approval.merge_pg_upcoming_for_client(
        object(), sessions, "CLIENT_A", _pg_loader=AsyncMock(return_value=pg_rows)
    )
    assert changed is True
    ids = {s.get("session_id") for s in sessions}
    assert "SES_PG" in ids
    assert "SES_DEAD" not in ids
    json_row = next(s for s in sessions if s["session_id"] == "SES_JSON")
    assert json_row.get("payment_status") == "paid"
    assert json_row.get("price_cents") == 9000


@pytest.mark.asyncio
async def test_merge_pg_upcoming_respects_flag_off(monkeypatch):
    monkeypatch.setenv("SCHEDULE_PG_MERGE_CLIENT", "false")
    sessions = []
    changed = await approval.merge_pg_upcoming_for_client(
        object(),
        sessions,
        "CLIENT_A",
        _pg_loader=AsyncMock(return_value=[{"session_id": "SES_X", "status": "scheduled"}]),
    )
    assert changed is False
    assert sessions == []


@pytest.mark.asyncio
async def test_cancel_pg_only_refunds_once_and_notifies():
    sessions = []
    pg_row = {
        "session_id": "SES_PG_ONLY",
        "client_id": "CLIENT_A",
        "coach_id": "COACH_A",
        "status": "scheduled",
        "scheduled_start": "2026-10-01T18:00:00+00:00",
        "client_name": "Audit Client",
        "payment_status": "paid",
    }
    refund = AsyncMock(return_value=("refunded", "re_test"))
    upsert = AsyncMock(return_value=True)
    notify = AsyncMock(return_value={"email": True, "sms": True})
    out = await approval.cancel_client_session(
        object(),
        sessions,
        "SES_PG_ONLY",
        "CLIENT_A",
        _pg_loader=AsyncMock(return_value=[pg_row]),
        _refund=refund,
        _upsert=upsert,
        _notify=notify,
    )
    assert out["ok"] is True
    assert out["json_changed"] is False
    assert out["refund_outcome"] == "refunded"
    assert sessions == []
    refund.assert_awaited_once()
    upsert.assert_awaited_once()
    notify.assert_awaited_once()
    cancelled = out["session"]
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelled_by"] == "CLIENT"


@pytest.mark.asyncio
async def test_cancel_inside_24h_too_late_still_cancels():
    sessions = [{
        "session_id": "SES_JSON",
        "client_id": "CLIENT_A",
        "status": "scheduled",
        "scheduled_start": "2026-09-09T12:00:00+00:00",
    }]
    refund = AsyncMock(return_value=("too_late", "inside 24h cancellation window — no refund"))
    upsert = AsyncMock(return_value=True)
    notify = AsyncMock(return_value={"email": False, "sms": False})
    out = await approval.cancel_client_session(
        object(),
        sessions,
        "SES_JSON",
        "CLIENT_A",
        _refund=refund,
        _upsert=upsert,
        _notify=notify,
    )
    assert out["ok"] is True
    assert out["json_changed"] is True
    assert sessions[0]["status"] == "cancelled"
    assert out["refund_outcome"] == "too_late"
    refund.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_coach_of_client_cancel_email_and_sms():
    sent = {}

    async def fake_lookup(_pool, hw):
        return {
            "email": "audit_coach@example.com",
            "phone": "+15555550100",
            "name": "Audit Coach",
            "timezone": "UTC",
        }

    async def fake_email(to_email, template_name, context):
        sent["email"] = (to_email, template_name, context)
        return True

    ns = AsyncMock()
    ns.send_sms = AsyncMock(return_value=True)
    result = await approval.notify_coach_of_client_cancel(
        object(),
        {
            "session_id": "SES_X",
            "coach_id": "audit_coach_hw",
            "client_name": "Audit Client",
            "scheduled_start": "2026-10-01T18:00:00+00:00",
        },
        notification_system=ns,
        _lookup=fake_lookup,
        _send_email=fake_email,
    )
    assert result["email"] is True
    assert result["sms"] is True
    assert sent["email"][1] == "session_cancelled_coach"
    ns.send_sms.assert_awaited_once()

    out = await executor._book_session_executor(
        None,
        "CLIENT_LONGRA_ID",
        {
            "slot_start": "2026-08-14T10:00:00+00:00",
            "notes": "yes I am concerned about her psychotic symptoms returning",
        },
    )
    assert out["success"] is False
    assert out["error"] == "coach_decision_required"
