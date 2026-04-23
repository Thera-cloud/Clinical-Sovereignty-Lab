"""
Tests for DeadmanSwitchService — silence detection and alert generation.
"""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.services.deadman_switch import (
    DeadmanSwitchService,
    DEFAULT_SILENCE_THRESHOLD_HOURS,
    HIGH_RISK_THRESHOLD_HOURS,
    ALERT_COOLDOWN_HOURS,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

class DeadmanFakeConn:
    """Extended fake connection that supports configurable query results."""

    def __init__(self):
        self._executed = []
        self._fetch_results = []
        self._fetchrow_result = None
        self._fetchval_results = []  # Pop from front on each call
        self._fetchval_index = 0

    async def fetch(self, query, *args):
        return self._fetch_results

    async def fetchrow(self, query, *args):
        return self._fetchrow_result

    async def fetchval(self, query, *args):
        if self._fetchval_index < len(self._fetchval_results):
            result = self._fetchval_results[self._fetchval_index]
            self._fetchval_index += 1
            return result
        return None

    async def execute(self, query, *args):
        self._executed.append((query, args))
        return "INSERT 0 1"


class DeadmanFakePool:
    def __init__(self, conn=None):
        self._conn = conn or DeadmanFakeConn()

    def acquire(self):
        return _FakeAcquire(self._conn)


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


# ─── Test Constants ───────────────────────────────────────────────────────────

class TestConstants:
    def test_default_silence_threshold(self):
        assert DEFAULT_SILENCE_THRESHOLD_HOURS == 72

    def test_high_risk_threshold(self):
        assert HIGH_RISK_THRESHOLD_HOURS == 48

    def test_alert_cooldown(self):
        assert ALERT_COOLDOWN_HOURS == 24


# ─── Test Initialization ─────────────────────────────────────────────────────

class TestInit:
    def test_service_stores_pool(self):
        pool = DeadmanFakePool()
        service = DeadmanSwitchService(db_pool=pool)
        assert service.db_pool is pool


# ─── Test check_all_clients ──────────────────────────────────────────────────

class TestCheckAllClients:
    @pytest.mark.asyncio
    async def test_no_clients_returns_zero(self):
        """When no clients exist, should return 0 alerts and 0 clients."""
        conn = DeadmanFakeConn()
        conn._fetch_results = []
        pool = DeadmanFakePool(conn)

        service = DeadmanSwitchService(db_pool=pool)
        result = await service.check_all_clients()

        assert result["clients_checked"] == 0
        assert result["alerts_generated"] == 0
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_active_client_no_alert(self):
        """Client with recent activity should not trigger an alert."""
        conn = DeadmanFakeConn()
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        # Simulate one client with LOW risk
        conn._fetch_results = [{
            "id": uuid4(),
            "name": "Active Client",
            "email": "active@test.com",
            "family_id": None,
            "risk_level": "LOW",
            "last_nate_message_at": recent,
        }]
        # fetchval calls: last_session, last_nudge, last_audit
        conn._fetchval_results = [recent, None, None]

        pool = DeadmanFakePool(conn)
        service = DeadmanSwitchService(db_pool=pool)
        result = await service.check_all_clients()

        assert result["clients_checked"] == 1
        assert result["alerts_generated"] == 0

    @pytest.mark.asyncio
    async def test_silent_low_risk_triggers_after_72h(self):
        """LOW risk client silent >72h should trigger alert."""
        conn = DeadmanFakeConn()
        # Last activity 100 hours ago
        old = datetime.now(timezone.utc) - timedelta(hours=100)
        conn._fetch_results = [{
            "id": uuid4(),
            "name": "Silent Client",
            "email": "silent@test.com",
            "family_id": None,
            "risk_level": "LOW",
            "last_nate_message_at": old,
        }]
        # fetchval: last_session, last_nudge, last_audit, recent_alert, coach_key
        conn._fetchval_results = [old, None, None, None, None]

        pool = DeadmanFakePool(conn)
        service = DeadmanSwitchService(db_pool=pool)
        result = await service.check_all_clients()

        assert result["clients_checked"] == 1
        assert result["alerts_generated"] == 1
        # Should have INSERT into nate_nudges and audit_log
        assert len(conn._executed) == 2

    @pytest.mark.asyncio
    async def test_high_risk_triggers_after_48h(self):
        """HIGH risk client silent >48h should trigger alert."""
        conn = DeadmanFakeConn()
        # Last activity 50 hours ago (past 48h threshold)
        old = datetime.now(timezone.utc) - timedelta(hours=50)
        conn._fetch_results = [{
            "id": uuid4(),
            "name": "High Risk Client",
            "email": "highrisk@test.com",
            "family_id": None,
            "risk_level": "HIGH",
            "last_nate_message_at": old,
        }]
        conn._fetchval_results = [old, None, None, None, None]

        pool = DeadmanFakePool(conn)
        service = DeadmanSwitchService(db_pool=pool)
        result = await service.check_all_clients()

        assert result["alerts_generated"] == 1

    @pytest.mark.asyncio
    async def test_cooldown_prevents_duplicate_alert(self):
        """Should not re-alert if already alerted within cooldown."""
        conn = DeadmanFakeConn()
        old = datetime.now(timezone.utc) - timedelta(hours=100)
        conn._fetch_results = [{
            "id": uuid4(),
            "name": "Already Alerted",
            "email": "alerted@test.com",
            "family_id": None,
            "risk_level": "LOW",
            "last_nate_message_at": old,
        }]
        # fetchval: last_session=old, last_nudge=None, last_audit=None, recent_alert=some_id
        conn._fetchval_results = [old, None, None, uuid4()]  # recent_alert exists

        pool = DeadmanFakePool(conn)
        service = DeadmanSwitchService(db_pool=pool)
        result = await service.check_all_clients()

        assert result["alerts_generated"] == 0
        # Should not have inserted any nudges or audit entries
        assert len(conn._executed) == 0

    @pytest.mark.asyncio
    async def test_new_user_no_activity_skipped(self):
        """Client with zero activity records should be skipped."""
        conn = DeadmanFakeConn()
        conn._fetch_results = [{
            "id": uuid4(),
            "name": "New User",
            "email": "new@test.com",
            "family_id": None,
            "risk_level": "LOW",
            "last_nate_message_at": None,
        }]
        # All activity sources return None
        conn._fetchval_results = [None, None, None]

        pool = DeadmanFakePool(conn)
        service = DeadmanSwitchService(db_pool=pool)
        result = await service.check_all_clients()

        assert result["clients_checked"] == 1
        assert result["alerts_generated"] == 0


# ─── Test get_silent_clients ─────────────────────────────────────────────────

class TestGetSilentClients:
    @pytest.mark.asyncio
    async def test_returns_silent_clients(self):
        """Should return formatted list of silent clients from SQL query."""
        conn = DeadmanFakeConn()
        last_active = datetime.now(timezone.utc) - timedelta(hours=100)
        conn._fetch_results = [{
            "id": uuid4(),
            "name": "Silent One",
            "email": "s@test.com",
            "last_active": last_active,
        }]

        pool = DeadmanFakePool(conn)
        service = DeadmanSwitchService(db_pool=pool)
        result = await service.get_silent_clients(threshold_hours=72)

        assert len(result) == 1
        assert result[0]["name"] == "Silent One"
        assert result[0]["silence_hours"] is not None
        assert result[0]["silence_hours"] >= 99

    @pytest.mark.asyncio
    async def test_default_threshold(self):
        """Should use DEFAULT_SILENCE_THRESHOLD_HOURS when none specified."""
        conn = DeadmanFakeConn()
        conn._fetch_results = []

        pool = DeadmanFakePool(conn)
        service = DeadmanSwitchService(db_pool=pool)
        result = await service.get_silent_clients()

        assert result == []

    @pytest.mark.asyncio
    async def test_null_last_active(self):
        """Client with NULL last_active should show silence_hours=None."""
        conn = DeadmanFakeConn()
        conn._fetch_results = [{
            "id": uuid4(),
            "name": "Unknown Activity",
            "email": "u@test.com",
            "last_active": None,
        }]

        pool = DeadmanFakePool(conn)
        service = DeadmanSwitchService(db_pool=pool)
        result = await service.get_silent_clients(threshold_hours=24)

        assert len(result) == 1
        assert result[0]["silence_hours"] is None
        assert result[0]["last_active"] is None
