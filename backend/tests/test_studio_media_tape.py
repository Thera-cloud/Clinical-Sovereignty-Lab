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


def test_removed_marker_hides_episode_from_edit():
    assert _tape.tape_removed_marker({"removed": True}) is True
    assert _tape.tape_removed_marker('{"removed": true}') is True
    assert _tape.tape_removed_marker([{"start_s": 1, "end_s": 2}]) is False
    assert _tape.tape_removed_marker([]) is False


def test_delete_keys_stay_inside_the_session():
    sid = "22659f6a-8d0f-4b19-97f3-466d91f15c24"
    keys = _tape.tape_keys_for_delete(
        sid,
        [
            f"studio/{sid}.mp4",
            f"studio/{sid}/cut.mp4",
            "studio/other-session.mp4",
            "../secrets.env",
            "",
        ],
    )
    assert keys == [f"studio/{sid}.mp4", f"studio/{sid}/cut.mp4"]


def test_tape_play_url_empty_without_key():
    assert _tape.tape_play_url("") == ""
    assert _tape.tape_play_url("   ") == ""


def test_transcript_interleaves_nate_with_host():
    lines = _ep.arrange_transcript(
        [
            {
                "id": "h",
                "role": "host",
                "label": "Host",
                "utterances_json": [
                    {"t": "HOST", "text": "one"},
                    {"t": "HOST", "text": "two"},
                ],
            },
            {
                "id": "n",
                "role": "cohost_ai",
                "label": "AI",
                "utterances_json": [
                    {"t": "NATE", "text": "reply one"},
                    {"t": "NATE", "text": "reply two"},
                ],
            },
        ]
    )
    assert [row["speaker"] for row in lines] == [
        "Host",
        "Little Nate",
        "Host",
        "Little Nate",
    ]


def test_program_out_signals_egress_start():
    html = (ROOT / "mobile/web/studio_program_out.html").read_text()
    assert "START_RECORDING" in html
    assert "END_RECORDING" in html


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
    nested = {
        "storyboard": [
            {"id": 1, "clip": {"start_s": 1, "end_s": 8, "source_id": "master"}},
            {"id": 2, "clip": None},
            {"id": 3, "start_s": 40, "end_s": 70},
        ]
    }
    assert parse_cut_windows(nested) == [(1.0, 8.0), (40.0, 70.0)]


def test_storyboard_limits_and_title():
    slots = _tape.storyboard_blueprint()
    assert [s["max_s"] for s in slots] == [20.0, 30.0, 330.0, 120.0, 330.0, 120.0, 60.0]
    assert slots[1]["label"] == "Hook Video"
    assert _tape.clip_fits_slot(20, 20) is True
    assert _tape.clip_fits_slot(20.2, 20) is False
    assert _tape.edited_title("The Moments Between") == "The Moments Between (Edited Version)"
    filled, err = _tape.normalize_storyboard(
        [{"id": 1, "start_s": 0, "end_s": 12, "source_title": "Master"}]
    )
    assert err == ""
    assert filled[0]["clip"]["duration_s"] == 12
    assert filled[1]["clip"] is None
    over, over_err = _tape.normalize_storyboard([{"id": 1, "start_s": 0, "end_s": 40}])
    assert over == []
    assert over_err == "slot_1_over_max"


def test_apply_cuts_storyboard_over_max_offline():
    out = asyncio.run(
        apply_cuts(
            None,
            "ep",
            "coach",
            storyboard=[{"id": 1, "start_s": 0, "end_s": 99}],
        )
    )
    assert out["ok"] is False
    assert out["code"] == 422
    assert "over_max" in str(out.get("reason") or "")


def test_migration_443_and_editor_ui():
    sql = (ROOT / "backend/migrations/443_studio_episode_assets.sql").read_text()
    assert "studio_episode_assets" in sql
    src = (ROOT / "backend/app/routers/sovereign_studio_api.py").read_text()
    assert "storyboard-slots" in src
    assert "/episodes/{episode_id}/assets" in src
    dart = (ROOT / "mobile/lib/widgets/coach_studio_podcast_editor.dart").read_text()
    assert "Uncut Master Tape" in dart
    assert "Approve & Publish Cut" in dart
    assert "Add to Storyboard" in dart
    assert "ADJUST PLACED CLIP" in dart
    assert "Publish Successful!" in dart
    assert "Invalid Clip" in dart
    assert "Stitch Time:" in dart
    assert "Upload New Media" in dart
    assert "Return to Dashboard" in dart
    assert "Hook Video" in dart
    tab = (ROOT / "mobile/lib/widgets/coach_sovereign_studio_tab.dart").read_text()
    assert "CoachStudioPodcastEditor" in tab


def test_apply_cuts_offline_no_db():
    out = asyncio.run(apply_cuts(None, "ep", "coach", [{"start_s": 1, "end_s": 2}]))
    assert out["ok"] is False
    assert out["code"] == 503


def test_empty_add_cuts_still_422():
    out = asyncio.run(add_cuts(None, "x", "coach", []))
    assert out["ok"] is False
    assert out["code"] == 422


def test_webhook_jwt_and_stamp_gate():
    import hashlib
    import os

    os.environ["LIVEKIT_API_KEY"] = "k"
    os.environ["LIVEKIT_API_SECRET"] = "s"
    raw = b'{"event":"egress_ended"}'
    tok = _lk.mint_api_jwt(api_key="k", api_secret="s")
    assert _lk.verify_livekit_webhook("", raw)["ok"] is False
    assert _lk.verify_livekit_webhook(f"Bearer {tok}", raw)["ok"] is True
    digest = hashlib.sha256(raw).hexdigest()
    bad = _lk.mint_api_jwt(api_key="k", api_secret="s")
    # Body hash, when present, must match.
    import base64
    import json
    import hmac as _hmac

    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = _b64(b'{"alg":"HS256","typ":"JWT"}')
    payload = _b64(json.dumps({"iss": "k", "nbf": 1, "exp": 4102444800, "sha256": digest}).encode())
    sig = _hmac.new(b"s", f"{header}.{payload}".encode(), hashlib.sha256).digest()
    good = f"{header}.{payload}.{_b64(sig)}"
    assert _lk.verify_livekit_webhook(f"Bearer {good}", raw)["ok"] is True
    payload_bad = _b64(json.dumps({"iss": "k", "nbf": 1, "exp": 4102444800, "sha256": "00"}).encode())
    sig_bad = _hmac.new(b"s", f"{header}.{payload_bad}".encode(), hashlib.sha256).digest()
    wrong = f"{header}.{payload_bad}.{_b64(sig_bad)}"
    assert _lk.verify_livekit_webhook(f"Bearer {wrong}", raw).get("reason") == "bad_body_hash"
    assert bad.count(".") == 2
    src = (ROOT / "backend/app/routers/sovereign_studio_api.py").read_text()
    assert "verify_livekit_webhook" in src
    assert "start_session_egress" in src
    tier2 = (ROOT / "backend/app/services/studio_tier2.py").read_text()
    assert 'plan.get("started") and plan.get("egress_id")' in tier2


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
