"""Shared fixtures for ZEFCP tests."""

import pytest


@pytest.fixture
def swarm_secret() -> bytes:
    """Fixed swarm secret for deterministic tests."""
    return b"test-swarm-secret-32-bytes-long!"
