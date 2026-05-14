"""
PGSD identity resolution: callers may pass users.id UUID, hardware_id, or username.
Regression: Family Entanglement passed UUID while loaders queried hardware_id-only paths.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import pytest

from app.services.pgsd_engine import PGSDEngine

LISA_USER = "LetsGoLisa"
LISA_HW = "CLIENT_LETSGOLISA_ID"
LISA_UUID = "089c82d9-c69b-4d92-a909-263f17257cf5"
BILL_USER = "LetsGoBill"
BILL_HW = "CLIENT_LETSGOBILL_ID"
BILL_UUID = "85665740-3f37-4fdd-9454-08455320a1ff"


class _FakeAcquire:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def __aenter__(self) -> Any:
        return self._conn

    async def __aexit__(self, *args: Any) -> None:
        return None


class _FakePoolResolve:
    """Minimal pool: acquire() for resolve_pgsd_subject; fetch* unused."""

    def __init__(self, rows_by_query_arg: Dict[str, Dict[str, Any]]) -> None:
        self._rows = rows_by_query_arg

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(_FakeConnResolve(self._rows))


class _FakeConnResolve:
    def __init__(self, rows: Dict[str, Dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchrow(self, sql: str, arg: str) -> Optional[Dict[str, Any]]:
        key = str(arg).strip()
        if "WHERE id = $1::uuid" in sql and key in self._rows:
            return dict(self._rows[key])
        if "WHERE hardware_id = $1" in sql and key in self._rows:
            return dict(self._rows[key])
        if "WHERE username = $1" in sql and key in self._rows:
            return dict(self._rows[key])
        return None


@pytest.fixture
def resolve_row() -> Dict[str, Dict[str, Any]]:
    canonical = {
        "id": LISA_UUID,
        "hardware_id": LISA_HW,
        "username": LISA_USER,
    }
    return {
        LISA_UUID: canonical,
        LISA_HW: canonical,
        LISA_USER: canonical,
    }


@pytest.mark.asyncio
async def test_resolve_pgsd_subject_from_users_uuid(resolve_row: Dict) -> None:
    engine = PGSDEngine(db_pool=_FakePoolResolve(resolve_row))
    r = await engine.resolve_pgsd_subject(LISA_UUID)
    assert r is not None
    assert r["id"] == LISA_UUID
    assert r["hardware_id"] == LISA_HW
    assert r["username"] == LISA_USER


@pytest.mark.asyncio
async def test_resolve_pgsd_subject_from_hardware_id(resolve_row: Dict) -> None:
    engine = PGSDEngine(db_pool=_FakePoolResolve(resolve_row))
    r = await engine.resolve_pgsd_subject(LISA_HW)
    assert r is not None
    assert r["id"] == LISA_UUID


@pytest.mark.asyncio
async def test_resolve_pgsd_subject_from_username(resolve_row: Dict) -> None:
    engine = PGSDEngine(db_pool=_FakePoolResolve(resolve_row))
    r = await engine.resolve_pgsd_subject(LISA_USER)
    assert r is not None
    assert r["hardware_id"] == LISA_HW


@pytest.mark.asyncio
async def test_resolve_unknown_logs_and_returns_none(caplog: pytest.LogCaptureFixture) -> None:
    engine = PGSDEngine(db_pool=_FakePoolResolve({}))
    caplog.set_level(logging.WARNING)
    r = await engine.resolve_pgsd_subject("nope_not_a_user")
    assert r is None
    # No exception path — simply no row; resolve returns None without warning in current code.
    assert "pgsd_subject_resolve_error" not in caplog.text


@pytest.mark.asyncio
async def test_compute_full_pgsd_distinct_fingerprints_for_two_uuids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: two internal UUIDs must not collapse to identical fingerprints."""

    engine = PGSDEngine(db_pool=object())  # unused; loaders mocked

    async def fake_resolve(subject: str) -> Optional[Dict[str, str]]:
        s = str(subject).strip()
        if s == LISA_UUID:
            return {"id": LISA_UUID, "hardware_id": LISA_HW, "username": LISA_USER}
        if s == BILL_UUID:
            return {"id": BILL_UUID, "hardware_id": BILL_HW, "username": BILL_USER}
        return None

    async def fake_crystals(uid: str) -> Dict[str, Any]:
        if uid == LISA_UUID:
            return {
                "domains": {"clinical": 0.85},
                "total_crystals": 8,
                "avg_age_days": 400,
                "crystals_last_30d": 2,
                "resolved_domains": 2,
                "avg_crystals_per_session": 0,
                "temporal_span_years": 1.1,
            }
        return {
            "domains": {"coaching": 0.35, "marketing": 0.2},
            "total_crystals": 3,
            "avg_age_days": 40,
            "crystals_last_30d": 0,
            "resolved_domains": 0,
            "avg_crystals_per_session": 0,
            "temporal_span_years": 0.11,
        }

    async def fake_metrics(uid: str) -> Dict[str, Any]:
        base = {
            "C_emo": 0.5,
            "GAP": 0.3,
            "Quantum": 0.5,
            "session_count": 4,
            "avg_engagement": 0.5,
            "anxiety": 0.0,
            "stress": 0.0,
            "depression": 0.0,
            "shame_profile": {},
        }
        if uid == LISA_UUID:
            base["C_emo"] = 0.72
        else:
            base["C_emo"] = 0.41
        return base

    async def fake_sessions(_client_key: str) -> Dict[str, Any]:
        return {"avg_duration_minutes": 50.0}

    async def fake_family(_uid: str) -> Dict[str, Any]:
        return {"has_family": False}

    async def fake_mm(_client_key: str) -> Dict[str, Any]:
        return {}

    monkeypatch.setattr(engine, "resolve_pgsd_subject", fake_resolve)
    monkeypatch.setattr(engine, "_load_crystal_data", fake_crystals)
    monkeypatch.setattr(engine, "_load_metrics", fake_metrics)
    monkeypatch.setattr(engine, "_load_session_data", fake_sessions)
    monkeypatch.setattr(engine, "_load_family_data", fake_family)
    monkeypatch.setattr(engine, "_load_multimodal", fake_mm)

    a = await engine.compute_full_pgsd(LISA_UUID)
    b = await engine.compute_full_pgsd(BILL_UUID)

    fa = a.get("emotional_fingerprint")
    fb = b.get("emotional_fingerprint")
    assert fa and fb
    assert fa != fb

    ca = a.get("coordinate_5d") or {}
    cb = b.get("coordinate_5d") or {}
    assert ca != cb


@pytest.mark.asyncio
async def test_unresolved_subject_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = PGSDEngine(db_pool=object())

    async def no_resolve(_subject: str) -> None:
        return None

    async def z_crystals(_uid: str) -> Dict[str, Any]:
        return {
            "domains": {},
            "total_crystals": 0,
            "avg_age_days": 0,
            "crystals_last_30d": 0,
            "resolved_domains": 0,
            "avg_crystals_per_session": 0,
            "temporal_span_years": 0.0,
        }

    async def z_metrics(_uid: str) -> Dict[str, Any]:
        return {
            "C_emo": 0.5,
            "GAP": 0.3,
            "Quantum": 0.5,
            "session_count": 0,
            "avg_engagement": 0.5,
            "anxiety": 0.0,
            "stress": 0.0,
            "depression": 0.0,
            "shame_profile": {},
        }

    async def z_sess(_k: str) -> Dict[str, Any]:
        return {}

    async def z_fam(_u: str) -> Dict[str, Any]:
        return {"has_family": False}

    async def z_mm(_k: str) -> Dict[str, Any]:
        return {}

    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(engine, "resolve_pgsd_subject", no_resolve)
    monkeypatch.setattr(engine, "_load_crystal_data", z_crystals)
    monkeypatch.setattr(engine, "_load_metrics", z_metrics)
    monkeypatch.setattr(engine, "_load_session_data", z_sess)
    monkeypatch.setattr(engine, "_load_family_data", z_fam)
    monkeypatch.setattr(engine, "_load_multimodal", z_mm)

    await engine.compute_full_pgsd("totally_unknown")
    assert "pgsd_subject_unresolved" in caplog.text
