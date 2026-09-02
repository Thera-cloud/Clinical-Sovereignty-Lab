#!/usr/bin/env python3
"""STUDIO caller ingress smoke — Twilio PSTN + Zoom Phone SIP.

Offline (default): imports the same handlers the public routes use.
Live: set STUDIO_SMOKE_BASE=https://api.sovereignsanctuary.net
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.studio_screener_service import handle_screener, inbound_twiml
from app.services.studio_sip import sip_health, sip_join_allowed, zoom_phone_health


def _fail(msg: str) -> int:
    print(f"FAIL {msg}")
    return 1


def smoke_offline() -> int:
    xml = inbound_twiml()
    if "/api/studio/voice/screener" not in xml or "screening" not in xml.lower():
        return _fail("twilio inbound does not start screener")
    disc = handle_screener(step="disclosure")["twiml"]
    if "Press 1" not in disc:
        return _fail("screener disclosure missing")
    if sip_join_allowed("")["code"] != 403:
        return _fail("sip join must 403 without token")
    zoom = zoom_phone_health()
    if zoom["path"] != "sip" or zoom["allow_video"] is not False:
        return _fail("zoom phone must share audio-only sip gate")
    sip = sip_health()
    print(
        json.dumps(
            {
                "ok": True,
                "twilio": "inbound_screener",
                "zoom_phone": zoom,
                "sip_installed": sip["installed"],
            }
        )
    )
    return 0


def _req(base: str, method: str, path: str, data: bytes | None = None) -> tuple[int, str]:
    req = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.getcode(), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def smoke_live(base: str) -> int:
    code, body = _req(base, "POST", "/api/studio/voice/inbound", b"From=+15551212000&To=+15617833006")
    if code != 200 or "/api/studio/voice/screener" not in body:
        return _fail(f"twilio inbound {code}: {body[:200]}")
    code, body = _req(base, "GET", "/api/studio/voice/sip-health")
    if code != 200 or '"sip"' not in body:
        return _fail(f"sip-health {code}: {body[:200]}")
    code, body = _req(base, "GET", "/api/studio/voice/zoom-health")
    if code != 200 or "zoom_phone" not in body:
        return _fail(f"zoom-health {code}: {body[:200]}")
    code, body = _req(base, "POST", "/api/studio/voice/sip-join")
    if code != 403:
        return _fail(f"sip-join expected 403, got {code}: {body[:200]}")
    print(json.dumps({"ok": True, "base": base, "twilio": "inbound_200", "zoom": "sip_403_without_token"}))
    return 0


def main() -> int:
    base = (os.getenv("STUDIO_SMOKE_BASE") or "").strip()
    if base:
        return smoke_live(base)
    return smoke_offline()


if __name__ == "__main__":
    raise SystemExit(main())
