"""Offline unit tests for biometrics_consent (Slice 0).

Runs under CI without a database. Uses a mock db_pool that mimics asyncpg's
`acquire() -> connection` context manager surface.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import biometrics_consent as bc


class _FakeConn:
    def __init__(self, fetchrow_result=None, execute_side_effect=None, execute_result="UPDATE 1"):
        self._fetchrow_result = fetchrow_result
        self._execute_side_effect = execute_side_effect
        self._execute_result = execute_result
        self.executed = []

    async def fetchrow(self, *args, **kwargs):
        return self._fetchrow_result

    async def execute(self, sql, *args, **kwargs):
        if self._execute_side_effect:
            raise self._execute_side_effect
        self.executed.append((sql, args))
        return self._execute_result

    def transaction(self):
        return _FakeTx()


class _FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.get_event_loop().is_closed() else asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _reset_cache():
    bc.cache_clear()
    yield
    bc.cache_clear()


def test_disabled_user_returns_true():
    pool = _FakePool(_FakeConn(fetchrow_result={"biometrics_disabled": True}))
    result = asyncio.run(bc.is_biometrics_disabled("alice", pool))
    assert result is True


def test_enabled_user_returns_false():
    pool = _FakePool(_FakeConn(fetchrow_result={"biometrics_disabled": False}))
    result = asyncio.run(bc.is_biometrics_disabled("bob", pool))
    assert result is False


def test_missing_user_returns_false():
    pool = _FakePool(_FakeConn(fetchrow_result=None))
    result = asyncio.run(bc.is_biometrics_disabled("ghost", pool))
    assert result is False


def test_none_pool_fails_open():
    result = asyncio.run(bc.is_biometrics_disabled("alice", None))
    assert result is False


def test_empty_username_fails_open():
    pool = _FakePool(_FakeConn(fetchrow_result={"biometrics_disabled": True}))
    result = asyncio.run(bc.is_biometrics_disabled("", pool))
    assert result is False


def test_db_error_fails_open():
    class _BadConn:
        async def fetchrow(self, *a, **kw):
            raise RuntimeError("db down")

    pool = _FakePool(_BadConn())
    result = asyncio.run(bc.is_biometrics_disabled("alice", pool))
    assert result is False


def test_cache_hit_avoids_db():
    conn = _FakeConn(fetchrow_result={"biometrics_disabled": True})
    pool = _FakePool(conn)
    asyncio.run(bc.is_biometrics_disabled("alice", pool))
    conn._fetchrow_result = {"biometrics_disabled": False}
    result = asyncio.run(bc.is_biometrics_disabled("alice", pool))
    assert result is True


def test_cache_clear_invalidates():
    conn = _FakeConn(fetchrow_result={"biometrics_disabled": True})
    pool = _FakePool(conn)
    asyncio.run(bc.is_biometrics_disabled("alice", pool))
    bc.cache_clear("alice")
    conn._fetchrow_result = {"biometrics_disabled": False}
    result = asyncio.run(bc.is_biometrics_disabled("alice", pool))
    assert result is False


def test_username_normalized_case_insensitive():
    conn = _FakeConn(fetchrow_result={"biometrics_disabled": True})
    pool = _FakePool(conn)
    asyncio.run(bc.is_biometrics_disabled("ALICE", pool))
    result = asyncio.run(bc.is_biometrics_disabled("Alice", pool))
    assert result is True


def test_set_opt_out_success():
    conn = _FakeConn(execute_result="UPDATE 1")
    pool = _FakePool(conn)
    result = asyncio.run(bc.set_biometrics_opt_out("alice", True, "alice", "consent-withdrawn", pool))
    assert result is True
    assert len(conn.executed) == 2
    assert "UPDATE users" in conn.executed[0][0]
    assert "INSERT INTO biometrics_opt_out_log" in conn.executed[1][0]


def test_set_opt_out_user_not_found():
    conn = _FakeConn(execute_result="UPDATE 0")
    pool = _FakePool(conn)
    result = asyncio.run(bc.set_biometrics_opt_out("ghost", True, "admin", None, pool))
    assert result is False


def test_get_status_returns_bool():
    pool = _FakePool(_FakeConn(fetchrow_result={"biometrics_disabled": True}))
    result = asyncio.run(bc.get_biometrics_status("alice", pool))
    assert result is True


def test_get_status_missing_user_returns_none():
    pool = _FakePool(_FakeConn(fetchrow_result=None))
    result = asyncio.run(bc.get_biometrics_status("ghost", pool))
    assert result is None
