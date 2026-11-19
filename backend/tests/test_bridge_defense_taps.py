"""Bridge Guardian and Pipeline Drum are local and do not reject a login."""
import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

_BRIDGE = Path(__file__).resolve().parents[1] / "app" / "websocket" / "bridge_server.py"


@pytest.fixture(autouse=True)
def _reset_taps():
    import app.websocket.bridge_defense_taps as taps
    taps._guardian = None
    taps._drum = None
    taps._tapped = False
    taps._login_redis = False
    yield
    taps._guardian = None
    taps._drum = None
    taps._tapped = False
    taps._login_redis = None


def test_guardian_stays_off_without_a_pool():
    from app.websocket.bridge_defense_taps import bridge_guardian
    assert bridge_guardian(None) is None


def test_guardian_uses_this_process_pool():
    from app.websocket.bridge_defense_taps import bridge_guardian
    pool = object()
    fibre = bridge_guardian(pool)
    assert fibre._db is pool
    assert bridge_guardian(pool) is fibre


@pytest.mark.asyncio
async def test_drum_senses_a_frame_without_a_database():
    from app.websocket.bridge_defense_taps import bridge_drum, note_drum_tap
    drum = await bridge_drum()
    assert drum._db is None
    assert await drum.is_ready()
    note_drum_tap(drum, "ws://pong", b"{}")
    assert len(drum.moisture._request_distribution) == 1
    await drum.stop()


class _Attempts:
    def __init__(self, count, boom=False):
        self.count = count
        self.boom = boom
        self.calls = 0

    async def fetchrow(self, query, *args):
        self.calls += 1
        self.query = query
        self.args = args
        if self.boom:
            raise RuntimeError("db down")
        return {"fail_count": self.count, "last_attempt": datetime.now(timezone.utc)}


@pytest.mark.asyncio
async def test_blank_name_locks_by_caller_address_only():
    from app.websocket.bridge_defense_taps import bridge_login_allowed
    pool = _Attempts(5)
    locked = await bridge_login_allowed(pool, "  ", "CLIENT", "203.0.113.10", "")
    assert locked["allowed"] is False
    assert pool.args[0] == "ip:203.0.113.10"
    skipped = _Attempts(9)
    result = await bridge_login_allowed(skipped, "  ", "CLIENT", "", "")
    assert result["allowed"] is True
    assert skipped.calls == 0


@pytest.mark.asyncio
async def test_case_variants_share_one_durable_counter():
    from app.websocket.bridge_defense_taps import bridge_login_allowed
    pool = _Attempts(4)
    result = await bridge_login_allowed(pool, "Client1", "CLIENT", "203.0.113.10", "")
    assert result["allowed"] is True
    assert "LOWER(identifier)" in pool.query
    assert pool.args[0] == "Client1"


@pytest.mark.asyncio
async def test_five_recent_failures_lock_without_a_password_check():
    from app.websocket.bridge_defense_taps import bridge_login_allowed
    open_try = await bridge_login_allowed(_Attempts(4), "client1", "CLIENT", "203.0.113.10", "ua")
    assert open_try["allowed"] is True
    locked = await bridge_login_allowed(_Attempts(5), "client1", "CLIENT", "203.0.113.10", "ua")
    assert locked["allowed"] is False
    assert locked["lockout_remaining_sec"] > 0
    coach = await bridge_login_allowed(_Attempts(5), "CoachN", "COACH", "203.0.113.10", "ua")
    assert coach["allowed"] is False


@pytest.mark.asyncio
async def test_a_database_error_still_allows_the_password_check():
    from app.websocket.bridge_defense_taps import bridge_login_allowed
    result = await bridge_login_allowed(_Attempts(5, boom=True), "client1", "CLIENT", "203.0.113.10", "")
    assert result["allowed"] is True
    assert await bridge_login_allowed(None, "client1", "CLIENT", "203.0.113.10", "")
    assert (await bridge_login_allowed(None, "client1", "CLIENT", "203.0.113.10", ""))["allowed"] is True


class _SlowFails:
    def __init__(self, prior=0):
        self.n = prior
        self.lock = -1
        self.cleared = False

    def ttl(self, _key):
        return self.lock

    def delete(self, *_keys):
        self.n = 0
        self.lock = -1
        self.cleared = True

    def set(self, *_args, **_kwargs):
        self.lock = 180

    def pipeline(self):
        return self

    def zadd(self, _key, _mapping):
        self.n += 1

    def zremrangebyscore(self, *_args):
        return 0

    def zcard(self, _key):
        return self.n

    def expire(self, *_args):
        return True

    def execute(self):
        return [1, 0, self.n, True]


@pytest.mark.asyncio
async def test_slow_misses_lock_after_a_restart_and_clear_on_success():
    import app.websocket.bridge_defense_taps as taps
    from app.websocket.bridge_defense_taps import (
        bridge_login_allowed, note_login_failure, note_login_success,
    )
    window = _SlowFails(prior=4)
    taps._login_redis = window
    await note_login_failure("Client1", "203.0.113.44")
    assert window.lock == 180
    locked = await bridge_login_allowed(_Attempts(0), "client1", "CLIENT", "203.0.113.44", "")
    assert locked["allowed"] is False
    assert locked["lockout_remaining_sec"] == 180
    await note_login_success("client1", "203.0.113.44")
    assert window.lock == -1
    open_try = await bridge_login_allowed(_Attempts(0), "client1", "CLIENT", "203.0.113.44", "")
    assert open_try["allowed"] is True


@pytest.mark.asyncio
async def test_redis_counter_error_still_allows_the_password_check():
    import app.websocket.bridge_defense_taps as taps
    from app.websocket.bridge_defense_taps import bridge_login_allowed

    class _Down:
        def ttl(self, _key):
            raise RuntimeError("redis down")

    taps._login_redis = _Down()
    result = await bridge_login_allowed(_Attempts(0), "client1", "CLIENT", "203.0.113.44", "")
    assert result["allowed"] is True


def test_bridge_does_not_reject_a_login_from_the_score():
    text = _BRIDGE.read_text()
    ast.parse(text)
    assert "bridge_guardian" in text
    assert "bridge_login_allowed" in text
    assert "note_drum_tap" in text
    assert "requires_verification" not in text
    assert "generate_device_verification" not in text
    assert "note_login_failure" in text
    assert "note_login_success" in text
    taps = Path(__file__).resolve().parents[1].joinpath("app/websocket/bridge_defense_taps.py").read_text()
    assert "success = TRUE" in taps
    assert "LOWER(identifier)" in taps
