"""Unit tests for the MFA freshness gate (Slice 6c).

Covers:
- Feature flag behavior (default off, env override, fail-closed on enable).
- Timestamp parsing edge cases (Z suffix, tz-naive, malformed, future).
- Priority ordering across multiple MFA keys.
- Window override and env-driven window.
- ``enforce_mfa_recent`` bypasses for audit and disabled flag.
- ``enforce_mfa_recent`` raises 401 with correct payload when stale.
- ``enforce_mfa_recent`` fails closed when profile_data lookup fails.

No network, no Postgres, no Redis. All DB access is stubbed via a tiny
async context-manager fake.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pytest


# --------------------------------------------------------------------------- #
# Test helpers                                                                #
# --------------------------------------------------------------------------- #


class _FakeConn:
    """Minimal asyncpg-shaped connection returning a preset row for fetchrow()."""

    def __init__(self, row: Optional[Dict[str, Any]]):
        self._row = row

    async def fetchrow(self, _sql: str, *_args: Any) -> Optional[Dict[str, Any]]:
        return self._row


class _FakePool:
    """Minimal asyncpg-shaped pool. ``acquire()`` returns an async CM."""

    def __init__(self, row: Optional[Dict[str, Any]] = None, raise_on_acquire: bool = False):
        self._row = row
        self._raise = raise_on_acquire

    def acquire(self):
        if self._raise:
            raise RuntimeError("simulated pool failure")

        @asynccontextmanager
        async def _cm():
            yield _FakeConn(self._row)

        return _cm()


def _now_iso(offset_seconds: float = 0.0) -> str:
    """UTC ISO-8601 timestamp with optional offset from now."""
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()


def _reload_gate(monkeypatch: pytest.MonkeyPatch, **env: str) -> Any:
    """Set env then import (or re-import) mfa_gate so it sees the values.

    Also reloads ``app.services.cohort`` so cohort env overrides
    (e.g. ``MFA_GATE_STRICT_WINDOW_SECONDS``) are picked up on the same
    call; ``mfa_gate`` imports helpers from cohort at module import time.
    """
    import importlib
    import sys

    for k, v in env.items():
        monkeypatch.setenv(k, v)
    if "app.services.cohort" in sys.modules:
        importlib.reload(sys.modules["app.services.cohort"])
    if "app.services.mfa_gate" in sys.modules:
        return importlib.reload(sys.modules["app.services.mfa_gate"])
    import app.services.mfa_gate as gate  # type: ignore
    return gate


# --------------------------------------------------------------------------- #
# is_enabled()                                                                #
# --------------------------------------------------------------------------- #


def test_is_enabled_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_PHI_MFA_GATE", raising=False)
    gate = _reload_gate(monkeypatch)
    assert gate.is_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
def test_is_enabled_truthy_values(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE=val)
    assert gate.is_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", "", "   "])
def test_is_enabled_falsy_values(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE=val)
    assert gate.is_enabled() is False


# --------------------------------------------------------------------------- #
# default_window_seconds()                                                    #
# --------------------------------------------------------------------------- #


def test_default_window_is_30_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MFA_GATE_WINDOW_SECONDS", raising=False)
    gate = _reload_gate(monkeypatch)
    assert gate.default_window_seconds() == 1800


def test_default_window_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch, MFA_GATE_WINDOW_SECONDS="600")
    assert gate.default_window_seconds() == 600


def test_default_window_env_clamped_low(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch, MFA_GATE_WINDOW_SECONDS="1")
    # Clamp to 60s min.
    assert gate.default_window_seconds() == 60


def test_default_window_env_clamped_high(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch, MFA_GATE_WINDOW_SECONDS="9999999")
    # Clamp to 24h max.
    assert gate.default_window_seconds() == 86_400


def test_default_window_env_invalid_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch, MFA_GATE_WINDOW_SECONDS="abc")
    assert gate.default_window_seconds() == 1800


# --------------------------------------------------------------------------- #
# check_mfa_recent()                                                          #
# --------------------------------------------------------------------------- #


def test_check_returns_ok_when_fresh_webauthn(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch)
    pd = {"webauthn_last_verified": _now_iso(-30)}
    ok, reason = gate.check_mfa_recent(pd, max_age_seconds=1800)
    assert ok is True
    assert reason == "ok"


def test_check_returns_ok_with_canonical_key(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch)
    pd = {"mfa_last_verified_at": _now_iso(-10)}
    ok, reason = gate.check_mfa_recent(pd, max_age_seconds=1800)
    assert ok is True
    assert reason == "ok"


def test_check_prefers_newest_across_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch)
    # webauthn is stale, canonical is fresh — should pass on canonical.
    pd = {
        "webauthn_last_verified": _now_iso(-10_000),
        "mfa_last_verified_at": _now_iso(-30),
    }
    ok, reason = gate.check_mfa_recent(pd, max_age_seconds=1800)
    assert ok is True
    assert reason == "ok"


def test_check_stale_returns_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch)
    pd = {"webauthn_last_verified": _now_iso(-3600)}
    ok, reason = gate.check_mfa_recent(pd, max_age_seconds=1800)
    assert ok is False
    assert reason.startswith("stale:")


def test_check_no_profile_data(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch)
    ok, reason = gate.check_mfa_recent(None)
    assert ok is False
    assert reason == "no_profile_data"


def test_check_no_mfa_field(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch)
    ok, reason = gate.check_mfa_recent({"unrelated_key": "value"})
    assert ok is False
    assert reason == "no_mfa_field"


def test_check_unparseable_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch)
    pd = {"webauthn_last_verified": "not-a-date"}
    ok, reason = gate.check_mfa_recent(pd)
    assert ok is False
    assert reason.startswith("unparseable_timestamp:")


def test_check_future_timestamp_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch)
    pd = {"webauthn_last_verified": _now_iso(+3600)}
    ok, reason = gate.check_mfa_recent(pd)
    assert ok is False
    assert reason == "future_timestamp"


def test_check_naive_timestamp_treated_as_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch)
    # Timestamp without tz — parser should coerce to UTC.
    naive = datetime.utcnow().replace(microsecond=0).isoformat()
    pd = {"webauthn_last_verified": naive}
    ok, reason = gate.check_mfa_recent(pd, max_age_seconds=1800)
    assert ok is True
    assert reason == "ok"


def test_check_z_suffix_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch)
    # Common Cloudflare / JS-style trailing 'Z'.
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    pd = {"webauthn_last_verified": ts}
    ok, reason = gate.check_mfa_recent(pd, max_age_seconds=1800)
    assert ok is True
    assert reason == "ok"


# --------------------------------------------------------------------------- #
# enforce_mfa_recent() — bypasses                                             #
# --------------------------------------------------------------------------- #


def test_enforce_noop_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_PHI_MFA_GATE", raising=False)
    gate = _reload_gate(monkeypatch)
    # No pool, no principal profile — must not raise because flag is off.
    asyncio.run(gate.enforce_mfa_recent(None, {"username": "alice", "role": "COACH"}))


def test_enforce_bypasses_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE="1")
    asyncio.run(
        gate.enforce_mfa_recent(
            None,
            {"username": "audit", "role": "ADMIN", "is_audit": True},
        )
    )


# --------------------------------------------------------------------------- #
# enforce_mfa_recent() — active enforcement                                   #
# --------------------------------------------------------------------------- #


def test_enforce_passes_with_fresh_webauthn(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE="1")
    pool = _FakePool(row={"profile_data": {"webauthn_last_verified": _now_iso(-60)}})
    principal = {"username": "admin1", "hardware_id": "HW_ADMIN1", "role": "ADMIN"}
    asyncio.run(gate.enforce_mfa_recent(pool, principal))


def test_enforce_raises_401_when_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE="1")
    pool = _FakePool(row={"profile_data": {"webauthn_last_verified": _now_iso(-10_000)}})
    principal = {"username": "admin1", "hardware_id": "HW_ADMIN1", "role": "ADMIN"}

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(gate.enforce_mfa_recent(pool, principal))
    assert excinfo.value.status_code == 401
    detail = excinfo.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "MFA_REVERIFY_REQUIRED"
    assert detail["reason"].startswith("stale:")
    assert isinstance(detail["retry_after_seconds"], int)
    assert detail["retry_after_seconds"] > 0


def test_enforce_raises_401_when_no_mfa_field(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE="1")
    pool = _FakePool(row={"profile_data": {"unrelated": "value"}})
    principal = {"username": "coach1", "hardware_id": "HW_COACH1", "role": "COACH"}
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(gate.enforce_mfa_recent(pool, principal))
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail["code"] == "MFA_REVERIFY_REQUIRED"
    assert excinfo.value.detail["reason"] == "no_mfa_field"


def test_enforce_raises_401_when_pool_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE="1")
    principal = {"username": "coach1", "hardware_id": "HW_COACH1", "role": "COACH"}
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(gate.enforce_mfa_recent(None, principal))
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail["reason"] == "no_profile_data"


def test_enforce_raises_401_on_pool_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE="1")
    pool = _FakePool(raise_on_acquire=True)
    principal = {"username": "coach1", "hardware_id": "HW_COACH1", "role": "COACH"}
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(gate.enforce_mfa_recent(pool, principal))
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail["reason"] == "no_profile_data"


def test_enforce_accepts_string_encoded_profile_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """asyncpg can return JSONB as a str; helper must json.loads it."""
    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE="1")
    pd_str = json.dumps({"webauthn_last_verified": _now_iso(-60)})
    pool = _FakePool(row={"profile_data": pd_str})
    principal = {"username": "admin1", "hardware_id": "HW_ADMIN1", "role": "ADMIN"}
    asyncio.run(gate.enforce_mfa_recent(pool, principal))


def test_enforce_respects_custom_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller-supplied max_age_seconds beats the env default."""
    from fastapi import HTTPException

    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE="1", MFA_GATE_WINDOW_SECONDS="3600")
    # 120s old, default window (3600s) says fresh, but caller passes 60.
    pool = _FakePool(row={"profile_data": {"webauthn_last_verified": _now_iso(-120)}})
    principal = {"username": "admin1", "hardware_id": "HW_ADMIN1", "role": "ADMIN"}
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(gate.enforce_mfa_recent(pool, principal, max_age_seconds=60))
    assert excinfo.value.detail["retry_after_seconds"] == 60


# --------------------------------------------------------------------------- #
# enforce_mfa_recent() — Slice 6c-strict: cohort-aware window                #
# --------------------------------------------------------------------------- #


class _RaisingConn:
    """Fake conn where the FIRST fetchrow raises (simulates pre-414 schema).

    On the SECOND call it returns the fallback row. Used to prove the
    legacy-schema retry path in ``_fetch_principal_state``.
    """

    def __init__(self, fallback_row: Dict[str, Any]):
        self._fallback = fallback_row
        self._calls = 0

    async def fetchrow(self, sql: str, *_args: Any) -> Optional[Dict[str, Any]]:
        self._calls += 1
        if self._calls == 1 and "program_id" in sql:
            raise RuntimeError("column users.program_id does not exist")
        return self._fallback


class _RaisingPool:
    """Pool whose connection simulates a pre-414 users table."""

    def __init__(self, fallback_row: Dict[str, Any]):
        self._fallback = fallback_row

    def acquire(self):
        @asynccontextmanager
        async def _cm():
            yield _RaisingConn(self._fallback)

        return _cm()


def test_strict_cohort_narrows_window_below_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh MFA at 400s old is stale for a strict cohort (300s) even when the
    global default (1800s) would say fresh."""
    from fastapi import HTTPException

    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE="1")
    pool = _FakePool(
        row={
            "profile_data": {"webauthn_last_verified": _now_iso(-400)},
            "program_id": "bee_hiv_plus",
        }
    )
    principal = {"username": "cohort_user", "hardware_id": "HW_C1", "role": "CLIENT"}
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(gate.enforce_mfa_recent(pool, principal))
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail["reason"].startswith("stale:")
    # 401 retry_after_seconds should reflect the strict window, not the default.
    assert excinfo.value.detail["retry_after_seconds"] == 300


def test_strict_cohort_passes_within_strict_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh MFA at 60s old passes even for a strict cohort (300s window)."""
    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE="1")
    pool = _FakePool(
        row={
            "profile_data": {"webauthn_last_verified": _now_iso(-60)},
            "program_id": "bee_hiv_plus",
        }
    )
    principal = {"username": "cohort_user", "hardware_id": "HW_C1", "role": "CLIENT"}
    asyncio.run(gate.enforce_mfa_recent(pool, principal))


def test_non_cohort_user_uses_default_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """A general-pool user with 400s-old MFA still passes under the 1800s default."""
    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE="1")
    pool = _FakePool(
        row={
            "profile_data": {"webauthn_last_verified": _now_iso(-400)},
            "program_id": None,
        }
    )
    principal = {"username": "general_user", "hardware_id": "HW_G1", "role": "CLIENT"}
    asyncio.run(gate.enforce_mfa_recent(pool, principal))


def test_strict_cohort_clamps_caller_override_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller override wider than the strict window is clamped down.

    Caller says 1 hour is fine, but the strict cohort policy caps at 300s —
    a 400s-old MFA must still fail with retry_after=300.
    """
    from fastapi import HTTPException

    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE="1")
    pool = _FakePool(
        row={
            "profile_data": {"webauthn_last_verified": _now_iso(-400)},
            "program_id": "bee_hiv_plus",
        }
    )
    principal = {"username": "cohort_user", "hardware_id": "HW_C1", "role": "CLIENT"}
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(gate.enforce_mfa_recent(pool, principal, max_age_seconds=3600))
    assert excinfo.value.detail["retry_after_seconds"] == 300


def test_strict_cohort_respects_tighter_caller_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the caller wants an even tighter window than the strict default,
    the caller's tighter value wins."""
    from fastapi import HTTPException

    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE="1")
    pool = _FakePool(
        row={
            "profile_data": {"webauthn_last_verified": _now_iso(-90)},
            "program_id": "bee_hiv_plus",
        }
    )
    principal = {"username": "cohort_user", "hardware_id": "HW_C1", "role": "CLIENT"}
    # 90s old + caller wants 60s max → stale even though strict cohort says 300s.
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(gate.enforce_mfa_recent(pool, principal, max_age_seconds=60))
    assert excinfo.value.detail["retry_after_seconds"] == 60


def test_strict_cohort_env_override_of_strict_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operators can retune the strict window via env without a code change."""
    from fastapi import HTTPException

    gate = _reload_gate(
        monkeypatch,
        ENABLE_PHI_MFA_GATE="1",
        MFA_GATE_STRICT_WINDOW_SECONDS="120",
    )
    pool = _FakePool(
        row={
            "profile_data": {"webauthn_last_verified": _now_iso(-200)},
            "program_id": "bee_hiv_plus",
        }
    )
    principal = {"username": "cohort_user", "hardware_id": "HW_C1", "role": "CLIENT"}
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(gate.enforce_mfa_recent(pool, principal))
    assert excinfo.value.detail["retry_after_seconds"] == 120


def test_pre_414_schema_falls_back_to_legacy_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-414 deploys (no program_id column) must still enforce the gate,
    treating the user as non-cohort."""
    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE="1")
    # First fetchrow with program_id raises; fallback returns profile_data only.
    pool = _RaisingPool(fallback_row={"profile_data": {"webauthn_last_verified": _now_iso(-60)}})
    principal = {"username": "legacy_user", "hardware_id": "HW_L1", "role": "CLIENT"}
    asyncio.run(gate.enforce_mfa_recent(pool, principal))


def test_program_id_response_never_leaks_cohort_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Server-side observability yes, client-side disclosure no.

    The 401 detail must NOT contain program_id — that would let unauthenticated
    or partially-authenticated clients probe cohort membership.
    """
    from fastapi import HTTPException

    gate = _reload_gate(monkeypatch, ENABLE_PHI_MFA_GATE="1")
    pool = _FakePool(
        row={
            "profile_data": {"webauthn_last_verified": _now_iso(-10_000)},
            "program_id": "bee_hiv_plus",
        }
    )
    principal = {"username": "cohort_user", "hardware_id": "HW_C1", "role": "CLIENT"}
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(gate.enforce_mfa_recent(pool, principal))
    detail_str = str(excinfo.value.detail)
    assert "bee_hiv_plus" not in detail_str
    assert "program_id" not in detail_str
    assert "cohort" not in detail_str
