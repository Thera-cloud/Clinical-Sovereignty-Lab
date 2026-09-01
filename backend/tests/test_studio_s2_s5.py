"""S2–S5 offline gates: screener tree, INV-6 scan, dump gate, LiveKit guest video."""

from pathlib import Path

from _studio_load import load_svc

_comp = load_svc("studio_compliance")
_inv = load_svc("studio_invariants")
_lk = load_svc("studio_livekit")
_sess = load_svc("studio_session_service")
_meter = load_svc("studio_meter")
_sip = load_svc("studio_sip")
_did = load_svc("studio_did_service")
_sc = load_svc("studio_screener_service")
_t2 = load_svc("studio_tier2")
_sms = load_svc("studio_sms")
_av = load_svc("studio_avatar")
_as = load_svc("studio_screener_autoscale")
_yt = load_svc("studio_youtube")
scan_text = _comp.scan_text
prescan_outgoing = _comp.prescan_outgoing
LIVE_TIER_CLEAN_EPISODES = _inv.LIVE_TIER_CLEAN_EPISODES
LN_COHOST_LABEL = _inv.LN_COHOST_LABEL
join_token_stub = _lk.join_token_stub
reject_guest_video = _lk.reject_guest_video
mint_livekit_jwt = _lk.mint_livekit_jwt
room_embed_url = _lk.room_embed_url
egress_plan = _lk.egress_plan
join_token = _lk.join_token
session_minutes = _meter.session_minutes
sip_join_allowed = _sip.sip_join_allowed
sip_ingress_twiml = _sip.sip_ingress_twiml
normalize_e164 = _did.normalize_e164
COACHN_DID = _did.COACHN_DID
handle_screener = _sc.handle_screener
inbound_twiml = _sc.inbound_twiml
is_risk = _sc.is_risk
wait_twiml = _sc.wait_twiml
handle_event = _lk.handle_event
DELAY_S = _t2.DELAY_S
dump_allowed = _t2.dump_allowed
parse_sms_reply = _sms.parse_sms_reply
envelope_frame = _av.envelope_frame
scale_hint = _as.scale_hint
parse_state = _yt.parse_state
_sign_state = _yt._sign_state

ROOT = Path(__file__).resolve().parents[2]


def test_inbound_always_screener():
    xml = inbound_twiml()
    assert "/api/studio/voice/screener" in xml
    assert "screening" in xml.lower()


def test_screener_risk_private_support_not_show():
    out = handle_screener(step="risk", speech="I want to die tonight")
    assert out["risk"] is True
    assert "988" in out["twiml"]
    assert "<Dial>988</Dial>" in out["twiml"]
    assert "private support" in out["twiml"].lower()
    assert "waiting room" not in out["twiml"].lower()


def test_screener_safe_wait():
    out = handle_screener(step="risk", speech="I want to talk about habits")
    assert out["risk"] is False
    assert "waiting room" in out["twiml"].lower()
    assert "audio only" in out["twiml"].lower()


def test_wait_room_loops_then_closes():
    looped = wait_twiml(0)
    assert "step=wait" in looped
    assert "n=1" in looped
    closed = wait_twiml(8)
    assert "Hangup" in closed
    evt = handle_event({"event": "egress_ended"})
    assert evt["ok"] is True
    assert evt["allow_video_guest"] is False


def test_is_risk_false_on_ordinary():
    assert is_risk("how do I keep a morning routine") is False


def test_compliance_inv6_and_pii():
    flags = scan_text("I diagnose you have depression. Call 555-123-4567")
    cats = {f["category"] for f in flags}
    assert "guardrail" in cats
    assert "pii" in cats


def test_dump_gate_one_clean_episode():
    assert LIVE_TIER_CLEAN_EPISODES == 1
    assert dump_allowed(0) is False
    assert dump_allowed(1) is True
    assert DELAY_S == 45


def test_livekit_guest_audio_only():
    assert reject_guest_video("guest", "track-1")["ok"] is False
    assert reject_guest_video("guest", None)["ok"] is True
    tok = join_token_stub("sid", "guest")
    assert tok["allow_video"] is False
    assert tok["allowed_media_kinds"] == ["audio"]


def test_migration_407_and_api_routes():
    sql = (ROOT / "backend/migrations/407_studio_s2_s5.sql").read_text()
    assert "studio_youtube_connection" in sql
    assert "rtmp_url" in sql
    c402 = (ROOT / "backend/migrations/402_studio_callers.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS consent_records" not in c402
    c408 = (ROOT / "backend/migrations/408_studio_consent_records.sql").read_text()
    assert "studio_consent_records" in c408
    c409 = (ROOT / "backend/migrations/409_studio_s2_s5_complete.sql").read_text()
    assert "studio_dump_spans" in c409
    assert "COACH_COACHN_ID" in c409
    assert "CREATE TABLE IF NOT EXISTS consent_records" not in c409
    src = (ROOT / "backend/app/routers/sovereign_studio_api.py").read_text()
    assert "studio_screener_service" in src
    assert "studio_tier2" in src
    assert "regenerate" in src
    assert "youtube/callback" in src
    assert "livekit/events" in src
    assert "ln-scan" in src
    assert "cohost/turn" in src
    assert "cohost/caption" in src
    assert "cohost/speak" in src
    dart = (ROOT / "mobile/lib/widgets/coach_sovereign_studio_tab.dart").read_text()
    assert "EPISODE REVIEW" in dart
    assert "Little Nate (co-host)" in dart
    assert "Dump locked" in dart
    assert "Connect YouTube" in dart
    assert "Speaker transcript" in dart
    assert "Open studio room" in dart
    assert "SESSION VIEW" in dart
    html = (ROOT / "mobile/web/studio_livekit_room.html").read_text()
    assert "livekit-client.umd.min.js" in html
    assert "cdn.jsdelivr.net" not in html
    assert "setCameraEnabled(false)" in html
    boot = (ROOT / "scripts/orange/livekit_bootstrap.sh").read_text()
    assert "APPLY" in boot
    assert "11434" in boot
    assert "10.13.13.5" in boot


def test_sms_reply_and_autoscale():
    assert parse_sms_reply("YES") == "opt_in"
    assert parse_sms_reply("STOP") == "opt_out"
    assert parse_sms_reply("hello") == "ignore"
    assert scale_hint(0)["workers"] == 1
    assert scale_hint(12)["workers"] == 3


def test_inv6_prescan_and_envelope():
    blocked = prescan_outgoing("I will diagnose you")
    assert blocked["blocked"] is True
    assert blocked["pre_synthesis"] is True
    ok = prescan_outgoing("Let's talk about sleep habits")
    assert ok["ok"] is True
    frame = envelope_frame(0.5)
    assert frame["photoreal"] is False
    assert len(frame["points"]) == 24


def test_youtube_state_and_livekit_jwt():
    st = _sign_state("COACH_COACHN_ID")
    assert parse_state(st) == "COACH_COACHN_ID"
    assert parse_state("bad") is None
    tok = mint_livekit_jwt(
        api_key="key",
        api_secret="secret",
        room="studio-1",
        identity="host",
        role="guest",
    )
    assert tok.count(".") == 2

    def _jwt_body(raw: str) -> dict:
        import base64
        import json

        part = raw.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))

    guest_video = _jwt_body(tok)["video"]
    assert guest_video["canPublish"] is True
    assert guest_video["canPublishSources"] == [2]
    host = mint_livekit_jwt(
        api_key="key",
        api_secret="secret",
        room="studio-1",
        identity="host",
        role="host",
    )
    host_video = _jwt_body(host)["video"]
    assert host_video["canPublish"] is True
    assert "canPublishSources" not in host_video
    host_body = _jwt_body(host)
    assert host_body["exp"] - host_body["nbf"] >= 28000
    guest = join_token_stub("sid", "guest")
    assert guest["allow_video"] is False


def test_s4_room_meter_sip():
    from datetime import datetime, timezone

    url = room_embed_url("wss://lk.example", "tok", "guest")
    assert "studio_livekit_room.html" in url
    assert "role=guest" in url
    plan = egress_plan("sid-1", rtmp_url="rtmp://x", live_unlocked=False)
    assert plan["delay_s"] == 45
    assert plan["rtmp"] is False
    assert plan["photoreal"] is False
    minted = join_token("abc", "guest", identity="g1")
    assert minted["room_url"]
    assert minted["allow_video"] is False
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 18, 12, 30, tzinfo=timezone.utc)
    assert session_minutes(start, end) == 30.0
    assert sip_join_allowed("")["code"] == 403
    assert sip_join_allowed("abc")["ok"] is True
    assert "<Reject" in sip_ingress_twiml("")
    assert normalize_e164("(561) 783-3006") == COACHN_DID
    assert normalize_e164("5617833006") == "+15617833006"
    sql411 = (ROOT / "backend/migrations/411_studio_coachn_did.sql").read_text()
    assert "+15617833006" in sql411
    assert "COACH_COACHN_ID" in sql411
    src = (ROOT / "backend/app/services/studio_did_service.py").read_text()
    assert "incoming_phone_numbers.create" in src
    assert "attach_existing_did" in src
    assert "purchased" in src


def test_s4_apply_probe_egress_billing_autoscale():
    import asyncio

    start_room_egress = _lk.start_room_egress
    post_session_billing = _meter.post_session_billing
    StudioScreenerAutoscaleAgent = _as.StudioScreenerAutoscaleAgent

    h = _lk.health()
    assert h["node"] == "orange"
    assert h["allow_video_guest"] is False
    assert "internal_reachable" in h
    plan = asyncio.run(start_room_egress("sid-apply"))
    assert plan["delay_s"] == 45
    assert plan["started"] is False
    assert plan["reason"] == "livekit_not_configured"
    billed = asyncio.run(post_session_billing(None, "show", "COACH_COACHN_ID", 12))
    assert billed["dry"] is True
    agent = StudioScreenerAutoscaleAgent(None)
    assert agent.last_hint["workers"] == 1
    html = _lk.ROOM_HTML
    assert "captureStream" in html
    assert "ln-envelope" in html
    assert "cdn.jsdelivr.net" not in html
    assert "btnMute" in html
    assert "Toss to Nate" in html
    assert "hostVid" in html
    assert "setCameraEnabled(true)" in html
    assert "LIVE WITH LITTLE NATE" in html
    assert "LITTLE NATE (CO-HOST)" in html
    assert "AI CO-HOST" not in html
    assert "/avatar-modes/studio_portrait.html" in html
    assert "expression_viewer.html" not in html
    portrait = (ROOT / "mobile/web/avatar-modes/studio_portrait.html").read_text()
    assert "plates/exp_01_neutral.png" in portrait
    assert "plates/exp_03_jawopen.png" in portrait
    assert "setExpression" in portrait
    assert "setVoiceState" in portrait
    assert "lil_nate.glb" not in portrait
    assert (ROOT / "mobile/web/avatar-modes/plates/exp_01_neutral.png").is_file()
    assert (ROOT / "mobile/web/avatar-modes/plates/exp_06_brow_up.png").is_file()
    assert "mininate_neutral.glb" in (ROOT / "mobile/web/avatar-modes/expression_viewer.html").read_text()
    assert "lil_nate.glb" not in (ROOT / "mobile/web/avatar-modes/expression_viewer.html").read_text()
    assert (ROOT / "mobile/web/avatar-modes/mininate_neutral.glb").is_file()
    assert (ROOT / "mobile/web/avatar-modes/vendor/three.module.js").is_file()
    assert "/cohost/turn" in html
    assert "/cohost/caption" in html
    assert "/cohost/speak" in html
    assert "nateSpeaker" in html
    assert "echoCancellation" in html
    assert "holdHostMic" not in html
    assert "Room link expired" in html
    assert "MediaRecorder" in html
    assert "drainTurns" in html
    assert "recd.start();" in html
    assert "recd.start(2400)" not in html
    assert "speakBrowser(text)" not in html
    assert "ActiveSpeakersChanged" in html
    assert "caller_join" in html
    assert "grid-template-columns:1fr 1fr 1fr" in html
    assert "object-fit:cover" in html
    tok = _lk.mint_livekit_jwt(
        api_key="k",
        api_secret="s",
        room="studio-sid-1",
        identity="host",
        role="host",
    )
    import os

    os.environ["LIVEKIT_API_KEY"] = "k"
    os.environ["LIVEKIT_API_SECRET"] = "s"
    v = _lk.verify_livekit_jwt(tok)
    assert v["ok"] is True
    assert v["session_id"] == "sid-1"
    url = _lk.room_embed_url("wss://x", tok, "host", "sid-1")
    assert "session=sid-1" in url
    turn = asyncio.run(_sess.cohost_turn(None, "sid-1", "hello from the host"))
    assert turn["ok"] is True
    assert turn["text"]
    opened = asyncio.run(
        _sess.cohost_turn(None, "sid-1", "podcast room live", event="open", callers=1)
    )
    assert opened["ok"] is True
    assert opened.get("event") == "open"
    captioned = asyncio.run(
        _sess.cohost_turn(
            None,
            "sid-1",
            "HOST: welcome in\nCALLER: what is sovereignty?",
            event="caption",
            callers=1,
        )
    )
    assert captioned["ok"] is True
    assert captioned.get("event") == "caption"
    assert _sess.caption_should_ask("CALLER: what is sovereignty?") is True
    assert _sess.caption_should_ask("ok") is False
    assert _sess.caption_should_ask("late.") is False
    quiet = asyncio.run(_sess.ingest_live_caption(b"", speaker="caller"))
    assert quiet["ok"] is False
    assert quiet["reason"] == "no_speech"
    spoken = asyncio.run(_sess.synthesize_cohost_line(""))
    assert spoken == b""
    src_sess = (ROOT / "backend/app/services/studio_session_service.py").read_text()
    assert "synthesize_studio_voice" in src_sess
    assert 'tts_provider="azure_premium"' in src_sess
    assert 'voice="onyx"' in src_sess
    assert 'tts_provider="edge_tts"' not in src_sess
    assert 'voice="nate_warm"' not in src_sess
    voice_src = (ROOT / "backend/app/services/studio_phone_voice.py").read_text()
    assert 'GROK_VOICE' in voice_src
    assert 'voice": "Rex"' in voice_src or 'GROK_VOICE' in voice_src
    assert "2025-04-01-preview" in voice_src
    assert 'voice": "onyx"' in voice_src
    assert "trusted older brother" in voice_src
    assert "nateTurn(blob, false, 'caption')" not in html
    assert "event:'open')" not in html
    assert "caller_join" in html
    from app.services.studio_phone_voice import studio_audio_media_type

    assert studio_audio_media_type(b"RIFF____WAVE") == "audio/wav"
    blocked = asyncio.run(_sess.cohost_turn(None, "sid-1", "please diagnose this therapy case"))
    assert blocked["ok"] is True
    assert blocked.get("redirect") is True
    assert (ROOT / "mobile/web/livekit-client.umd.min.js").is_file()
    ngx = (ROOT / "nginx/snippets/health-livekit.conf").read_text()
    assert "location /livekit/" in ngx
    assert "10.13.13.5:7880" in ngx
    main = (ROOT / "backend/app/main.py").read_text()
    assert "studio_screener_autoscale" in main
    dart = (ROOT / "mobile/lib/widgets/coach_sovereign_studio_tab.dart").read_text()
    assert "/egress" in dart
    pin = (ROOT / "scripts/cf_pin_ln_observer_lb.sh").read_text()
    assert "/livekit" in pin
