"""S4 LiveKit + INV-2 guest audio-only. JWT if env set. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from app.services.studio_invariants import guest_video_allowed

DELAY_S = 45

_ROOM_FILE = Path(__file__).with_name("studio_livekit_room.html")
ROOM_HTML = _ROOM_FILE.read_text(encoding="utf-8") if _ROOM_FILE.is_file() else ""


def room_origin() -> str:
    return os.getenv("STUDIO_ROOM_ORIGIN", "https://coach.sovereignsanctuary.net").rstrip("/")


def room_embed_url(lk_url: str, token: str, role: str, session_id: str = "") -> str:
    api = os.getenv("STUDIO_API_ORIGIN", "https://api.sovereignsanctuary.net").rstrip("/")
    q = urlencode(
        {
            "url": lk_url or "",
            "token": token or "",
            "role": role or "host",
            "session": session_id or "",
            "api": api,
        }
    )
    return f"{room_origin()}/studio_nate_room.html?v=20260901e#{q}"


def verify_livekit_jwt(token: str) -> Dict[str, Any]:
    secret = os.getenv("LIVEKIT_API_SECRET", "")
    key = os.getenv("LIVEKIT_API_KEY", "")
    parts = (token or "").split(".")
    if len(parts) != 3 or not secret:
        return {"ok": False, "reason": "bad_token"}
    h, p, s = parts
    expect = _b64(hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expect, s):
        return {"ok": False, "reason": "bad_sig"}

    def _pad(raw: str) -> str:
        return raw + "=" * (-len(raw) % 4)

    try:
        payload = json.loads(base64.urlsafe_b64decode(_pad(p)))
    except Exception:
        return {"ok": False, "reason": "bad_payload"}
    if int(payload.get("exp") or 0) < int(time.time()):
        return {"ok": False, "reason": "expired"}
    if key and payload.get("iss") != key:
        return {"ok": False, "reason": "iss"}
    room = str((payload.get("video") or {}).get("room") or "")
    sid = room[7:] if room.startswith("studio-") else ""
    return {
        "ok": True,
        "room": room,
        "session_id": sid,
        "identity": str(payload.get("sub") or ""),
    }


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
    ttl_s: int = 28800,
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
    out["room_url"] = room_embed_url(url, token, role, session_id)
    return out
