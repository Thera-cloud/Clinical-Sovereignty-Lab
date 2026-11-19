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
    yield
    taps._guardian = None
    taps._drum = None
    taps._tapped = False


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

    async def fetchrow(self, *_args):
        self.calls += 1
        if self.boom:
            raise RuntimeError("db down")
        return {"fail_count": self.count, "last_attempt": datetime.now(timezone.utc)}


@pytest.mark.asyncio
async def test_empty_username_skips_the_durable_lock():
    from app.websocket.bridge_defense_taps import bridge_login_allowed
    pool = _Attempts(9)
    result = await bridge_login_allowed(pool, "  ", "CLIENT", "203.0.113.10", "")
    assert result["allowed"] is True
    assert pool.calls == 0


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


def test_bridge_does_not_reject_a_login_from_the_score():
    text = _BRIDGE.read_text()
    ast.parse(text)
    assert "bridge_guardian" in text
    assert "bridge_login_allowed" in text
    assert "note_drum_tap" in text
    assert "requires_verification" not in text
    assert "generate_device_verification" not in text
    taps = Path(__file__).resolve().parents[1].joinpath("app/websocket/bridge_defense_taps.py").read_text()
    assert "success = TRUE" in taps
