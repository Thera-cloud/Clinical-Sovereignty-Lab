"""S4 LiveKit + INV-2 guest audio-only. Media stays on ORANGE. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from app.services.studio_invariants import guest_video_allowed


def health() -> Dict[str, Any]:
    url = os.getenv("LIVEKIT_URL", "")
    return {
        "status": "ok" if url else "pending",
        "url_configured": bool(url),
        "allow_video_guest": False,
        "node": "orange",
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
