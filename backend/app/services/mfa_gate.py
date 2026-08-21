"""MFA freshness gate for PHI reads (Slice 6c of Bee HIV+ privacy plan).

HIPAA Security Rule §164.312(a)(2)(i) requires unique user identification;
§164.308(a)(4) requires access controls proportional to risk. For the most
sensitive PHI (trauma history, safe-silence state, part registry, trigger
dates, polyvictimization layers) we add a step-up MFA re-verification gate
on top of the existing session token so a stolen bearer alone cannot read
PHI without a fresh authenticator touch.

Contract
--------
1. ``is_enabled()`` reads ``ENABLE_PHI_MFA_GATE``. When False the gate is a
   no-op — zero behavior change for callers.
2. ``check_mfa_recent(profile_data, ...)`` returns ``(ok, reason)`` without
   raising. Callers who want soft handling (dashboards, low-risk reads)
   use this.
3. ``enforce_mfa_recent(db_pool, principal, ...)`` looks up the caller's
   ``profile_data``, calls ``check_mfa_recent``, and raises
   ``HTTPException(401, {"code": "MFA_REVERIFY_REQUIRED", ...})`` on
   staleness. Audit-token principals (``is_audit=True``) always pass.

Timestamp sources (checked in priority order)
---------------------------------------------
1. ``profile_data.mfa_last_verified_at`` — new canonical key; any future
   MFA method (TOTP verify, SMS verify, WebAuthn) should write this.
2. ``profile_data.webauthn_last_verified`` — already populated today by
   ``/api/admin/webauthn/auth-verify``. This means admin YubiKey users
   pass the gate immediately when the flag is enabled; other roles need
   MFA infrastructure before the flag flips on for them.

Freshness window
----------------
Default 1800 seconds (30 minutes). Override via ``MFA_GATE_WINDOW_SECONDS``.
Callers may override per-endpoint by passing ``max_age_seconds``.

Design invariants
-----------------
- Fail-closed when enabled: unknown timestamp / parse error / no MFA
  fields ⇒ ``ok=False``. HIPAA-appropriate default.
- Audit token bypass: trust auditors don't carry MFA state. This is
  identical to the ``require_clinician_for_user`` audit bypass and is
  the ONLY bypass path.
- No writes here. The gate reads state; writers live in
  ``admin.py`` (webauthn auth-verify) and future MFA endpoints.
- Zero DB migrations. Uses the existing ``users.profile_data`` JSONB
  columns.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_ENV_FLAG = "ENABLE_PHI_MFA_GATE"
_ENV_WINDOW = "MFA_GATE_WINDOW_SECONDS"
_DEFAULT_WINDOW_SECONDS = 1800  # 30 minutes

# Priority order: newer canonical key wins if both are present.
_MFA_TIMESTAMP_KEYS: Tuple[str, ...] = (
    "mfa_last_verified_at",
    "webauthn_last_verified",
)


def is_enabled() -> bool:
    """Return True iff ``ENABLE_PHI_MFA_GATE`` is truthy in the environment.

    Deliberately re-reads env each call so tests can toggle without a
    process restart. Cost is one dict lookup.
    """
    return (os.getenv(_ENV_FLAG) or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def default_window_seconds() -> int:
    """Freshness window in seconds. Overridable via env; clamped to sane range."""
    raw = (os.getenv(_ENV_WINDOW) or "").strip()
    if not raw:
        return _DEFAULT_WINDOW_SECONDS
    try:
        n = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "mfa_gate: MFA_GATE_WINDOW_SECONDS=%r not an int, using default %ds",
            raw,
            _DEFAULT_WINDOW_SECONDS,
        )
        return _DEFAULT_WINDOW_SECONDS
    # Clamp: 60 seconds min (avoid pathological configs), 24h max.
    return max(60, min(n, 86_400))


def _parse_iso(ts: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string; return None on any failure."""
    if not ts:
        return None
    s = str(ts).strip()
    if not s:
        return None
    try:
        # Accept trailing 'Z' shorthand.
        parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def check_mfa_recent(
    profile_data: Optional[Dict[str, Any]],
    max_age_seconds: Optional[int] = None,
) -> Tuple[bool, str]:
    """Return ``(ok, reason)`` for the given profile.

    ``ok=True`` iff a supported MFA timestamp key is present and the
    parsed timestamp is within ``max_age_seconds`` of now (UTC).

    ``reason`` is a short machine-readable slug for logging/telemetry:
      - ``"ok"`` — verification is fresh.
      - ``"no_profile_data"`` — caller passed None/empty.
      - ``"no_mfa_field"`` — profile has no MFA timestamp keys.
      - ``"unparseable_timestamp:<key>"`` — value present but malformed.
      - ``"stale:<age_seconds>s"`` — timestamp too old.
      - ``"future_timestamp"`` — timestamp is in the future (clock skew
        or tampering); treated as stale.
    """
    if not profile_data:
        return False, "no_profile_data"

    window = max_age_seconds if max_age_seconds is not None else default_window_seconds()

    latest_key: Optional[str] = None
    latest_ts: Optional[datetime] = None
    for key in _MFA_TIMESTAMP_KEYS:
        raw = profile_data.get(key)
        if raw is None:
            continue
        parsed = _parse_iso(raw)
        if parsed is None:
            # Note the malformed key but keep scanning — a later key may work.
            if latest_ts is None:
                latest_key = key
            continue
        if latest_ts is None or parsed > latest_ts:
            latest_ts = parsed
            latest_key = key

    if latest_ts is None:
        return False, (
            "no_mfa_field"
            if latest_key is None
            else f"unparseable_timestamp:{latest_key}"
        )

    now = datetime.now(timezone.utc)
    age = (now - latest_ts).total_seconds()
    if age < 0:
        # Clock skew or forged timestamp.
        return False, "future_timestamp"
    if age > window:
        return False, f"stale:{int(age)}s"
    return True, "ok"


async def _fetch_principal_profile_data(
    db_pool: Any, principal: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Load the caller's ``profile_data`` JSONB. Returns None on any failure.

    Prefers ``hardware_id`` (indexed unique key on ``users``) and falls
    back to ``username`` if hardware_id is missing.
    """
    if db_pool is None:
        return None
    hw = (principal.get("hardware_id") or "").strip()
    uname = (principal.get("username") or "").strip()
    if not hw and not uname:
        return None
    try:
        async with db_pool.acquire() as conn:
            if hw:
                row = await conn.fetchrow(
                    "SELECT profile_data FROM users WHERE hardware_id = $1",
                    hw,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT profile_data FROM users WHERE username = $1",
                    uname,
                )
    except Exception as exc:
        logger.warning("mfa_gate: profile_data fetch failed: %s", exc)
        return None
    if not row or row["profile_data"] is None:
        return None
    pd = row["profile_data"]
    if isinstance(pd, dict):
        return pd
    try:
        return json.loads(pd)
    except (TypeError, ValueError):
        return None


async def enforce_mfa_recent(
    db_pool: Any,
    principal: Dict[str, Any],
    max_age_seconds: Optional[int] = None,
) -> None:
    """Raise ``HTTPException(401, MFA_REVERIFY_REQUIRED)`` if MFA is stale.

    No-op paths (return without raising):
      1. Flag ``ENABLE_PHI_MFA_GATE`` is off.
      2. Principal carries ``is_audit=True`` (trust-auditor probe).

    Fail-closed paths (raise 401):
      3. Flag is on and profile_data lookup fails.
      4. Flag is on and no supported MFA timestamp is present or fresh.

    The 401 payload includes ``reason`` for observability and a
    ``retry_after_seconds`` hint so the client knows how long its next
    verification will remain valid.
    """
    if not is_enabled():
        return
    if principal.get("is_audit"):
        return

    # Import locally to keep this module import-safe outside FastAPI.
    from fastapi import HTTPException  # type: ignore

    window = max_age_seconds if max_age_seconds is not None else default_window_seconds()

    profile_data = await _fetch_principal_profile_data(db_pool, principal)
    ok, reason = check_mfa_recent(profile_data, max_age_seconds=window)
    if ok:
        return

    who = principal.get("username") or principal.get("hardware_id") or "?"
    logger.info(
        "mfa_gate: blocking %s (role=%s) reason=%s window=%ds",
        who,
        principal.get("role"),
        reason,
        window,
    )
    raise HTTPException(
        status_code=401,
        detail={
            "code": "MFA_REVERIFY_REQUIRED",
            "reason": reason,
            "retry_after_seconds": window,
        },
    )


__all__ = [
    "check_mfa_recent",
    "default_window_seconds",
    "enforce_mfa_recent",
    "is_enabled",
]
