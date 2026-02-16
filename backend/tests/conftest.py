"""
Shared pytest fixtures for the Sovereign Swarm test suite.
"""

import pytest
from uuid import uuid4
from datetime import datetime


class FakeConnection:
    def __init__(self):
        self._executed = []
        self._fetch_results = []
        self._fetchrow_result = None
        self._fetchval_result = None

    async def fetch(self, query, *args):
        return self._fetch_results

    async def fetchrow(self, query, *args):
        return self._fetchrow_result

    async def fetchval(self, query, *args):
        return self._fetchval_result

    async def execute(self, query, *args):
        self._executed.append((query, args))
        return "INSERT 0 1"


class FakePool:
    def __init__(self):
        self._conn = FakeConnection()

    def acquire(self):
        return FakeAcquireContext(self._conn)


class FakeAcquireContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


class FakeRedis:
    def __init__(self):
        self._data = {}

    async def ping(self):
        return True

    async def xadd(self, name, fields, maxlen=None):
        if name not in self._data:
            self._data[name] = []
        self._data[name].append(fields)
        return b"1-0"

    async def info(self, section=None):
        return {}

    async def close(self):
        pass


@pytest.fixture
def fake_pool():
    return FakePool()


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def fake_conn(fake_pool):
    return fake_pool._conn
