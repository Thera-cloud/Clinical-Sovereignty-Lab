"""Canonical client covenant version for signup and chat/booking gates.

Bridge `REQUIRED_CONSENT_VERSION` must stay in lockstep with this value.
Paid Stripe finalize previously defaulted to v13.0_2026, which blocked
`nate_query` / `client_book_session` until ReConsentScreen.
"""
from __future__ import annotations

REQUIRED_CONSENT_VERSION = "v13.1_2026"

# Stale defaults still present on older Stripe prepare clients.
_LEGACY_SIGNUP_CONSENT = frozenset({"v13.0_2026"})


def stamp_signup_consent(raw: str | None) -> str:
    """Stamp new accounts at the live covenant; upgrade omitted/stale Stripe defaults."""
    v = (raw or "").strip()
    if not v or v in _LEGACY_SIGNUP_CONSENT:
        return REQUIRED_CONSENT_VERSION
    return v
