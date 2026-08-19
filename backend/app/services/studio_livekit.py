"""S4 LiveKit + INV-2 guest audio-only. JWT if env set. No ORANGE install. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional

from app.services.studio_invariants import guest_video_allowed


def health() -> Dict[str, Any]:
    url = os.getenv("LIVEKIT_URL", "")
    return {
        "status": "ok" if url else "pending",
        "url_configured": bool(url),
        "jwt_configured": bool(os.getenv("LIVEKIT_API_KEY") and os.getenv("LIVEKIT_API_SECRET")),
        "allow_video_guest": False,
        "node": "orange",
        "installed": False,
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


def join_token(session_id: str, role: str, identity: str = "") -> Dict[str, Any]:
    out = join_token_stub(session_id, role)
    key = os.getenv("LIVEKIT_API_KEY", "")
    secret = os.getenv("LIVEKIT_API_SECRET", "")
    url = os.getenv("LIVEKIT_URL", "")
    if key and secret:
        out["token"] = mint_livekit_jwt(
            api_key=key,
            api_secret=secret,
            room=f"studio-{session_id}",
            identity=identity or role,
            role=role,
        )
        out["jwt"] = True
        out["url"] = url
        out["room"] = f"studio-{session_id}"
    else:
        out["jwt"] = False
        out["url"] = url
    return out
