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
#stage{display:flex;gap:8px;padding:12px;flex-wrap:wrap}
video{width:320px;height:180px;background:#111;border-radius:8px}
#env{width:160px;height:160px;background:#111;border-radius:8px}
</style>
</head>
<body>
<div id="bar">SOVEREIGN STUDIO · AI co-host and knowledge companion</div>
<div id="status">Connecting…</div>
<div id="stage"><canvas id="env" width="160" height="160"></canvas></div>
<script src="https://cdn.jsdelivr.net/npm/livekit-client@2.15.4/dist/livekit-client.umd.min.js"></script>
<script>
(function(){
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
  drawEnv(0.35);
  var p = params();
  var status = document.getElementById('status');
  var guest = p.role === 'guest';
  if (!p.url || !p.token){
    status.textContent = 'LiveKit pending — set LIVEKIT_URL + JWT, then Start session.';
    return;
  }
  var LK = window.LivekitClient;
  var room = new LK.Room({adaptiveStream:true, dynacast:true});
  room.on(LK.RoomEvent.TrackSubscribed, function(track){
    var el = track.attach();
    el.autoplay = true;
    document.getElementById('stage').appendChild(el);
  });
  room.connect(p.url, p.token).then(function(){
    return room.localParticipant.setMicrophoneEnabled(true);
  }).then(function(){
    if (guest) return room.localParticipant.setCameraEnabled(false);
    return room.localParticipant.setCameraEnabled(true);
  }).then(function(){
    status.textContent = guest ? 'Guest audio-only (INV-2).' : 'Host connected.';
  }).catch(function(e){
    status.textContent = 'Connect failed: ' + e;
  });
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


def health() -> Dict[str, Any]:
    url = os.getenv("LIVEKIT_URL", "")
    internal = os.getenv("LIVEKIT_INTERNAL_URL", "")
    return {
        "status": "ok" if url else "pending",
        "url_configured": bool(url),
        "jwt_configured": bool(os.getenv("LIVEKIT_API_KEY") and os.getenv("LIVEKIT_API_SECRET")),
        "allow_video_guest": False,
        "node": "orange",
        "installed": bool(internal),
        "internal_configured": bool(internal),
        "room_origin": room_origin(),
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
    video = {
        "roomJoin": True,
        "room": room,
        "canPublish": True,
        "canSubscribe": True,
        "canPublishData": True,
        "canPublishSources": ["microphone"] if not can_video else ["microphone", "camera"],
    }
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
        "installed": False,
    }


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
