"""
Sovereign IDE session gate — HMAC-signed short-lived tokens after YubiKey verify.

Tokens are required by the ide.* Cloudflare Worker / Mac auth proxy.
Mint only when webauthn_last_verified is fresh (default 180s).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, Optional, Tuple

COOKIE_NAME = "ss_ide_session"
PURPOSE = "ide"
DEFAULT_TTL_SECONDS = 4 * 3600
DEFAULT_FRESH_YK_SECONDS = 180


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _secret() -> bytes:
    raw = (
        os.environ.get("IDE_GATE_SECRET")
        or os.environ.get("JWT_SECRET")
        or ""
    ).strip()
    if not raw:
        raise RuntimeError("IDE_GATE_SECRET or JWT_SECRET required for IDE session gate")
    return hashlib.sha256(f"ide-gate-v1:{raw}".encode("utf-8")).digest()


def fresh_yubikey_window_seconds() -> int:
    try:
        return max(30, int(os.environ.get("IDE_YK_FRESH_SECONDS", DEFAULT_FRESH_YK_SECONDS)))
    except ValueError:
        return DEFAULT_FRESH_YK_SECONDS


def session_ttl_seconds() -> int:
    try:
        return max(300, int(os.environ.get("IDE_SESSION_TTL_SECONDS", DEFAULT_TTL_SECONDS)))
    except ValueError:
        return DEFAULT_TTL_SECONDS


def mint_ide_session(
    *,
    hardware_id: str,
    username: str = "",
    active_key: str = "",
    ttl_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """Return token dict: token, expires_at, cookie_name, max_age."""
    ttl = ttl_seconds if ttl_seconds is not None else session_ttl_seconds()
    now = int(time.time())
    exp = now + ttl
    payload = {
        "sub": hardware_id,
        "usr": username or "",
        "key": (active_key or "")[:64],
        "pur": PURPOSE,
        "iat": now,
        "exp": exp,
        "jti": secrets.token_hex(16),
    }
    body = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _b64url(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    token = f"{body}.{sig}"
    return {
        "token": token,
        "expires_at": exp,
        "cookie_name": COOKIE_NAME,
        "max_age": ttl,
        "jti": payload["jti"],
    }


def verify_ide_session(token: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Verify HMAC token.
    Returns (ok, payload_or_none, reason).
    """
    if not token or "." not in token:
        return False, None, "missing_or_malformed"
    try:
        body, sig = token.rsplit(".", 1)
        expected = _b64url(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, sig):
            return False, None, "bad_signature"
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
        if payload.get("pur") != PURPOSE:
            return False, None, "wrong_purpose"
        exp = int(payload.get("exp", 0))
        if exp < int(time.time()):
            return False, None, "expired"
        if not payload.get("sub"):
            return False, None, "no_subject"
        return True, payload, "ok"
    except Exception as e:
        return False, None, f"verify_error:{type(e).__name__}"


def yubikey_verified_recently(verified_at_iso: Optional[str], window_s: Optional[int] = None) -> bool:
    """True if ISO timestamp is within the fresh window."""
    if not verified_at_iso:
        return False
    window = window_s if window_s is not None else fresh_yubikey_window_seconds()
    try:
        from datetime import datetime, timezone

        ts = datetime.fromisoformat(str(verified_at_iso).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return 0 <= age <= window
    except Exception:
        return False


def cookie_header_value(token: str, max_age: int) -> str:
    """Set-Cookie value for Domain=.sovereignsanctuary.net (cross-subdomain)."""
    return (
        f"{COOKIE_NAME}={token}; Domain=.sovereignsanctuary.net; Path=/; "
        f"Max-Age={max_age}; Secure; HttpOnly; SameSite=None"
    )
