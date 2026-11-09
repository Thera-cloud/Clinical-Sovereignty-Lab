"""already_ran_this_window(): durable per-hour dedup for scheduled auditors.

Offline. Also asserts every AUDIT_HOURS auditor loop is wired to the guard so a
new auditor cannot regress to memory-only dedup.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services import audit_window_guard as guard

SERVICES = Path(__file__).resolve().parents[1] / "app" / "services"
NOW = datetime(2026, 11, 9, 17, 3, tzinfo=timezone.utc)


class _Conn:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def fetchval(self, sql, *args):
        self.calls.append((" ".join(sql.split()), args))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


@pytest.fixture(autouse=True)
def _clear_memo():
    guard.reset_memo()
    yield
    guard.reset_memo()


@pytest.mark.asyncio
async def test_row_present_returns_true_and_memoizes():
    conn = _Conn(1)
    pool = _Pool(conn)
    assert await guard.already_ran_this_window(pool, "token_lab_audit_sent", now=NOW) is True
    assert await guard.already_ran_this_window(pool, "token_lab_audit_sent", now=NOW) is True
    assert len(conn.calls) == 1  # second call served from memo
    sql, args = conn.calls[0]
    assert args == ("token_lab_audit_sent",)
    assert "date_trunc('hour', NOW())" in sql
    assert "skyeye_activity" in sql


@pytest.mark.asyncio
async def test_no_row_returns_false_and_does_not_memoize():
    conn = _Conn(None)
    pool = _Pool(conn)
    assert await guard.already_ran_this_window(pool, "gkm_audit_sent", now=NOW) is False
    assert await guard.already_ran_this_window(pool, "gkm_audit_sent", now=NOW) is False
    assert len(conn.calls) == 2


@pytest.mark.asyncio
async def test_memo_is_per_type_and_per_hour():
    pool = _Pool(_Conn(1))
    assert await guard.already_ran_this_window(pool, "a_audit_sent", now=NOW) is True
    later = NOW.replace(hour=23)
    conn2 = _Conn(None)
    assert await guard.already_ran_this_window(_Pool(conn2), "a_audit_sent", now=later) is False
    assert await guard.already_ran_this_window(_Pool(conn2), "b_audit_sent", now=NOW) is False
    assert len(conn2.calls) == 2


@pytest.mark.asyncio
async def test_fail_open_on_db_error_and_missing_pool():
    assert await guard.already_ran_this_window(_Pool(_Conn(RuntimeError("pg down"))), "x", now=NOW) is False
    assert await guard.already_ran_this_window(None, "x", now=NOW) is False
    assert await guard.already_ran_this_window(object(), "x", now=NOW) is False


def test_window_key_matches_auditor_convention():
    assert guard.window_key(NOW) == "2026-11-09_17"


GATE = re.compile(
    r"if \(now\.hour in AUDIT_HOURS[^\n]*\n\s*and not await already_ran_this_window\("
    r"self\.(?:db_pool|_db_pool|_pool), \"([a-z0-9_]+_audit_sent)\"\)\):"
)


def test_every_scheduled_auditor_is_guarded():
    skip = {"trust_enforcer.py", "agent_status_digest.py", "audit_window_guard.py"}
    unguarded, bad_type = [], []
    checked = 0
    for f in sorted(SERVICES.glob("*.py")):
        if f.name in skip:
            continue
        src = f.read_text()
        if not re.search(r"^AUDIT_HOURS\s*=", src, re.M):
            continue
        checked += 1
        m = GATE.search(src)
        if not m or "from app.services.audit_window_guard import already_ran_this_window" not in src:
            unguarded.append(f.name)
            continue
        # The guarded type must be one the file actually logs.
        if f"'{m.group(1)}'" not in src and f'"{m.group(1)}"' not in src:
            bad_type.append((f.name, m.group(1)))
        if src.count("already_ran_this_window(") != 1:
            bad_type.append((f.name, "guard count"))
    assert checked >= 50, checked
    assert unguarded == [], unguarded
    assert bad_type == [], bad_type
