"""S4 LiveKit + INV-2 guest audio-only. JWT if env set. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from app.services.studio_invariants import guest_video_allowed

DELAY_S = 45

ROOM_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Sovereign Studio Room</title>
<style>
body{margin:0;background:#050505;color:#E8D5A3;font-family:DM Sans,sans-serif}
#bar{padding:12px 16px;border-bottom:1px solid #222;color:#C9A962;letter-spacing:1px;font-size:12px}
#status{padding:8px 16px;color:#8B7355;font-size:12px}
#board{display:flex;gap:12px;padding:12px;flex-wrap:wrap}
.tile{background:#111;border:1px solid #222;border-radius:8px;min-width:220px;flex:1}
.tile h3{margin:0;padding:8px 10px;font-size:11px;color:#C9A962;letter-spacing:1px}
.tile .box{width:100%;height:180px;background:#0A0A0A;display:flex;align-items:center;justify-content:center;overflow:hidden}
.tile video,.tile canvas{width:100%;height:180px;object-fit:cover;background:#0A0A0A}
#wait{padding:0 12px 8px;color:#8B7355;font-size:12px}
#dock{position:sticky;bottom:0;padding:10px 12px;border-top:1px solid #222;background:#0A0A0A;display:flex;flex-wrap:wrap;gap:8px}
#dock button{background:#111;color:#E8D5A3;border:1px solid #8B7355;border-radius:6px;padding:8px 12px;font-size:12px;cursor:pointer}
#dock button.on{border-color:#C9A962;color:#C9A962}
#dock button.warn{border-color:#EF4444;color:#EF4444}
#dock .meta{color:#8B7355;font-size:11px;align-self:center}
</style>
</head>
<body>
<div id="bar">SOVEREIGN STUDIO · AI co-host and knowledge companion</div>
<div id="status">Connecting…</div>
<div id="board">
  <div class="tile" id="hostTile"><h3>HOST</h3><div class="box" id="hostBox"><video id="hostVid" autoplay muted playsinline></video></div></div>
  <div class="tile" id="lnTile"><h3>AI CO-HOST</h3><div class="box"><canvas id="env" width="160" height="160"></canvas></div></div>
  <div class="tile" id="callerTile"><h3>CALLERS (audio)</h3><div class="box" id="callers"><span id="callerEmpty" style="color:#8B7355;font-size:12px">No live callers</span></div></div>
</div>
<div id="wait">Waiting room: none</div>
<div id="dock">
  <button id="btnMute" type="button">Mute</button>
  <button id="btnCam" type="button">Camera</button>
  <button id="btnToss" type="button">Toss to Nate</button>
  <button id="btnPause" type="button">Pause LN</button>
  <button id="btnBring" type="button">Bring on</button>
  <button id="btnHold" type="button">Hold</button>
  <button id="btnDrop" type="button">Drop</button>
  <button id="btnEnd" class="warn" type="button">End session</button>
  <button id="btnDump" type="button" disabled>Dump locked</button>
  <span class="meta">Delay 45s · RTMP pending</span>
</div>
<script src="/livekit-client.umd.min.js"></script>
<script>
(function(){
  var room = null, micOn = true, camOn = false, lnPaused = false, waiting = [];
  function params(){
    var h = new URLSearchParams(location.hash.replace(/^#/, ''));
    var q = new URLSearchParams(location.search);
    return {
      url: h.get('url') || q.get('url') || '',
      token: h.get('token') || q.get('token') || '',
      role: (h.get('role') || q.get('role') || 'host').toLowerCase()
    };
  }
  function drawEnv(level){
    var c = document.getElementById('env');
    var ctx = c.getContext('2d');
    ctx.clearRect(0,0,160,160);
    ctx.strokeStyle = '#C9A962';
    ctx.beginPath();
    for (var i=0;i<24;i++){
      var ang = (i/24)*Math.PI*2;
      var r = 40 + 28*level*(0.65+0.35*Math.sin(i*1.7));
      var x = 80 + r*Math.cos(ang);
      var y = 80 + r*Math.sin(ang);
      if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    }
    ctx.closePath(); ctx.stroke();
  }
  function setStatus(t){ document.getElementById('status').textContent = t; }
  function renderWait(){
    document.getElementById('wait').textContent = waiting.length
      ? ('Waiting room: ' + waiting.join(', ')) : 'Waiting room: none';
  }
  function previewCam(){
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
    navigator.mediaDevices.getUserMedia({video:true, audio:false}).then(function(ms){
      var v = document.getElementById('hostVid');
      v.srcObject = ms;
      v.play().catch(function(){});
    }).catch(function(){});
  }
  function attachLocalCam(){
    if (!room || !room.localParticipant) return;
    room.localParticipant.videoTrackPublications.forEach(function(pub){
      if (!pub.track) return;
      var src = pub.source;
      var isCam = (LK.Track && LK.Track.Source && src === LK.Track.Source.Camera) || src === 'camera';
      if (!isCam) return;
      var el = pub.track.attach();
      el.muted = true; el.autoplay = true; el.playsInline = true;
      var box = document.getElementById('hostBox');
      box.innerHTML = '';
      box.appendChild(el);
    });
  }
  function sendOp(op){
    if (!room) return;
    try {
      var raw = JSON.stringify({op: op});
      if (room.localParticipant.publishData) {
        room.localParticipant.publishData(new TextEncoder().encode(raw), {reliable:true});
      }
    } catch (e) {}
    setStatus('Host · ' + op);
  }
  drawEnv(0.35);
  var p = params();
  var guest = p.role === 'guest';
  if (guest) document.getElementById('btnCam').style.display = 'none';
  if (!p.url || !p.token){
    setStatus('LiveKit pending — set LIVEKIT_URL + JWT, then Start session.');
    return;
  }
  var LK = window.LivekitClient;
  if (!LK || !LK.Room){
    setStatus('LiveKit client failed to load.');
    return;
  }
  previewCam();
  room = new LK.Room({adaptiveStream:true, dynacast:true});
  room.on(LK.RoomEvent.TrackSubscribed, function(track, pub, participant){
    var empty = document.getElementById('callerEmpty');
    if (empty) empty.remove();
    var el = track.attach();
    el.autoplay = true;
    document.getElementById('callers').appendChild(el);
    waiting = waiting.filter(function(n){ return n !== participant.identity; });
    renderWait();
  });
  room.on(LK.RoomEvent.ParticipantConnected, function(participant){
    waiting.push(participant.identity || 'caller');
    renderWait();
  });
  room.on(LK.RoomEvent.ParticipantDisconnected, function(participant){
    waiting = waiting.filter(function(n){ return n !== participant.identity; });
    renderWait();
  });
  room.on(LK.RoomEvent.LocalTrackPublished, attachLocalCam);
  room.connect(p.url, p.token).then(function(){
    return room.localParticipant.setMicrophoneEnabled(true);
  }).then(function(){
    if (guest) return room.localParticipant.setCameraEnabled(false);
    return room.localParticipant.setCameraEnabled(true).then(function(){
      camOn = true;
      attachLocalCam();
      var stream = document.getElementById('env').captureStream(12);
      var vt = stream && stream.getVideoTracks()[0];
      if (!vt) return;
      var t = 0;
      setInterval(function(){
        if (lnPaused) return;
        t += 1;
        drawEnv(0.28 + 0.45*Math.abs(Math.sin(t/8)));
      }, 80);
      var opts = {name:'ln-envelope'};
      if (LK.Track && LK.Track.Source) opts.source = LK.Track.Source.ScreenShare;
      return room.localParticipant.publishTrack(vt, opts).catch(function(){ return null; });
    });
  }).then(function(){
    setStatus(guest ? 'Guest audio-only (INV-2).' : 'Host + envelope avatar.');
  }).catch(function(e){
    setStatus('Connect failed: ' + e);
  });
  document.getElementById('btnMute').onclick = function(){
    if (!room) return;
    micOn = !micOn;
    room.localParticipant.setMicrophoneEnabled(micOn);
    this.textContent = micOn ? 'Mute' : 'Unmute';
    this.classList.toggle('on', !micOn);
  };
  document.getElementById('btnCam').onclick = function(){
    if (!room || guest) return;
    camOn = !camOn;
    room.localParticipant.setCameraEnabled(camOn).then(attachLocalCam);
    this.classList.toggle('on', camOn);
  };
  document.getElementById('btnToss').onclick = function(){ sendOp('toss'); };
  document.getElementById('btnPause').onclick = function(){
    lnPaused = !lnPaused;
    this.textContent = lnPaused ? 'Resume LN' : 'Pause LN';
    this.classList.toggle('on', lnPaused);
    sendOp(lnPaused ? 'pause_ln' : 'resume_ln');
  };
  document.getElementById('btnBring').onclick = function(){
    if (!waiting.length){ setStatus('Waiting room empty.'); return; }
    sendOp('bring_on:' + waiting[0]);
  };
  document.getElementById('btnHold').onclick = function(){ sendOp('hold'); };
  document.getElementById('btnDrop').onclick = function(){ sendOp('drop'); };
  document.getElementById('btnEnd').onclick = function(){
    if (room) room.disconnect();
    setStatus('Session ended. Close this tab or End → review in Studio.');
  };
})();
</script>
</body>
</html>
"""


def room_origin() -> str:
    return os.getenv("STUDIO_ROOM_ORIGIN", "https://coach.sovereignsanctuary.net").rstrip("/")


def room_embed_url(lk_url: str, token: str, role: str) -> str:
    q = urlencode({"url": lk_url or "", "token": token or "", "role": role or "host"})
    return f"{room_origin()}/studio_livekit_room.html#{q}"


def egress_plan(session_id: str, rtmp_url: str = "", live_unlocked: bool = False) -> Dict[str, Any]:
    return {
        "ok": True,
        "session_id": session_id,
        "delay_s": DELAY_S,
        "composited": True,
        "avatar": "audio_envelope",
        "photoreal": False,
        "rtmp": bool(rtmp_url) and live_unlocked,
        "rtmp_url_set": bool(rtmp_url),
        "dump_cuts_delayed_output": True,
        "installed": bool(os.getenv("LIVEKIT_INTERNAL_URL")),
    }


def _probe_internal() -> Dict[str, Any]:
    internal = (os.getenv("LIVEKIT_INTERNAL_URL") or "").rstrip("/")
    if not internal:
        return {"reachable": False, "reason": "unset"}
    try:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(internal + "/", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return {"reachable": True, "code": int(resp.status)}
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code:
            return {"reachable": True, "code": int(code)}
        return {"reachable": False, "reason": str(exc)[:80]}


def health() -> Dict[str, Any]:
    url = os.getenv("LIVEKIT_URL", "")
    internal = os.getenv("LIVEKIT_INTERNAL_URL", "")
    probe = _probe_internal()
    ready = bool(url) and bool(os.getenv("LIVEKIT_API_KEY")) and probe.get("reachable")
    return {
        "status": "ok" if ready else "pending",
        "url_configured": bool(url),
        "jwt_configured": bool(os.getenv("LIVEKIT_API_KEY") and os.getenv("LIVEKIT_API_SECRET")),
        "allow_video_guest": False,
        "node": "orange",
        "installed": bool(internal),
        "internal_configured": bool(internal),
        "internal_reachable": bool(probe.get("reachable")),
        "internal_probe": probe,
        "room_origin": room_origin(),
        "sip_uri_set": bool(os.getenv("LIVEKIT_SIP_URI")),
    }


def reject_guest_video(role: str, video_track_key: Optional[str]) -> Dict[str, Any]:
    if guest_video_allowed(role, video_track_key):
        return {"ok": True}
    return {"ok": False, "reason": "INV-2 guest video forbidden", "code": 422}


def join_token_stub(session_id: str, role: str) -> Dict[str, Any]:
    if role == "guest":
        return {
            "ok": True,
            "session_id": session_id,
            "role": "guest",
            "allowed_media_kinds": ["audio"],
            "allow_video": False,
        }
    return {
        "ok": True,
        "session_id": session_id,
        "role": role,
        "allowed_media_kinds": ["audio", "video"],
    }


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def mint_livekit_jwt(
    *,
    api_key: str,
    api_secret: str,
    room: str,
    identity: str,
    role: str,
    ttl_s: int = 3600,
) -> str:
    now = int(time.time())
    can_video = role != "guest"
    # Omit canPublishSources for host — string names decode as UNKNOWN and
    # canvas captureStream is screen_share, not camera. Guest: proto MICROPHONE=2.
    video = {
        "roomJoin": True,
        "room": room,
        "canPublish": True,
        "canSubscribe": True,
        "canPublishData": True,
        "roomRecord": True,
        "roomAdmin": can_video,
    }
    if not can_video:
        video["canPublishSources"] = [2]
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": api_key,
        "sub": identity or role,
        "nbf": now - 10,
        "exp": now + ttl_s,
        "video": video,
    }
    h = _b64(json.dumps(header, separators=(",", ":")).encode())
    p = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(api_secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64(sig)}"


def handle_event(body: Dict[str, Any]) -> Dict[str, Any]:
    event = str((body or {}).get("event") or (body or {}).get("event_type") or "").strip()
    return {
        "ok": True,
        "event": event or "unknown",
        "allow_video_guest": False,
        "installed": bool(os.getenv("LIVEKIT_INTERNAL_URL")),
    }


async def start_room_egress(
    session_id: str, rtmp_url: str = "", live_unlocked: bool = False
) -> Dict[str, Any]:
    plan = egress_plan(session_id, rtmp_url=rtmp_url, live_unlocked=live_unlocked)
    internal = (os.getenv("LIVEKIT_INTERNAL_URL") or "").rstrip("/")
    key = os.getenv("LIVEKIT_API_KEY", "")
    secret = os.getenv("LIVEKIT_API_SECRET", "")
    if not internal or not key or not secret:
        plan["started"] = False
        plan["reason"] = "livekit_not_configured"
        return plan
    token = mint_livekit_jwt(
        api_key=key,
        api_secret=secret,
        room=f"studio-{session_id}",
        identity="egress",
        role="host",
    )
    file_out: Dict[str, Any] = {
        "file_type": "MP4",
        "filepath": f"studio/{session_id}.mp4",
    }
    acct = os.getenv("R2_ACCOUNT_ID", "")
    r2_key = os.getenv("R2_ACCESS_KEY_ID", "")
    r2_secret = os.getenv("R2_SECRET_ACCESS_KEY", "")
    bucket = os.getenv("R2_DEFAULT_BUCKET", "nate-vault")
    if acct and r2_key and r2_secret:
        file_out["s3"] = {
            "access_key": r2_key,
            "secret": r2_secret,
            "region": "auto",
            "endpoint": f"https://{acct}.r2.cloudflarestorage.com",
            "bucket": bucket,
            "force_path_style": True,
        }
        plan["r2"] = True
    body: Dict[str, Any] = {
        "room_name": f"studio-{session_id}",
        "layout": "speaker",
        "audio_only": False,
        "file_outputs": [file_out],
    }
    if rtmp_url and live_unlocked:
        body["stream_outputs"] = [{"protocol": "RTMP", "urls": [rtmp_url]}]
    try:
        import httpx

        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                f"{internal}/twirp/livekit.Egress/StartRoomCompositeEgress",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        plan["http"] = resp.status_code
        plan["started"] = resp.status_code < 400
        plan["egress_reply"] = (resp.text or "")[:240]
        if resp.status_code >= 400:
            plan["reason"] = "egress_worker_or_api"
    except Exception as exc:
        plan["started"] = False
        plan["reason"] = str(exc)[:120]
    return plan


def join_token(session_id: str, role: str, identity: str = "") -> Dict[str, Any]:
    out = join_token_stub(session_id, role)
    key = os.getenv("LIVEKIT_API_KEY", "")
    secret = os.getenv("LIVEKIT_API_SECRET", "")
    url = os.getenv("LIVEKIT_URL", "")
    token = ""
    if key and secret:
        token = mint_livekit_jwt(
            api_key=key,
            api_secret=secret,
            room=f"studio-{session_id}",
            identity=identity or role,
            role=role,
        )
        out["token"] = token
        out["jwt"] = True
        out["url"] = url
        out["room"] = f"studio-{session_id}"
    else:
        out["jwt"] = False
        out["url"] = url
    out["room_url"] = room_embed_url(url, token, role)
    return out
