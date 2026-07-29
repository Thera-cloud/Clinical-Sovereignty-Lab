"""HMAC-signed read-only content preview URLs for CEO emails (72h TTL).

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional, Tuple
from urllib.parse import urlencode

DEFAULT_TTL_S = 72 * 3600
API_BASE = os.getenv(
    "PUBLIC_API_BASE", "https://api.sovereignsanctuary.net"
).rstrip("/")


def _secret() -> bytes:
    raw = (
        os.getenv("GROWTH_PREVIEW_SECRET")
        or os.getenv("JWT_SECRET")
        or os.getenv("SECRET_KEY")
        or "growth-preview-dev-only"
    )
    return raw.encode("utf-8")


def sign_preview(content_id: int, *, exp: Optional[int] = None) -> str:
    exp = int(exp or (time.time() + DEFAULT_TTL_S))
    msg = f"{int(content_id)}:{exp}".encode("utf-8")
    sig = hmac.new(_secret(), msg, hashlib.sha256).hexdigest()[:32]
    return sig


def verify_preview(content_id: int, exp: int, sig: str) -> bool:
    try:
        exp_i = int(exp)
        cid = int(content_id)
    except (TypeError, ValueError):
        return False
    if exp_i < int(time.time()):
        return False
    expected = sign_preview(cid, exp=exp_i)
    return hmac.compare_digest(expected, (sig or "").strip().lower())


def build_preview_url(content_id: int, *, ttl_s: int = DEFAULT_TTL_S) -> str:
    exp = int(time.time() + ttl_s)
    sig = sign_preview(content_id, exp=exp)
    q = urlencode({"exp": exp, "sig": sig})
    return f"{API_BASE}/api/marketing/content/{int(content_id)}/preview?{q}"


def build_dashboard_deep_link(content_id: int) -> str:
    base = os.getenv(
        "COMMAND_BASE_URL", "https://command.sovereignsanctuary.net"
    ).rstrip("/")
    return f"{base}/marketing_engine.html#content={int(content_id)}"


def parse_and_verify(content_id: int, exp: str, sig: str) -> Tuple[bool, str]:
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False, "invalid exp"
    if not verify_preview(content_id, exp_i, sig):
        return False, "invalid or expired signature"
    return True, "ok"
