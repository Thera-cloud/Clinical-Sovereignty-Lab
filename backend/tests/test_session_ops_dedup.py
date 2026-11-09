"""Duplicate-email guards for Schedule Ops + sibling schedulers.

Offline: fake asyncpg pool, no network. Covers
  1. SessionOpsReconcileAgent digest — durable DB dedup survives a restart
  2. SessionOpsReconcileAgent cancel notify — claim-first (DB + memory) then send
  3. apply_coach_session_cancel — marks cancel_notify_sent so the agent won't re-send
  4. trust_enforcer / agent_status_digest — whole-hour lookback, not 30 min
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.services import session_approval as approval
from app.services import session_ops_reconcile_agent as mod
from app.services.session_ops_reconcile_agent import SessionOpsReconcileAgent

SERVICES = Path(__file__).resolve().parents[1] / "app" / "services"


class _Conn:
    def __init__(self, *, fetchval_results=None):
        self.calls: list = []
        self._fetchval_results = list(fetchval_results or [])

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", " ".join(sql.split()), args))
        if self._fetchval_results:
            return self._fetchval_results.pop(0)
        return None

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", " ".join(sql.split()), args))
        return None

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", " ".join(sql.split()), args))
        return []

    async def execute(self, sql, *args):
        self.calls.append(("execute", " ".join(sql.split()), args))
        return "UPDATE 1"


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


# 20:30 ET on 2026-11-08 == 01:30Z 2026-11-09 — inside the evening digest window.
DIGEST_NOW = datetime(2026, 11, 9, 1, 30, tzinfo=timezone.utc)


# ---------------------------------------------------------------- 1. digest


@pytest.mark.asyncio
async def test_digest_skipped_when_db_row_exists_this_window(monkeypatch):
    """Restart inside the window: memory key is empty but skyeye_activity has
    the row → no second email."""
    conn = _Conn(fetchval_results=[1])
    agent = SessionOpsReconcileAgent(db_pool=_Pool(conn))
    sent = AsyncMock()
    monkeypatch.setattr(agent, "_send_digest", sent)

    await agent._maybe_digest({"healed": [], "flags": []}, DIGEST_NOW)

    sent.assert_not_awaited()
    kinds = [c[0] for c in conn.calls]
    assert kinds == ["fetchval"]
    assert "session_ops_reconcile_sent" in conn.calls[0][1]
    assert "INTERVAL '6 hours'" in conn.calls[0][1]
    # Memory key is still set so the rest of the hour short-circuits without a DB hit.
    assert agent._last_digest_key == "2026-11-08-20"


@pytest.mark.asyncio
async def test_digest_sent_once_then_memory_short_circuits(monkeypatch):
    conn = _Conn(fetchval_results=[None])
    agent = SessionOpsReconcileAgent(db_pool=_Pool(conn))
    sent = AsyncMock()
    monkeypatch.setattr(agent, "_send_digest", sent)

    await agent._maybe_digest({"healed": [], "flags": ["x"]}, DIGEST_NOW)
    await agent._maybe_digest({"healed": [], "flags": ["x"]}, DIGEST_NOW)

    sent.assert_awaited_once()
    # Second call never touched the DB (memory fast path).
    assert len([c for c in conn.calls if c[0] == "fetchval"]) == 1


@pytest.mark.asyncio
async def test_digest_outside_window_no_db_no_send(monkeypatch):
    conn = _Conn()
    agent = SessionOpsReconcileAgent(db_pool=_Pool(conn))
    sent = AsyncMock()
    monkeypatch.setattr(agent, "_send_digest", sent)

    # 13:28Z == 08:28 ET
    await agent._maybe_digest({}, datetime(2026, 11, 9, 13, 28, tzinfo=timezone.utc))

    sent.assert_not_awaited()
    assert conn.calls == []


@pytest.mark.asyncio
async def test_digest_db_error_fails_open(monkeypatch):
    """Dedup check raising must not suppress the digest entirely."""

    class _Boom(_Conn):
        async def fetchval(self, sql, *args):
            raise RuntimeError("pg down")

    agent = SessionOpsReconcileAgent(db_pool=_Pool(_Boom()))
    sent = AsyncMock()
    monkeypatch.setattr(agent, "_send_digest", sent)

    await agent._maybe_digest({"healed": [], "flags": []}, DIGEST_NOW)

    sent.assert_awaited_once()


# ---------------------------------------------------------- 2. cancel notify


def _dead_row() -> dict:
    return {
        "session_id": "SES_DEDUP_1",
        "client_id": "CLIENT_A",
        "coach_id": "COACH_X",
        "status": "cancelled",
        "payment_status": "paid",
        "price_cents": 7500,
        "scheduled_start": "2026-11-10T15:00:00+00:00",
        "session_data": {},
    }


@pytest.mark.asyncio
async def test_notify_cancel_claims_before_sending(monkeypatch):
    conn = _Conn(fetchval_results=["SES_DEDUP_1"])  # claim UPDATE ... RETURNING wins
    agent = SessionOpsReconcileAgent(db_pool=_Pool(conn))
    order: list = []

    async def _client(db_pool, row, **kw):
        order.append(("client", bool(_sd(row).get("cancel_notify_sent"))))
        return {"email": True}

    async def _coach(db_pool, row, **kw):
        order.append(("coach", bool(_sd(row).get("cancel_notify_sent"))))
        return {"email": True}

    monkeypatch.setattr(approval, "notify_client_of_coach_cancel", _client)
    monkeypatch.setattr(approval, "notify_coach_of_client_cancel", _coach)

    row = _dead_row()
    await agent._notify_cancel(row)

    # DB claim happened first and is the conditional UPDATE.
    assert conn.calls[0][0] == "fetchval"
    assert "cancel_notify_sent" in conn.calls[0][1]
    assert "RETURNING session_id" in conn.calls[0][1]
    assert "NOT IN ('true', '1', 'yes')" in conn.calls[0][1]
    # Both senders ran, and saw the in-memory flag already set.
    assert order == [("client", True), ("coach", True)]
    assert row["session_data"]["cancel_notify_sent"] is True
    # No post-send UPDATE anymore (claim replaced it).
    assert [c[0] for c in conn.calls] == ["fetchval"]


@pytest.mark.asyncio
async def test_notify_cancel_skips_when_claim_lost(monkeypatch):
    """Another path (REST coach cancel / payment agent) already flagged it."""
    conn = _Conn(fetchval_results=[None])
    agent = SessionOpsReconcileAgent(db_pool=_Pool(conn))
    client = AsyncMock(return_value={"email": True})
    coach = AsyncMock(return_value={"email": True})
    monkeypatch.setattr(approval, "notify_client_of_coach_cancel", client)
    monkeypatch.setattr(approval, "notify_coach_of_client_cancel", coach)

    row = _dead_row()
    await agent._notify_cancel(row)

    client.assert_not_awaited()
    coach.assert_not_awaited()
    assert row["session_data"]["cancel_notify_sent"] is True


@pytest.mark.asyncio
async def test_notify_cancel_skips_when_memory_flag_set(monkeypatch):
    conn = _Conn()
    agent = SessionOpsReconcileAgent(db_pool=_Pool(conn))
    client = AsyncMock()
    monkeypatch.setattr(approval, "notify_client_of_coach_cancel", client)

    row = _dead_row()
    row["session_data"] = '{"cancel_notify_sent": true}'
    await agent._notify_cancel(row)

    client.assert_not_awaited()
    assert conn.calls == []


@pytest.mark.asyncio
async def test_notify_cancel_claim_db_error_does_not_send(monkeypatch):
    class _Boom(_Conn):
        async def fetchval(self, sql, *args):
            raise RuntimeError("pg down")

    agent = SessionOpsReconcileAgent(db_pool=_Pool(_Boom()))
    client = AsyncMock()
    monkeypatch.setattr(approval, "notify_client_of_coach_cancel", client)

    await agent._notify_cancel(_dead_row())

    client.assert_not_awaited()


def _sd(row):
    sd = row.get("session_data") or {}
    return sd if isinstance(sd, dict) else {}


# --------------------------------------------- 3. REST coach cancel sets flag


@pytest.mark.asyncio
async def test_apply_coach_session_cancel_marks_notify_sent(monkeypatch):
    session = {
        "session_id": "SES_COACH_CXL_FLAG",
        "client_id": "CLIENT_A",
        "coach_id": "COACH_X",
        "status": "scheduled",
        "scheduled_start": "2026-11-12T12:00:00+00:00",
    }
    refund = AsyncMock(return_value=("refunded", "re_x"))
    notify = AsyncMock(return_value={"email": True, "sms": False})
    monkeypatch.setattr(
        approval, "notify_coach_of_client_cancel", AsyncMock(return_value={"email": True})
    )

    out = await approval.apply_coach_session_cancel(
        None, session, reason="coach closed", _refund=refund, _notify=notify,
    )

    assert out["session"]["status"] == "cancelled"
    assert session["cancel_notify_sent"] is True
    assert session["cancel_notified_by"] == "coach_cancel"
    # The reconcile agent reads session_data.cancel_notify_sent after
    # upsert_session_pg folds unknown top-level keys into session_data.
    assert mod._notify_sent({"session_data": {"cancel_notify_sent": True}}) is True


@pytest.mark.asyncio
async def test_apply_coach_session_cancel_no_flag_when_nothing_sent(monkeypatch):
    session = {
        "session_id": "SES_COACH_CXL_NOFLAG",
        "client_id": "CLIENT_A",
        "coach_id": "COACH_X",
        "status": "scheduled",
        "scheduled_start": "2026-11-12T12:00:00+00:00",
    }
    refund = AsyncMock(return_value=("none", ""))
    notify = AsyncMock(return_value={"email": False, "sms": False})
    monkeypatch.setattr(
        approval, "notify_coach_of_client_cancel", AsyncMock(return_value={"email": False})
    )

    await approval.apply_coach_session_cancel(
        None, session, reason="x", _refund=refund, _notify=notify,
    )

    # Nothing went out → leave it to the reconcile agent to notify.
    assert "cancel_notify_sent" not in session


def test_upsert_folds_unknown_keys_into_session_data():
    """Guards the contract the flag relies on: top-level keys not in the PG
    column set are serialised into session_data."""
    src = (SERVICES / "pg_data_helpers.py").read_text()
    assert "extra = {k: v for k, v in session.items() if k not in known_keys" in src
    assert "json.dumps(extra" in src


# ------------------------------------- 4. sibling schedulers: hour lookback


@pytest.mark.parametrize(
    "fname,activity",
    [
        ("trust_enforcer.py", "trust_enforcer_sent"),
        ("agent_status_digest.py", "agent_digest_sent"),
    ],
)
def test_sibling_schedulers_use_whole_hour_lookback(fname, activity):
    src = (SERVICES / fname).read_text()
    i = src.index(f"type='{activity}'")
    chunk = src[i : i + 200]
    assert "date_trunc('hour', NOW())" in chunk
    assert "INTERVAL '30 minutes'" not in chunk


def test_safe_deploy_warns_on_email_windows():
    sh = (Path(__file__).resolve().parents[2] / "scripts" / "safe_deploy.sh").read_text()
    assert "digest hour" in sh
    assert "audit window" in sh
    assert "TZ=America/New_York" in sh
    # Advisory only — must not abort the deploy.
    warn_block = sh[sh.index("Email-window advisory") : sh.index("ts=$(date -u")]
    assert "exit" not in warn_block
