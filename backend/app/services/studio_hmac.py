"""HMAC-SHA256 verify for Studio hooks. No FastAPI imports."""

from __future__ import annotations

import hashlib
import hmac


def verify_hmac(secret: bytes, body: bytes, header: str) -> bool:
    got = (header or "").strip().lower()
    if got.startswith("sha256="):
        got = got[7:]
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if len(got) != len(expected):
        return False
    return hmac.compare_digest(expected, got)
