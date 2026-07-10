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


def trial_free_upgrade_session_key(session_id: str) -> str:
    """Phase 3.5: TRIAL_FREE -> card-based TRIAL upgrade Stripe setup-mode session."""
    return f"{_prefix()}:trial_free_upgrade:{session_id}"


# --- Public Trial Funnel (Phase 1-4) abuse-cap + turn-accounting keys ---
# Namespaced separately from the above (pre-signup) keys since these gate an
# unauthenticated WebSocket surface and must fail closed on Redis outage.

def public_trial_ip_daily_key(ip_hash: str) -> str:
    return f"{_prefix()}:public_trial:ip_daily:{ip_hash}"


def public_trial_global_daily_key() -> str:
    return f"{_prefix()}:public_trial:global_daily"


def public_trial_fp_hourly_key(fp_hash: str) -> str:
    return f"{_prefix()}:public_trial:fp_hourly:{fp_hash}"


def public_trial_fp_inflight_key(fp_hash: str) -> str:
    return f"{_prefix()}:public_trial:fp_inflight:{fp_hash}"


def public_trial_email_ip_daily_key(ip_hash: str) -> str:
    return f"{_prefix()}:public_trial:email_ip_daily:{ip_hash}"


def registration_ip_daily_key(ip_hash: str) -> str:
    """Phase 3 security-registration-abuse: per-IP TRIAL_FREE registration cap
    (5/day), separate from the trial-turn caps above."""
    return f"{_prefix()}:public_trial:reg_ip_daily:{ip_hash}"


# --- Bot-abuse hardening (2026-07): Turnstile device-verification sliding
# window + a per-HOUR global cap alongside the existing per-day one. ---

def public_trial_verified_key(device_uuid_hash: str) -> str:
    """Sliding-window flag set once a device passes Turnstile at
    public_trial_start. Checked (and its TTL refreshed) on every subsequent
    public_trial_chat turn so a long, legitimate conversation is never
    re-challenged mid-session, while a device that never solved a challenge
    can never reach inference via public_trial_chat alone."""
    return f"{_prefix()}:public_trial:verified:{device_uuid_hash}"


def public_trial_global_hourly_key() -> str:
    """Per-hour companion to public_trial_global_daily_key — caps how much of
    the shared daily inference budget a single hour (i.e. a burst) can
    consume, so a scripted flood can't exhaust the whole day's budget in
    minutes."""
    return f"{_prefix()}:public_trial:global_hourly"


def public_trial_alert_dedup_key(cap_kind: str) -> str:
    """SETNX dedup guard so a sustained flood of rejected requests against an
    exhausted global cap triggers at most one admin alert per window, not one
    per rejected request."""
    return f"{_prefix()}:public_trial:alert_dedup:{cap_kind}"
