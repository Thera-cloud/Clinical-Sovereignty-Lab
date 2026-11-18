"""Bridge Guardian and Pipeline Drum are local and do not reject a login."""
import ast
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


def test_bridge_does_not_reject_a_login_from_the_score():
    text = _BRIDGE.read_text()
    ast.parse(text)
    assert "bridge_guardian" in text
    assert "note_drum_tap" in text
    assert "requires_verification" not in text
    assert "member_login_guardian" in text
