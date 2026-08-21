"""Unit tests for `encryption_pool_kwargs()` — Slice 2.

The helper decides whether asyncpg pools should attach the pgcrypto
`init_connection` callback. The wiring itself is a no-op when no key is
resolvable, so these tests only verify the flag → kwargs contract.
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ENABLE_PGCRYPTO_ENCRYPTION", raising=False)
    yield


def test_flag_off_returns_empty_kwargs():
    from app.services.db_encryption_middleware import encryption_pool_kwargs

    assert encryption_pool_kwargs() == {}


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_flag_on_returns_init_callback(monkeypatch, value):
    monkeypatch.setenv("ENABLE_PGCRYPTO_ENCRYPTION", value)
    from app.services.db_encryption_middleware import (
        encryption_pool_kwargs,
        init_connection,
    )

    kw = encryption_pool_kwargs()
    assert list(kw.keys()) == ["init"]
    assert kw["init"] is init_connection


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_flag_falsy_returns_empty_kwargs(monkeypatch, value):
    monkeypatch.setenv("ENABLE_PGCRYPTO_ENCRYPTION", value)
    from app.services.db_encryption_middleware import encryption_pool_kwargs

    assert encryption_pool_kwargs() == {}
