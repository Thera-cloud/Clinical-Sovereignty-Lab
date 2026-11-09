"""Offline occupancy, slot-credit, publish payload, auditor handshake counts."""
from datetime import datetime, timedelta, timezone

from app.services.session_occupancy import ranges_overlap, as_utc, PAID_STATUSES
from app.services.session_schedule_publish import json_payload_from_row
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
