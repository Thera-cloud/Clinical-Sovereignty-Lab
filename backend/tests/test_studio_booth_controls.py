"""Booth dock contracts: stop-share, lookup, host-gate, sound, dump/end."""

from pathlib import Path

from _studio_load import load_svc

ROOT = Path(__file__).resolve().parents[2]
ROOM_COPIES = (
    "mobile/web/studio_nate_room.html",
    "mobile/web/studio_livekit_room.html",
    "backend/app/services/studio_nate_room.html",
    "backend/app/services/studio_livekit_room.html",
    "dashboard/studio_nate_room.html",
    "dashboard/studio_livekit_room.html",
)


def test_resolve_sound_any_word():
    share = load_svc("studio_cohost_share")
    hit = share.resolve_sound("explode")
    assert hit["ok"] is True
    assert hit["generated"] is True
    assert hit["sound_id"]
    assert share.resolve_sound("sting")["generated"] is False
    assert share.resolve_sound("")["ok"] is False
    assert share.resolve_sound("!!!")["ok"] is False


def test_prime_match_tight_growth():
    hold = load_svc("studio_listen_hold")
    assert hold.prime_match("hello there friends", "hello there friends extra")
    long_tail = "hello there friends " + ("x" * 20)
    assert not hold.prime_match("hello there friends", long_tail)


def test_booth_routes_and_cache_bump():
    api = (ROOT / "backend/app/routers/sovereign_studio_api.py").read_text()
    assert '/sessions/{session_id}/booth-status' in api
    assert '/sessions/{session_id}/booth/queue' in api
    assert '/sessions/{session_id}/booth/end' in api
    assert '/sessions/{session_id}/booth/dump' in api
    assert '/sessions/{session_id}/booth/guest-link' in api
    assert '/sessions/{session_id}/booth/egress' in api
    assert '/sessions/{session_id}/booth/ln-scan' in api
    assert '/sessions/{session_id}/booth/legs' in api
    assert '/sessions/{session_id}/lookup' in api
    live = (ROOT / "backend/app/services/studio_livekit.py").read_text()
    assert "v=20260909b" in live
    assert 'with_name("studio_nate_room.html")' in live
    assert "RemoveParticipant" in live
    sess = (ROOT / "backend/app/services/studio_session_service.py").read_text()
    assert "4–8 spoken sentences" not in sess
    assert "Never name the realm" in sess
    assert "broadcasting from" not in sess
    assert 'Realm: {realm_name}' not in sess
    share = (ROOT / "backend/app/services/studio_cohost_share.py").read_text()
    assert "_MAX_DOC = 32_000_000" in share


def test_sip_sync_keeps_phone_waiters():
    cq = load_svc("studio_caller_queue")
    wait, active = cq.merge_board_snapshot(
        ["caller-aaa11111", "web-guest"],
        "caller-bbb22222",
        ["web-1"],
        "",
    )
    assert "caller-aaa11111" in wait
    assert active == "caller-bbb22222"
    wait, active = cq.merge_board_snapshot(
        ["caller-aaa11111"],
        "caller-bbb22222",
        ["web-1"],
        "web-1",
    )
    assert active == "web-1"
    assert "caller-bbb22222" in wait
    assert cq.is_phone_identity("caller-abc")
    assert not cq.is_phone_identity("guest-xyz")


def test_six_room_copies_match():
    src = (ROOT / "mobile/web/studio_nate_room.html").read_text()
    for rel in ROOM_COPIES:
        other = (ROOT / rel).read_text()
        assert other == src, rel
    assert "function hasSpeechRec" in src
    assert "booth/egress" in src
    assert "Safari captions the host mic" in src
    assert "32 * 1024 * 1024" in src
    assert "intent.kind === 'search') doLookup" not in src
    assert "createElement('iframe')" in src
    assert "vid.controls = true" in src
    assert 'id="sfxList"' in src
    assert "booth/ln-scan" in src
    assert "screener then waiting room" in src
