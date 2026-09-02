"""INV-4 SIP ingress — token required, guests audio-only. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import os
from typing import Any, Dict


def sip_health() -> Dict[str, Any]:
    uri = os.getenv("LIVEKIT_SIP_URI", "")
    return {
        "status": "ok",
        "sip": "s4",
        "allow_video": False,
        "join_requires_token": True,
        "ingress": uri or "pending",
        "installed": bool(uri),
    }


def zoom_phone_health() -> Dict[str, Any]:
    """Google Workspace / Zoom Phone uses the same SIP gate as studio guests."""
    h = sip_health()
    return {
        "status": h["status"],
        "carrier": "zoom_phone",
        "path": "sip",
        "allow_video": False,
        "join_requires_token": True,
        "ingress": h["ingress"],
        "installed": h["installed"],
    }


def sip_join_allowed(token: str) -> Dict[str, Any]:
    if not (token or "").strip():
        return {"ok": False, "reason": "screener token required", "code": 403}
    return {"ok": True, "allow_video": False}


def sip_ingress_twiml(token: str) -> str:
    if not (token or "").strip():
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response><Reject reason=\"rejected\"/></Response>"
        )
    uri = os.getenv("LIVEKIT_SIP_URI", "")
    if not uri:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response><Say>Studio SIP ingress is not installed. Stay on the phone line.</Say>"
            "<Hangup/></Response>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Say>Connecting audio only.</Say>"
        f"<Dial><Sip>{uri}</Sip></Dial></Response>"
    )
