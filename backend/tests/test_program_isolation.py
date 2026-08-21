"""Unit tests for program_isolation (Slice 4 of Bee HIV+ privacy plan)."""

from __future__ import annotations

import pytest

from app.services.program_isolation import (
    _crystal_program_cache,
    _user_program_cache,
    filter_crystals_by_program,
    is_enabled,
)
from app.services import program_isolation as pi


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.delenv("ENABLE_PROGRAM_ISOLATION", raising=False)
    _crystal_program_cache.clear()
    _user_program_cache.clear()
    yield
    _crystal_program_cache.clear()
    _user_program_cache.clear()


def test_flag_off_by_default():
    assert is_enabled() is False


@pytest.mark.parametrize("v", ["1", "true", "TRUE", "yes", "on"])
def test_flag_on_variants(monkeypatch, v):
    monkeypatch.setenv("ENABLE_PROGRAM_ISOLATION", v)
    assert is_enabled() is True


@pytest.mark.parametrize("v", ["0", "false", "no", "off", "maybe", ""])
def test_flag_off_variants(monkeypatch, v):
    monkeypatch.setenv("ENABLE_PROGRAM_ISOLATION", v)
    assert is_enabled() is False


def test_filter_noop_when_flag_off():
    # Flag off — even with a mismatched program_id, no filtering happens.
    rows = [
        {"id": 1, "program_id": "bee_hiv_plus"},
        {"id": 2, "program_id": None},
        {"id": 3, "program_id": "other"},
    ]
    out = filter_crystals_by_program(rows, user_program_id="bee_hiv_plus")
    assert out == rows


def test_filter_general_user_drops_program_crystals(monkeypatch):
    monkeypatch.setenv("ENABLE_PROGRAM_ISOLATION", "1")
    rows = [
        {"id": 1, "program_id": None},
        {"id": 2, "program_id": "bee_hiv_plus"},
        {"id": 3, "program_id": "other_program"},
    ]
    out = filter_crystals_by_program(rows, user_program_id=None)
    assert [r["id"] for r in out] == [1]


def test_filter_program_user_keeps_own_and_general(monkeypatch):
    monkeypatch.setenv("ENABLE_PROGRAM_ISOLATION", "1")
    rows = [
        {"id": 1, "program_id": None},
        {"id": 2, "program_id": "bee_hiv_plus"},
        {"id": 3, "program_id": "other_program"},
    ]
    out = filter_crystals_by_program(rows, user_program_id="bee_hiv_plus")
    assert [r["id"] for r in out] == [1, 2]


def test_filter_uses_id_to_program_map_when_row_lacks_column(monkeypatch):
    monkeypatch.setenv("ENABLE_PROGRAM_ISOLATION", "1")
    rows = [
        {"id": 1},
        {"id": 2},
        {"id": 3},
    ]
    id_to_program = {1: None, 2: "bee_hiv_plus", 3: "other"}
    out = filter_crystals_by_program(rows, user_program_id=None, id_to_program=id_to_program)
    assert [r["id"] for r in out] == [1]

    out2 = filter_crystals_by_program(
        rows, user_program_id="bee_hiv_plus", id_to_program=id_to_program
    )
    assert [r["id"] for r in out2] == [1, 2]


def test_filter_empty_input_returns_empty_list():
    assert filter_crystals_by_program([], user_program_id=None) == []
    assert filter_crystals_by_program([], user_program_id="foo") == []


def test_filter_missing_id_and_missing_column_defaults_to_none(monkeypatch):
    monkeypatch.setenv("ENABLE_PROGRAM_ISOLATION", "1")
    # No id, no program_id, no map — treated as general.
    rows = [{"crystal_text": "hello"}]
    out = filter_crystals_by_program(rows, user_program_id=None)
    assert out == rows
    out2 = filter_crystals_by_program(rows, user_program_id="bee_hiv_plus")
    assert out2 == rows  # general (None) is always visible to program users too


class _FakeConn:
    def __init__(self, rows=None, program_id=None, raise_exc=None):
        self._rows = rows or []
        self._program_id = program_id
        self._raise = raise_exc

    async def fetch(self, *_args, **_kwargs):
        if self._raise:
            raise self._raise
        return self._rows

    async def fetchrow(self, *_args, **_kwargs):
        if self._raise:
            raise self._raise
        if self._program_id is None:
            return None
        return {"program_id": self._program_id}


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self_inner):
                return pool._conn

            async def __aexit__(self_inner, *_a):
                return False

        return _Ctx()


@pytest.mark.asyncio
async def test_get_user_program_id_returns_value():
    pool = _FakePool(_FakeConn(program_id="bee_hiv_plus"))
    got = await pi.get_user_program_id(pool, "alice")
    assert got == "bee_hiv_plus"


@pytest.mark.asyncio
async def test_get_user_program_id_returns_none_when_missing():
    pool = _FakePool(_FakeConn(program_id=None))
    got = await pi.get_user_program_id(pool, "bob")
    assert got is None


@pytest.mark.asyncio
async def test_get_user_program_id_caches_result():
    pool = _FakePool(_FakeConn(program_id="cohort_a"))
    a = await pi.get_user_program_id(pool, "carol")
    assert a == "cohort_a"
    # Second call with a broken pool should still return the cached value.
    pool2 = _FakePool(_FakeConn(raise_exc=RuntimeError("db down")))
    b = await pi.get_user_program_id(pool2, "carol")
    assert b == "cohort_a"


@pytest.mark.asyncio
async def test_get_user_program_id_returns_none_on_db_error():
    pool = _FakePool(_FakeConn(raise_exc=RuntimeError("column missing")))
    got = await pi.get_user_program_id(pool, "dave")
    assert got is None


@pytest.mark.asyncio
async def test_bulk_fetch_returns_empty_when_disabled(monkeypatch):
    pool = _FakePool(_FakeConn(rows=[]))
    out = await pi._fetch_program_ids_bulk(pool, [])
    assert out == {}


@pytest.mark.asyncio
async def test_bulk_fetch_maps_ids_to_program_ids(monkeypatch):
    pool = _FakePool(_FakeConn(rows=[
        {"id": 1, "program_id": "bee_hiv_plus"},
        {"id": 2, "program_id": None},
    ]))
    out = await pi._fetch_program_ids_bulk(pool, [1, 2, 3])
    assert out[1] == "bee_hiv_plus"
    assert out[2] is None
    # id 3 not returned by DB → cached as None so future calls skip the DB
    assert out[3] is None


@pytest.mark.asyncio
async def test_filter_async_noop_when_flag_off(monkeypatch):
    pool = _FakePool(_FakeConn())
    rows = [{"id": 1, "program_id": "bee_hiv_plus"}, {"id": 2, "program_id": None}]
    out = await pi.filter_crystals_by_program_async(pool, rows, user_program_id=None)
    assert out == rows


@pytest.mark.asyncio
async def test_filter_async_fetches_program_ids_for_rows_missing_column(monkeypatch):
    monkeypatch.setenv("ENABLE_PROGRAM_ISOLATION", "1")
    # Rows don't carry program_id — helper should fetch from DB and filter.
    pool = _FakePool(_FakeConn(rows=[
        {"id": 10, "program_id": None},
        {"id": 11, "program_id": "bee_hiv_plus"},
    ]))
    rows = [{"id": 10}, {"id": 11}]
    out = await pi.filter_crystals_by_program_async(pool, rows, user_program_id=None)
    assert [r["id"] for r in out] == [10]

    _crystal_program_cache.clear()
    pool2 = _FakePool(_FakeConn(rows=[
        {"id": 10, "program_id": None},
        {"id": 11, "program_id": "bee_hiv_plus"},
    ]))
    out2 = await pi.filter_crystals_by_program_async(
        pool2, rows, user_program_id="bee_hiv_plus"
    )
    assert [r["id"] for r in out2] == [10, 11]


@pytest.mark.asyncio
async def test_filter_async_uses_row_program_id_without_db(monkeypatch):
    monkeypatch.setenv("ENABLE_PROGRAM_ISOLATION", "1")
    class _NoFetch(_FakeConn):
        async def fetch(self, *a, **k):  # pragma: no cover — should not be called
            raise AssertionError("fetch should not be called")

    pool = _FakePool(_NoFetch())
    rows = [
        {"id": 1, "program_id": None},
        {"id": 2, "program_id": "bee_hiv_plus"},
    ]
    out = await pi.filter_crystals_by_program_async(pool, rows, user_program_id=None)
    assert [r["id"] for r in out] == [1]
