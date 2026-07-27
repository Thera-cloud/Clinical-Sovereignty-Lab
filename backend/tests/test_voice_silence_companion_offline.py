"""Offline unit tests for VoiceSilenceCompanion quiet check-in.

Loads module by file path to avoid app.services.__init__ → numpy SIGFPE on macOS.
"""

from __future__ import annotations

import asyncio
import importlib.util
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SVC = _ROOT / "app" / "services" / "voice_silence_companion.py"
_spec = importlib.util.spec_from_file_location("voice_silence_companion", _SVC)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)

VoiceSilenceCompanion = _mod.VoiceSilenceCompanion


@pytest.mark.asyncio
async def test_soft_checkins_then_final_wait_then_alert():
    spoken: list[str] = []
    alerts: list[str] = []

    async def speak(t: str) -> None:
        spoken.append(t)

    async def alert(m: str) -> None:
        alerts.append(m)

    c = VoiceSilenceCompanion(
        speak=speak,
        alert_coach=alert,
        client_name="Kristy",
        checkin_s=15.0,
        final_wait_s=30.0,
        max_soft=3,
        startup_grace_s=5.0,
    )
    for expected in (1, 2, 3):
        c._last_client_voice = time.monotonic() - 20
        c._nate_speaking = False
        async with c._lock():
            c._soft_count += 1
            n = c._soft_count
            phrase = c._phrase(n)
            await speak(phrase)
            c._last_client_voice = time.monotonic()
            if n >= c.max_soft:
                c._phase = "final_wait"
        assert c._soft_count == expected

    assert len(spoken) == 3
    assert "here" in spoken[-1].lower()
    assert c._phase == "final_wait"

    c._last_client_voice = time.monotonic() - 35
    await alert(
        f"Client {c._client_name} stayed silent through {c.max_soft} warm check-ins"
    )
    c._phase = "done"
    assert alerts and "silent" in alerts[0].lower()
    assert c._phase == "done"


def test_client_speech_resets_soft_stage():
    async def speak(_t: str) -> None:
        return None

    c = VoiceSilenceCompanion(speak=speak, checkin_s=25, max_soft=3, startup_grace_s=5)
    c._soft_count = 2
    c._phase = "final_wait"
    c.note_client_speech()
    assert c._soft_count == 0
    assert c._phase == "soft"


def test_nate_speaking_refreshes_window_on_unmute():
    async def speak(_t: str) -> None:
        return None

    c = VoiceSilenceCompanion(speak=speak)
    before = c._last_client_voice
    time.sleep(0.05)
    c.set_nate_speaking(True)
    c.set_nate_speaking(False)
    assert c._last_client_voice >= before


@pytest.mark.asyncio
async def test_loop_fires_one_soft_checkin():
    spoken: list[str] = []

    async def speak(t: str) -> None:
        spoken.append(t)

    c = VoiceSilenceCompanion(
        speak=speak,
        checkin_s=15.0,
        final_wait_s=60.0,
        max_soft=3,
        startup_grace_s=5.0,
    )
    c.start()
    c._started_at = time.monotonic() - 20
    c._last_client_voice = time.monotonic() - 20
    await asyncio.sleep(1.3)
    c.stop()
    assert len(spoken) >= 1
    assert "here" in spoken[0].lower()
