"""Phase E4 — per-window envelope signing offline fences (importlib — avoid numpy FPE).

Covers:
  - ln7_envelope_signing.sign_fields()/verify_row_signature(): round-trips,
    tamper detection, window bucketing, legacy-row handling.
  - ln7_outcome_envelope.write_envelope(): passes sig/sig_window through to
    the INSERT, and falls back to an unsigned INSERT if the DB doesn't have
    the columns yet (pre-migration-315 rollout race).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
SERVICES = APP / "services"


def _ensure_pkg(name: str, path: Path) -> None:
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]  # type: ignore[attr-defined]
        sys.modules[name] = pkg


def _load(name: str, path: Path):
    _ensure_pkg("app", APP)
    _ensure_pkg("app.services", SERVICES)
    if name in sys.modules and getattr(sys.modules[name], "__file__", None) == str(path):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _sig_mod():
    return _load("app.services.ln7_envelope_signing", SERVICES / "ln7_envelope_signing.py")


def test_window_id_buckets_by_fixed_width():
    sig = _sig_mod()
    w = sig.window_id_for(ts=1000.0, window_s=900)
    assert w == "w900:1"
    # Same bucket for any ts within [900, 1800)
    assert sig.window_id_for(ts=1799.9, window_s=900) == w
    # Next bucket right at the boundary
    assert sig.window_id_for(ts=1800.0, window_s=900) != w


def test_sign_and_verify_round_trip():
    sig = _sig_mod()
    fields = {
        "loop_name": "ln7",
        "event_kind": "coding_outcome",
        "revision_id": "LN7-1",
        "patch_hash": "abc123",
        "confounded": False,
        "cost_usd": 0.12,
    }
    out = sig.sign_fields(fields, ts=1000.0)
    assert out["sig"] and out["sig_window"]

    row = dict(fields)
    row["sig"] = out["sig"]
    row["sig_window"] = out["sig_window"]
    assert sig.verify_row_signature(row) is True


def test_verify_detects_tamper():
    sig = _sig_mod()
    fields = {"loop_name": "ln7", "event_kind": "coding_outcome", "confounded": False}
    out = sig.sign_fields(fields, ts=1000.0)

    tampered = dict(fields)
    tampered["confounded"] = True  # flip the flag post-hoc
    tampered["sig"] = out["sig"]
    tampered["sig_window"] = out["sig_window"]
    assert sig.verify_row_signature(tampered) is False


def test_verify_legacy_unsigned_row_is_false_not_error():
    sig = _sig_mod()
    row = {"loop_name": "ln7", "event_kind": "coding_outcome", "sig": None, "sig_window": None}
    assert sig.verify_row_signature(row) is False


def test_different_windows_produce_different_signatures():
    sig = _sig_mod()
    fields = {"loop_name": "ln7", "event_kind": "coding_outcome"}
    a = sig.sign_fields(fields, ts=1000.0)
    b = sig.sign_fields(fields, ts=1000.0 + sig.DEFAULT_WINDOW_S)
    assert a["sig_window"] != b["sig_window"]
    assert a["sig"] != b["sig"]


class _FakeConn:
    """Records fetchrow calls; first call raises to exercise the pre-migration
    fallback path, unless configured otherwise."""

    def __init__(self, fail_signed_insert: bool = False):
        self.fail_signed_insert = fail_signed_insert
        self.calls = []

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        if self.fail_signed_insert and "sig_window" in query and len(self.calls) == 1:
            raise Exception('column "sig" of relation "outcome_envelope" does not exist')
        return {"envelope_id": "env-fixed-1"}


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


def test_write_envelope_includes_signature_columns():
    env = _load("app.services.ln7_outcome_envelope", SERVICES / "ln7_outcome_envelope.py")
    conn = _FakeConn()
    pool = _FakePool(conn)

    result = asyncio.run(
        env.write_envelope(
            pool,
            loop_name="ln7",
            event_kind="coding_outcome",
            revision_id="LN7-1",
            patch_hash="abc123",
        )
    )

    assert result == "env-fixed-1"
    assert len(conn.calls) == 1
    query, args = conn.calls[0]
    assert "sig_window" in query
    # sig, sig_window are the last two positional args ($15, $16)
    assert args[-2] is not None  # sig
    assert args[-1] is not None  # sig_window


def test_write_envelope_falls_back_when_columns_missing():
    env = _load("app.services.ln7_outcome_envelope", SERVICES / "ln7_outcome_envelope.py")
    conn = _FakeConn(fail_signed_insert=True)
    pool = _FakePool(conn)

    result = asyncio.run(
        env.write_envelope(
            pool,
            loop_name="ln7",
            event_kind="coding_outcome",
            revision_id="LN7-1",
        )
    )

    assert result == "env-fixed-1"
    # First call (signed) raised, second call (unsigned fallback) succeeded.
    assert len(conn.calls) == 2
    first_query, _ = conn.calls[0]
    second_query, _ = conn.calls[1]
    assert "sig_window" in first_query
    assert "sig_window" not in second_query


def test_write_envelope_mirrors_columns_into_attribution_json():
    """E2: empty/omitted attribution still gets revision_id/patch_hash in JSONB."""
    env = _load("app.services.ln7_outcome_envelope", SERVICES / "ln7_outcome_envelope.py")
    conn = _FakeConn()
    pool = _FakePool(conn)

    result = asyncio.run(
        env.write_envelope(
            pool,
            loop_name="ln7",
            event_kind="coding_outcome",
            revision_id="LN7-1",
            patch_hash="abc123",
            attribution={},  # caller forgot E2 keys
        )
    )

    assert result == "env-fixed-1"
    _query, args = conn.calls[0]
    # $9 is attribution_json
    import json

    attr = json.loads(args[8])
    assert attr.get("revision_id") == "LN7-1"
    assert attr.get("patch_hash") == "abc123"


def test_write_envelope_caller_attribution_overrides_columns():
    env = _load("app.services.ln7_outcome_envelope", SERVICES / "ln7_outcome_envelope.py")
    conn = _FakeConn()
    pool = _FakePool(conn)

    asyncio.run(
        env.write_envelope(
            pool,
            loop_name="ln7",
            event_kind="coding_outcome",
            revision_id="COL-REV",
            attribution={"revision_id": "CALLER-REV", "evidence_uri": "s3://x"},
        )
    )
    import json

    attr = json.loads(conn.calls[0][1][8])
    assert attr["revision_id"] == "CALLER-REV"
    assert attr["evidence_uri"] == "s3://x"
