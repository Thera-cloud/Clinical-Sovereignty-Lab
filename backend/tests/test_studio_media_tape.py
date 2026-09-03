"""Studio egress → R2 stamp + FFmpeg cut windows (offline)."""

import asyncio
from pathlib import Path

from _studio_load import load_svc

_lk = load_svc("studio_livekit")
_tape = load_svc("studio_media_tape")
_ep = load_svc("studio_episode_service")

session_media_r2_key = _lk.session_media_r2_key
session_cut_r2_key = _lk.session_cut_r2_key
parse_egress_event = _lk.parse_egress_event
handle_event = _lk.handle_event
parse_cut_windows = _tape.parse_cut_windows
apply_cuts = _tape.apply_cuts
add_cuts = _ep.add_cuts

ROOT = Path(__file__).resolve().parents[2]


def test_session_media_key_convention():
    assert session_media_r2_key("abc-1") == "studio/abc-1.mp4"
    assert session_cut_r2_key("abc-1") == "studio/abc-1/cut.mp4"
    assert session_media_r2_key("") == ""


def test_parse_egress_complete_from_room():
    parsed = parse_egress_event(
        {
            "event": "egress_ended",
            "egressInfo": {
                "egressId": "EG_1",
                "roomName": "studio-sid-99",
                "status": "EGRESS_COMPLETE",
                "file": {"filename": "studio/sid-99.mp4"},
            },
        }
    )
    assert parsed["session_id"] == "sid-99"
    assert parsed["complete"] is True
    assert parsed["media_r2_key"] == "studio/sid-99.mp4"
    assert parsed["egress_id"] == "EG_1"
    evt = handle_event({"event": "egress_ended", "egressInfo": {"roomName": "studio-x"}})
    assert evt["ok"] is True
    assert evt["media_r2_key"] == "studio/x.mp4"


def test_parse_cut_windows_shapes():
    assert parse_cut_windows([{"start_s": 10, "end_s": 40}]) == [(10.0, 40.0)]
    assert parse_cut_windows("10-40,90-120") == [(10.0, 40.0), (90.0, 120.0)]
    assert parse_cut_windows([[1, 5]]) == [(1.0, 5.0)]
    assert parse_cut_windows([{"start_s": 10, "end_s": 5}]) == []
    assert parse_cut_windows([]) == []


def test_apply_cuts_offline_no_db():
    out = asyncio.run(apply_cuts(None, "ep", "coach", [{"start_s": 1, "end_s": 2}]))
    assert out["ok"] is False
    assert out["code"] == 503


def test_empty_add_cuts_still_422():
    out = asyncio.run(add_cuts(None, "x", "coach", []))
    assert out["ok"] is False
    assert out["code"] == 422


def test_migration_431_and_routes():
    sql = (ROOT / "backend/migrations/431_studio_session_media.sql").read_text()
    assert "media_ready" in sql
    assert "media_master_r2_key" in sql
    assert "ADD COLUMN IF NOT EXISTS" in sql
    src = (ROOT / "backend/app/routers/sovereign_studio_api.py").read_text()
    assert "apply-cuts" in src
    assert "stamp_session_tape" in src
    ep = (ROOT / "backend/app/services/studio_episode_service.py").read_text()
    assert "media_master_r2_key" in ep
    dart = (ROOT / "mobile/lib/widgets/coach_sovereign_studio_tab.dart").read_text()
    assert "Apply cuts" in dart
    assert "tape ready" in dart
    assert "/apply-cuts" in dart
