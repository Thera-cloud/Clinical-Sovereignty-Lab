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
verify_livekit_jwt = _lk.verify_livekit_jwt
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
    assert "apply-cuts" in src
    assert "cohost/turn" in src
    assert "cohost/caption" in src
    assert "cohost/speak" in src
    dart = (ROOT / "mobile/lib/widgets/coach_sovereign_studio_tab.dart").read_text()
    assert "EPISODE REVIEW" in dart
    assert "Apply cuts" in dart
    assert "tape ready" in dart
    assert "Tab(text: 'EDIT')" in dart
    assert "Add keep range" in dart
    assert "Watch tape" in dart
    assert "_KeepRange" in dart
    assert "Little Nate (co-host)" in dart
    assert "Dump locked" in dart
    assert "Connect YouTube" in dart
    assert "Speaker transcript" in dart
    assert "Open studio room" in dart
    assert "SESSION VIEW" in dart
    html = (ROOT / "mobile/web/studio_livekit_room.html").read_text()
    nate_html = (ROOT / "mobile/web/studio_nate_room.html").read_text()
    assert html == nate_html
    assert "livekit-client.umd.min.js" in html
    assert "cdn.jsdelivr.net" not in html
    assert "setCameraEnabled(false)" in html
    boot = (ROOT / "scripts/orange/livekit_bootstrap.sh").read_text()
    assert "APPLY" in boot
    assert "11434" in boot
    assert "10.13.13.5" in boot
    assert "redis:" in boot
    assert "/api/studio/livekit/events" in boot


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
    assert "studio_nate_room.html" in url
    assert "role=guest" in url
    plan = egress_plan("sid-1", rtmp_url="rtmp://x", live_unlocked=False)
    assert plan["delay_s"] == 45
    assert plan["rtmp"] is False
    assert plan["photoreal"] is False
    assert plan["media_r2_key"] == "studio/sid-1.mp4"
    minted = join_token("abc", "guest", identity="g1")
    assert minted["room_url"]
    assert minted["allow_video"] is False
    host_mint = join_token("abc", "host")
    if host_mint.get("jwt"):
        assert verify_livekit_jwt(host_mint["token"]).get("identity", "").startswith("host-")
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
    assert "egress_worker" in h
    assert h["egress_worker"] is False
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
    assert "v=20260901q" in html
    assert "}, 2500);" in html
    assert "}, 450);" not in html
    assert "function waitLabel" in html
    assert "n > 10 ? '10+'" in html
    assert "ACTIVE CALLER" in html
    assert "CALLER ID 1" in html
    assert "JOIN THE CALL" in html
    assert 'id="rail"' in html
    assert 'id="hosts"' in html
    assert "grid-template-columns:1fr 1fr 1fr" not in html
    sess_src = (ROOT / "backend/app/services/studio_session_service.py").read_text()
    assert "max_tokens=400 if howto else 280" in sess_src
    assert "max_tokens=160 if howto else 120" not in sess_src
    voice_src = (ROOT / "backend/app/services/studio_phone_voice.py").read_text()
    assert "time() + 28.0" in voice_src
    assert "time() + 10.0" not in voice_src
    assert "expression_viewer.html" not in html
    assert "speakGen" in html
    assert "pendingCaps.slice(-24)" in html
    assert "pendingCaps.slice(-8)" not in html
    portrait = (ROOT / "mobile/web/avatar-modes/studio_portrait.html").read_text()
    assert "thera_world_bg.jpg" in portrait
    assert "function keyPlate" in portrait
    assert "function isBg" in portrait
    assert 'id="face"' in portrait
    assert "object-position:center 22%" not in portrait
    assert "plates/exp_01_neutral.png" in portrait
    assert "plates/exp_03_jaw_mouth.png" in portrait
    assert (ROOT / "mobile/web/avatar-modes/thera_world_bg.jpg").is_file()
    assert "setJawMix" in portrait
    assert "armTalk" in portrait
    assert "talkOpen" not in portrait
    assert "setExpression" in portrait
    assert "setVoiceState" in portrait
    assert "lil_nate.glb" not in portrait
    assert (ROOT / "mobile/web/avatar-modes/plates/exp_01_neutral.png").is_file()
    assert (ROOT / "mobile/web/avatar-modes/plates/exp_03_jaw_mouth.png").is_file()
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
    assert "grid-template-columns:1fr 1fr" in html
    assert "grid-template-columns:1fr 1fr 1fr" not in html
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
    assert "v=20260902u" in url
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
    assert "PRODUCT_BRIEF" in src_sess
    assert "SHOW_VOICE" in src_sess
    assert "asks_app_howto(blob)" in src_sess
    assert "asks_app_howto(thread_text" not in src_sess
    assert "remember_line" in src_sess
    assert "THIS_SHOW" in src_sess
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
    assert "deliverHold(blob, 'caption')" in html
    assert "var CAP_FRESH_MS = 20000;" in html
    assert "function freshCaps" in html
    assert "if (!fresh.length) return;" in html
    assert "capQueue.push({at: capAt, line: who + ': ' + j.text})" in html
    assert "var LISTEN_SILENCE_MS = 6000;" in html
    assert "function holdFloorMs" in html
    assert "function primeHold" in html
    assert "function deliverHold" in html
    assert "holdTurnBody(t, 'prime')" in html
    assert "rec.continuous = true;" in html
    assert "function releaseCapSoon" in html
    assert "}, 1200);" not in html
    assert "}, 2800);" not in html
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
    assert "/api/studio" in pin
    boot = (ROOT / "scripts/orange/livekit_egress_bootstrap.sh").read_text()
    assert "livekit/egress" in boot
    assert "APPLY" in boot
    assert "/out/config.yaml" in boot
    assert "chmod 644" in boot
    clone_pin = (ROOT / "nginx/snippets/clone-pin-to-primary.conf").read_text()
    assert "location /api/studio" in clone_pin
    assert "10.120.0.2" in clone_pin
    dart = (ROOT / "mobile/lib/widgets/coach_sovereign_studio_tab.dart").read_text()
    assert "Duration(seconds: 8)" in dart
    assert "_scheduleEgress" in dart
    assert "stop_session_egress" in (
        ROOT / "backend/app/services/studio_session_service.py"
    ).read_text()


def test_studio_product_thread_and_onair_guards():
    from app.services.studio_product_brief import (
        PRODUCT_BRIEF,
        SHOW_VOICE,
        asks_app_howto,
        blocks_competitor,
        blocks_ip_leak,
        sanitize_onair,
    )

    assert asks_app_howto("tell us how it works") is True
    assert asks_app_howto("what can Little Nate do for coaches") is True
    assert asks_app_howto("good morning everyone") is False
    assert asks_app_howto("that's a cool feature of the conversation") is False
    assert "jason kelce" in SHOW_VOICE.lower()
    assert "not a therapist" in SHOW_VOICE.lower()
    assert "not mirror" in SHOW_VOICE.lower()
    assert "when you actually want to know" in SHOW_VOICE.lower()
    assert "never end with a question" not in SHOW_VOICE.lower()
    sess_src = (ROOT / "backend/app/services/studio_session_service.py").read_text()
    assert "Do not default to the app" in sess_src
    assert "Coach style note" not in sess_src
    assert 'domain="culture"' in sess_src
    assert "No follow-up question" not in sess_src
    held = sanitize_onair("Nice take. I will wait for your response.")
    assert "wait for your" not in held.lower()
    assert "nice take" in held.lower()
    mirrored = sanitize_onair(
        "It sounds like you're carrying a lot. What's coming up for you? That stuff is heavy."
    )
    assert "sounds like" not in mirrored.lower()
    assert "coming up for you" not in mirrored.lower()
    assert "heavy" in mirrored.lower()
    # A natural co-host question survives the guard.
    asked = sanitize_onair("Sovereignty is just keeping your own mind. You ever try that?")
    assert "you ever try that?" in asked.lower()
    assert "sovereignty" in asked.lower()
    # Natural radio hand-offs are not stage direction.
    assert "back to you" in sanitize_onair("That's my take. Back to you, host.").lower()

    from app.services.studio_product_brief import drop_trailing_question, ends_with_question

    assert ends_with_question("You ever try that?") is True
    assert ends_with_question("Nah, I don't buy it.") is False
    assert drop_trailing_question("That's wild. You ever try that?") == "That's wild."
    # Never empty out a reply that is only a question.
    assert drop_trailing_question("You ever try that?") == "You ever try that?"
    assert "_last_nate_line" in (ROOT / "backend/app/services/studio_session_service.py").read_text()
    assert "app.sovereignsanctuary.net" in PRODUCT_BRIEF
    assert "Coach Command" in PRODUCT_BRIEF
    assert "Family Sanctuary" in PRODUCT_BRIEF
    assert "grok" not in PRODUCT_BRIEF.lower()
    assert "azure" not in PRODUCT_BRIEF.lower()
    assert "crystal" not in PRODUCT_BRIEF.lower()
    assert "patent" not in PRODUCT_BRIEF.lower()
    assert blocks_competitor("try BetterHelp instead") is True
    assert blocks_ip_leak("we run this on Azure and Grok") is True
    clean = sanitize_onair("You should download Calm or BetterHelp tonight")
    assert "betterhelp" not in clean.lower()
    assert "calm" not in clean.lower()
    assert "Sovereign Sanctuary" in clean
    _sess.remember_line("sid-thread", "HOST", "we are talking about the Little Nate app")
    _sess.remember_line("sid-thread", "HOST", "tell us how it works")
    prior = _sess.thread_text("sid-thread")
    assert "Little Nate app" in prior
    assert "how it works" in prior

def test_studio_realm_rotation():
    """Thera-world realms rotate behind Nate: catalog, frame serve, slide, context."""
    rot = load_svc("studio_realm_rotator")

    # Rotation walks the catalog in order and wraps, so a long show tours
    # realms instead of landing on the same one twice.
    assert rot.REALM_ROTATE_SECONDS == 180
    slugs = [r["slug"] for r in rot.REALMS]
    assert len(slugs) == len(set(slugs)) >= 8
    assert rot.next_slug("") == slugs[0]
    assert rot.next_slug(slugs[0]) == slugs[1]
    assert rot.next_slug(slugs[-1]) == slugs[0]
    for r in rot.REALMS:
        assert r["name"] and r["blurb"] and r["prompt"]

    # Every prompt carries the composite style so the center third stays open
    # for Nate and no stray people or text land in the backdrop.
    p = rot.realm_prompt(slugs[0])
    assert "no people" in p and "no text" in p
    assert "center must stay open" in p

    # Realm zero is the static plate, so the room is never blank on join.
    assert rot.BASELINE_REALM["image_url"] == "thera_world_bg.jpg"
    assert rot.BASELINE_REALM["frame_id"] == 0

    # Frames are served with their real format, not a hardcoded jpeg claim.
    assert rot.image_media_type(b"\xff\xd8\xffsomething") == "image/jpeg"
    assert rot.image_media_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert rot.image_media_type(b"RIFF____WEBPVP8 ") == "image/webp"
    assert rot.image_media_type(b"nope") == "application/octet-stream"

    # No DB pool means no frame table and no image spend.
    import asyncio

    assert asyncio.run(rot.realm_image_bytes(None, "sid-realm", 7)) is None

    api_src = (ROOT / "backend/app/routers/sovereign_studio_api.py").read_text()
    assert '@public_router.get("/sessions/{session_id}/realm")' in api_src
    assert '@public_router.get("/sessions/{session_id}/realm/{frame_id}")' in api_src
    # Frames are per-room, so the shared edge must not cache them publicly.
    assert "private, max-age=86400, immutable" in api_src
    assert "realm_blurb" in api_src and "realm_shift" in api_src

    assert (ROOT / "backend/migrations/430_studio_realm_frames.sql").exists()
    mig = (ROOT / "backend/migrations/430_studio_realm_frames.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS studio_realm_frames" in mig
    assert "ALTER TABLE" not in mig and "DROP " not in mig

    # Nate always knows the realm; he is told to work it in, never announce it.
    sess_src = (ROOT / "backend/app/services/studio_session_service.py").read_text()
    assert "WHERE YOU ARE" in sess_src
    assert "Never announce it as a status update." in sess_src
    assert "The realm just shifted in behind you this second." in sess_src

    # Horizontal wipe: old realm exits left, new realm lands. Nate never moves.
    portrait = (ROOT / "mobile/web/avatar-modes/studio_portrait.html").read_text()
    assert 'id="worldNext"' in portrait
    assert "translateX(-100%)" in portrait
    assert "img-src 'self' blob:" in portrait
    assert "revokeObjectURL" in portrait
    assert "function setRealm" in portrait

    # All six room copies poll and hand the frame over as a Blob.
    for rel in (
        "mobile/web/studio_nate_room.html",
        "mobile/web/studio_livekit_room.html",
        "backend/app/services/studio_nate_room.html",
        "backend/app/services/studio_livekit_room.html",
        "dashboard/studio_nate_room.html",
        "dashboard/studio_livekit_room.html",
    ):
        room = (ROOT / rel).read_text()
        assert "function pollRealm" in room, rel
        assert "function applyRealm" in room, rel
        assert "type:'setRealm'" in room, rel
        assert "realm_shift" in room, rel
        assert "function holdFloorMs" in room, rel
        assert "function primeHold" in room, rel
        assert "var LISTEN_SILENCE_MS = 6000;" in room, rel
        # The wait badge cannot be squeezed by the rail flex, or the count clips.
        assert "flex:0 0 auto;margin-top:auto" in room, rel
        assert "line-height:1.3;color:#C9A962" in room, rel
        assert 'id="shareTile"' in room, rel
        assert "#hosts.sharing" in room, rel
        assert 'id="btnShare"' in room, rel
        assert "getDisplayMedia" in room, rel
        assert "function playStudioSfx" in room, rel
        assert "function doLookup" in room, rel
        assert "share_kind" in room, rel
        assert "function grabShareJpeg" in room, rel
        assert "function pushShareFrame" in room, rel
        assert "cohost/share-frame" in room, rel


def test_studio_share_host_only():
    share = load_svc("studio_cohost_share")
    assert share.is_studio_host_identity("COACH_COACHN_ID")
    assert share.is_studio_host_identity("host-abc123")
    assert not share.is_studio_host_identity("guest-xyz")
    assert not share.is_studio_host_identity("caller-1")
    assert not share.is_studio_host_identity("egress")
    assert share.resolve_sound("sting")["ok"]
    assert share.resolve_sound("sting hit")["ok"]
    assert share.resolve_sound("explode")["ok"] is False
    assert share.safe_https_url("https://example.com/a") 
    assert share.safe_https_url("http://example.com") is None
    assert share.safe_https_url("https://127.0.0.1/x") is None
    card = share.host_url_card("https://example.com/pic.png")
    assert card["ok"] and card["image"]
    note = share.share_note("search", "Nevedal", [{"title": "One"}])
    assert "One" in note and "Nevedal" in note

    assert share.note_has_seen_content("Host is sharing a window.") is False
    assert share.note_has_seen_content("Host opened notes.pdf") is False
    assert share.note_has_seen_content("On screen: Clinical Sovereignty Lab patent claims") is True
    share.remember_share_frame("sess-vis", "Patent title visible on the page", "abc")
    seen = share.share_seen("sess-vis")
    assert seen["note"].startswith("Patent")
    assert share.merge_share_note("Host is sharing a window.", seen["note"]).startswith("Patent")
    share.forget_share_frame("sess-vis")
    assert share.share_seen("sess-vis") == {}
    import asyncio

    empty = asyncio.run(share.describe_share_frame(b""))
    assert empty["ok"] is False

    api_src = (ROOT / "backend/app/routers/sovereign_studio_api.py").read_text()
    assert '/sessions/{session_id}/cohost/share' in api_src
    assert '/sessions/{session_id}/cohost/share-frame' in api_src
    assert '/sessions/{session_id}/cohost/sound' in api_src
    assert "host_only" in api_src
    assert "_require_host_jwt" in api_src

    sess_src = (ROOT / "backend/app/services/studio_session_service.py").read_text()
    assert "ON SCREEN" in sess_src
    assert "share_kind" in sess_src
    assert "never when a caller asks" in sess_src
    assert "cannot see the page yet" in sess_src
    assert "images=[jpeg] if jpeg else None" in sess_src
    assert "needs_eyes" in sess_src


def test_studio_caller_queue_wiring():
    cq = load_svc("studio_caller_queue")
    lk = load_svc("studio_livekit")
    assert cq.move_waiting(["a", "b", "c"], "b", -1) == ["b", "a", "c"]
    assert cq.move_waiting(["a", "b", "c"], "b", 1) == ["a", "c", "b"]
    ident = cq.caller_identity("12345678-1234-1234-1234-123456789abc")
    assert ident == "caller-12345678"
    assert "send_room_data" in dir(lk)
    assert "list_room_participants" in dir(lk)
    api = (ROOT / "backend/app/routers/sovereign_studio_api.py").read_text()
    assert "/sessions/{session_id}/queue" in api
    assert "/sessions/{session_id}/callers" in api
    dart = (ROOT / "mobile/lib/widgets/coach_sovereign_studio_tab.dart").read_text()
    assert "CALLER BOARD" in dart
    assert "Copy RSS feed URL" in dart
    assert "Reject" in dart
    assert "COMPLIANCE FLAGS" in dart
