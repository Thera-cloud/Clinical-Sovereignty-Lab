"""Shared Redis keys for trial registration billing (setup + WebSocket register)."""
from __future__ import annotations

import hashlib
import os


def _prefix() -> str:
    p = os.getenv("REDIS_KEY_PREFIX", "nate")
    e = os.getenv("ENVIRONMENT", "production")
    return f"{p}:{e}"


def trial_signup_session_key(session_id: str) -> str:
    return f"{_prefix()}:trial_signup:{session_id}"


def trial_contact_key(kind: str, value: str) -> str:
    h = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{_prefix()}:trial_contact:{kind}:{h}"
