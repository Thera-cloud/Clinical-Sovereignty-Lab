"""Outreach sender-domain hard-fail.

Product domain sovereignsanctuary.net (and subdomains) must never be used
for cold Instantly sequences.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import os
from typing import List, Tuple

_BLOCKED_SUFFIXES = (
    "sovereignsanctuary.net",
    "littlenate.ai",
)


def parse_outreach_sender_domains() -> List[str]:
    raw = os.getenv("OUTREACH_SENDER_DOMAINS", "").strip()
    if not raw:
        return []
    return [d.strip().lower().lstrip("@") for d in raw.split(",") if d.strip()]


def domain_is_blocked(domain: str) -> bool:
    d = (domain or "").strip().lower().lstrip("@")
    if not d:
        return False
    for blocked in _BLOCKED_SUFFIXES:
        if d == blocked or d.endswith("." + blocked):
            return True
    return False


def validate_outreach_sender_domains(
    *, require_when_outreach_enabled: bool = True
) -> Tuple[bool, str]:
    """Return (ok, message). Fail hard when outreach flag on + bad/missing domains."""
    from app.services.growth import outreach_engine_enabled

    domains = parse_outreach_sender_domains()
    if not outreach_engine_enabled():
        return True, "outreach disabled — sender check skipped"
    if require_when_outreach_enabled and not domains:
        return False, "ENABLE_OUTREACH_ENGINE=true but OUTREACH_SENDER_DOMAINS is empty"
    bad = [d for d in domains if domain_is_blocked(d)]
    if bad:
        return False, f"blocked product domains in OUTREACH_SENDER_DOMAINS: {bad}"
    return True, f"ok ({len(domains)} sender domain(s))"


def startup_hard_fail_if_needed() -> None:
    """Raise RuntimeError when outreach is enabled with illegal sender config."""
    ok, msg = validate_outreach_sender_domains()
    if not ok:
        raise RuntimeError(f"OUTREACH_SENDER_GUARD: {msg}")
