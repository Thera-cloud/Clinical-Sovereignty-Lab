"""Offline classroom_zoom session attribution. No database."""
from uuid import UUID

import pytest

from app.services.wisdom_lifecycle_manager import WisdomLifecycleManager
from app.services.zoom_learning_registry import classroom_zoom_wisdom_count, record_classroom_zoom_wisdom


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class _ExtractConn:
    def __init__(self):
        self.args = None
        self.sql = ""

    async def fetchrow(self, sql, *args):
        self.sql = sql
        self.args = args
        return {"id": "w-1"}


@pytest.mark.asyncio
async def test_extract_wisdom_binds_session_and_family():
    conn = _ExtractConn()
    mgr = WisdomLifecycleManager(_Pool(conn), None)
    sid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    fid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    uid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    got = await mgr.extract_wisdom(
        "classroom_zoom",
        "Live session summary for the booked client and coach.",
        user_id=uid,
        session_id=sid,
        family_id=fid,
        domain="coaching",
        confidence=0.45,
    )
    assert got == "w-1"
    assert conn.args[0] == UUID(uid)
    assert conn.args[1] == UUID(fid)
    assert conn.args[2] == UUID(sid)
    assert conn.args[6] == "classroom_zoom"


class _CountConn:
    async def fetchval(self, sql, *args):
        assert "coaching_sessions cs ON cs.id = w.session_id" in sql
        assert args[0] == "SES_20261104_9F173E"
        return 3


@pytest.mark.asyncio
async def test_classroom_zoom_wisdom_count_joins_session_id():
    n = await classroom_zoom_wisdom_count(_Pool(_CountConn()), "SES_20261104_9F173E")
    assert n == 3


@pytest.mark.asyncio
async def test_classroom_zoom_wisdom_count_empty_without_pool():
    assert await classroom_zoom_wisdom_count(None, "SES_X") == 0


class _RecordConn:
    def __init__(self):
        self.fetchval_sql = []

    async def fetchrow(self, sql, *args):
        if "FROM coaching_sessions" in sql:
            return {
                "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "client_id": "CLIENT_BLAKECBARNES_ID",
                "coach_id": "COACH_COACHN_ID",
            }
        if "FROM users" in sql:
            hw = args[0]
            if hw == "CLIENT_BLAKECBARNES_ID":
                return {"id": "11111111-1111-1111-1111-111111111111", "family_id": None}
            if hw == "COACH_COACHN_ID":
                return {"id": "22222222-2222-2222-2222-222222222222", "family_id": None}
            return None
        return None

    async def fetchval(self, sql, *args):
        self.fetchval_sql.append(sql)
        return None


@pytest.mark.asyncio
async def test_record_classroom_zoom_wisdom_writes_client_and_coach(monkeypatch):
    writes = []

    async def _fake_targets(db_pool, client_id):
        return [{"hardware_id": "CLIENT_BLAKECBARNES_ID", "name": "Blake", "primary": "1"}]

    async def _fake_extract(self, source, content, user_id=None, domain="clinical",
                            confidence=0.5, session_id=None, family_id=None):
        writes.append({"source": source, "user_id": user_id, "session_id": session_id})
        return f"w-{user_id[:4]}"

    monkeypatch.setattr(
        "app.services.zoom_household_learning.household_crystal_targets",
        _fake_targets,
    )
    monkeypatch.setattr(
        "app.services.wisdom_lifecycle_manager.WisdomLifecycleManager.extract_wisdom",
        _fake_extract,
    )
    n = await record_classroom_zoom_wisdom(
        _Pool(_RecordConn()),
        session_id="SES_20261104_9F173E",
        coach_id="COACH_COACHN_ID",
        client_id="CLIENT_BLAKECBARNES_ID",
        content="The session covered regulation skills and next-week practice.",
        client_name="Blake",
    )
    assert n == 2
    uids = {w["user_id"] for w in writes}
    assert "11111111-1111-1111-1111-111111111111" in uids
    assert "22222222-2222-2222-2222-222222222222" in uids
    assert all(w["session_id"] == "dddddddd-dddd-dddd-dddd-dddddddddddd" for w in writes)
    assert all(w["source"] == "classroom_zoom" for w in writes)
