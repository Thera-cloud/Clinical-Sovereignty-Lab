"""Offline occupancy, slot-credit, publish payload, auditor handshake counts."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.session_occupancy import (
    OCCUPANCY_UNAVAILABLE,
    PAID_STATUSES,
    SIBLING_CLIENT_SQL,
    as_utc,
    occupancy_blocks_booking,
    ranges_overlap,
)
from app.services.session_schedule_publish import json_payload_from_row, upsert_sessions_json_row
from app.services.session_slot_facts import fact_text, _pi_suffix
from app.services.session_ops_reconcile_agent import classify_session
from app.services.billing_auditor import TAB_ENDPOINTS


NOW = datetime(2026, 11, 8, 20, 0, tzinfo=timezone.utc)
SLOT = datetime(2026, 11, 9, 14, 0, tzinfo=timezone.utc)


def test_ranges_overlap_half_open():
    a0, a1 = SLOT, SLOT + timedelta(minutes=50)
    b0, b1 = SLOT + timedelta(minutes=50), SLOT + timedelta(minutes=100)
    assert ranges_overlap(a0, a1, SLOT, SLOT + timedelta(minutes=10))
    assert not ranges_overlap(a0, a1, b0, b1)


def test_as_utc_z_and_naive():
    assert as_utc("2026-11-09T14:00:00Z").tzinfo is not None
    assert as_utc(datetime(2026, 11, 9, 14, 0)).tzinfo is timezone.utc


def test_json_payload_paid_zoom():
    payload = json_payload_from_row({
        "session_id": "SES_20261109_R7B1W2",
        "coach_id": "COACH_COACHN_ID",
        "client_id": "CLIENT_LETSGOBILL_ID",
        "client_name": "Bill West",
        "status": "scheduled",
        "payment_status": "paid",
        "scheduled_start": SLOT,
        "scheduled_end": SLOT + timedelta(minutes=50),
        "zoom_meeting_id": "99793663383",
        "zoom_link": "https://zoom.us/j/99793663383",
        "price_cents": 9000,
        "stripe_payment_intent_id": "pi_3UZZpgDY11zQpvls0DXSHeVw",
    })
    assert payload["payment_status"] == "paid"
    assert payload["zoom_meeting_id"] == "99793663383"
    assert payload["session_id"] == "SES_20261109_R7B1W2"


def test_slot_fact_never_global_and_pi_suffix():
    text = fact_text({
        "session_id": "SES_20261109_R7B1W2",
        "scheduled_start": SLOT.isoformat(),
        "price_cents": 9000,
        "payment_status": "paid",
        "stripe_payment_intent_id": "pi_3UZZpgDY11zQpvls0DXSHeVw",
        "zoom_meeting_id": "99793663383",
    }, "schedule_published")
    assert "SES_20261109_R7B1W2" in text
    assert "XSHeVw" in text or _pi_suffix("pi_3UZZpgDY11zQpvls0DXSHeVw") in text
    assert "global" not in text.lower()


def test_classify_paid_unpublished_heals():
    actions = classify_session(
        {
            "status": "scheduled",
            "scheduled_start": (NOW + timedelta(hours=18)).isoformat(),
            "payment_status": "paid",
            "price_cents": 9000,
        },
        NOW,
    )
    assert "paid_confirmed" in actions
    assert "publish_json" in actions
    assert "create_gcal" in actions
    assert "ensure_zoom" in actions


def test_classify_paid_published_zoom_gcal_no_heal():
    actions = classify_session(
        {
            "status": "scheduled",
            "scheduled_start": (NOW + timedelta(hours=18)).isoformat(),
            "payment_status": "paid",
            "google_event_id": "gcal1",
            "zoom_meeting_id": "99793663383",
            "session_data": {"schedule_published_at": NOW.isoformat()},
        },
        NOW,
    )
    assert "paid_confirmed" in actions
    assert "publish_json" not in actions
    assert "create_gcal" not in actions
    assert "ensure_zoom" not in actions


def test_billing_auditor_handshake_count_41():
    total = sum(len(t["endpoints"]) for t in TAB_ENDPOINTS)
    assert total == 41
    names = [e[1] for t in TAB_ENDPOINTS if t["tab_num"] == 10 for e in t["endpoints"]]
    assert "paid_missing_zoom" in names
    assert "occupancy_overlap" in names
    assert "paid_not_scheduled" in names


def test_paid_status_allowlist():
    assert "paid" in PAID_STATUSES


@pytest.mark.asyncio
async def test_occupancy_fail_closed_without_pool():
    msg = await occupancy_blocks_booking(
        None, coach_id="COACH_COACHN_ID", start=SLOT,
    )
    assert msg == OCCUPANCY_UNAVAILABLE


def test_sibling_sql_is_read_only():
    assert "UPDATE " not in SIBLING_CLIENT_SQL.upper()
    assert "DELETE " not in SIBLING_CLIENT_SQL.upper()
    assert "u2.hardware_id IS DISTINCT FROM u1.hardware_id" in SIBLING_CLIENT_SQL


def test_json_upsert_cancels_ghost_zoom_keeps_others(tmp_path: Path):
    other = {
        "session_id": "SES_OTHER",
        "coach_id": "COACH_X",
        "status": "scheduled",
        "scheduled_start": "2026-12-01T14:00:00+00:00",
        "zoom_meeting_id": "keep-me",
    }
    ghost = {
        "session_id": "SES_20260915_C94FF3",
        "coach_id": "COACH_COACHN_ID",
        "status": "scheduled",
        "scheduled_start": SLOT.isoformat(),
        "scheduled_end": (SLOT + timedelta(hours=1)).isoformat(),
        "zoom_meeting_id": "91728870074",
        "zoom_link": "https://zoom.us/j/91728870074",
        "zoom_host_url": "https://zoom.us/s/91728870074",
    }
    path = tmp_path / "sessions.json"
    path.write_text(json.dumps([other, ghost]), encoding="utf-8")
    payload = json_payload_from_row({
        "session_id": "SES_20261109_R7B1W2",
        "coach_id": "COACH_COACHN_ID",
        "client_id": "CLIENT_LETSGOBILL_ID",
        "status": "scheduled",
        "payment_status": "paid",
        "scheduled_start": SLOT,
        "scheduled_end": SLOT + timedelta(hours=1),
        "zoom_meeting_id": "99793663383",
    })
    out = upsert_sessions_json_row(payload, paths=[path])
    assert path.as_posix() in (out.get("written") or [])
    data = json.loads(path.read_text(encoding="utf-8"))
    by_id = {row["session_id"]: row for row in data}
    assert by_id["SES_OTHER"]["status"] == "scheduled"
    assert by_id["SES_OTHER"]["zoom_meeting_id"] == "keep-me"
    assert by_id["SES_20260915_C94FF3"]["status"] == "cancelled"
    assert by_id["SES_20260915_C94FF3"]["zoom_meeting_id"] == ""
    assert by_id["SES_20261109_R7B1W2"]["payment_status"] == "paid"


def test_classify_pending_publish_retries():
    actions = classify_session(
        {
            "status": "scheduled",
            "scheduled_start": (NOW + timedelta(hours=18)).isoformat(),
            "payment_status": "paid",
            "google_event_id": "gcal1",
            "zoom_meeting_id": "99793663383",
            "session_data": {
                "schedule_published_at": NOW.isoformat(),
                "schedule_publish_pending": True,
            },
        },
        NOW,
    )
    assert "publish_json" in actions
