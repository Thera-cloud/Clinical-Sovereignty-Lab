"""Quiet check-in companion for live voice calls.

# SOVEREIGN-VOICE
When a client is silent in an emotional window, Nate stays present with
soft check-ins rather than abandoning the line.

Flow (defaults):
  1–3) After ~25s client silence → warm check-in, reset timer
  4)   After 3rd check-in, wait ~60s more
  5)   Still silent → alert coach (client prolonged silence)

Client speech resets the silence clock and soft-checkin stage.
Nate speaking pauses the silence clock (does not count against client).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("nate.voice_silence_companion")

ENABLED = os.getenv("VOICE_SILENCE_COMPANION_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CHECKIN_S = float(os.getenv("VOICE_SILENCE_CHECKIN_S", "25"))
FINAL_WAIT_S = float(os.getenv("VOICE_SILENCE_FINAL_WAIT_S", "60"))
MAX_SOFT = int(os.getenv("VOICE_SILENCE_MAX_SOFT", "3"))
# Don't start silence clock until this many seconds into the call
STARTUP_GRACE_S = float(os.getenv("VOICE_SILENCE_STARTUP_GRACE_S", "15"))

SpeakFn = Callable[[str], Awaitable[None]]
AlertFn = Callable[[str], Awaitable[None]]

# Warm, short, non-clinical — stay with them in silence
_SOFT_PHRASES = (
    "I'm still here with you. Take your time.",
    "No rush at all — I'm right here whenever you're ready.",
    "I'm staying with you in this. You don't have to say anything yet. I'm here.",
)


def feature_enabled() -> bool:
    return ENABLED


class VoiceSilenceCompanion:
    """Background silence watcher for one live call."""

    def __init__(
        self,
        *,
        speak: SpeakFn,
        alert_coach: Optional[AlertFn] = None,
        client_name: str = "",
        checkin_s: float = CHECKIN_S,
        final_wait_s: float = FINAL_WAIT_S,
        max_soft: int = MAX_SOFT,
        startup_grace_s: float = STARTUP_GRACE_S,
    ):
        self._speak = speak
        self._alert_coach = alert_coach
        parts = (client_name or "").strip().split()
        self._client_name = parts[0] if parts else "there"
        self.checkin_s = max(15.0, float(checkin_s))
        self.final_wait_s = max(30.0, float(final_wait_s))
        self.max_soft = max(1, min(5, int(max_soft)))
        self.startup_grace_s = max(5.0, float(startup_grace_s))

        self._started_at = time.monotonic()
        self._last_client_voice = time.monotonic()
        self._soft_count = 0
        self._phase = "soft"  # soft | final_wait | done
        self._nate_speaking = False
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # Lazy lock — asyncio.Lock() at init fails on Py3.9 sync tests (no event loop)
        self._speaking_lock: Optional[asyncio.Lock] = None

    def _lock(self) -> asyncio.Lock:
        if self._speaking_lock is None:
            self._speaking_lock = asyncio.Lock()
        return self._speaking_lock

    def start(self) -> None:
        if not feature_enabled() or self._running:
            return
        self._running = True
        self._started_at = time.monotonic()
        self._last_client_voice = time.monotonic()
        self._task = asyncio.create_task(self._loop(), name="voice_silence_companion")
        logger.info(
            "Silence companion started (checkin=%.0fs x%d, final_wait=%.0fs)",
            self.checkin_s,
            self.max_soft,
            self.final_wait_s,
        )

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    def note_client_speech(self) -> None:
        """Client made sound / STT — reset silence clock and soft stage."""
        self._last_client_voice = time.monotonic()
        if self._phase != "done":
            self._soft_count = 0
            self._phase = "soft"

    def set_nate_speaking(self, speaking: bool) -> None:
        """Pause silence accrual while Nate's audio is playing."""
        was = self._nate_speaking
        self._nate_speaking = bool(speaking)
        if was and not speaking:
            # Fresh window after Nate finishes — don't punish client for listening
            self._last_client_voice = time.monotonic()

    def _phrase(self, soft_n: int) -> str:
        idx = min(max(soft_n - 1, 0), len(_SOFT_PHRASES) - 1)
        base = _SOFT_PHRASES[idx]
        if soft_n >= self.max_soft:
            return (
                f"{self._client_name}, I'm right here with you. "
                "No pressure to talk — I'll stay a little longer."
            )
        return base

    async def _loop(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(1.0)
                if not self._running or self._phase == "done":
                    break
                if self._nate_speaking:
                    continue
                if (time.monotonic() - self._started_at) < self.startup_grace_s:
                    continue
                silent_for = time.monotonic() - self._last_client_voice

                if self._phase == "soft":
                    if silent_for < self.checkin_s:
                        continue
                    async with self._lock():
                        if self._nate_speaking:
                            continue
                        self._soft_count += 1
                        n = self._soft_count
                        phrase = self._phrase(n)
                        print(
                            f"[VOICE-SILENCE] soft check-in #{n}/{self.max_soft} "
                            f"after {silent_for:.0f}s silence"
                        )
                        try:
                            await self._speak(phrase)
                        except Exception as e:
                            logger.warning("silence check-in speak failed: %s", e)
                        self._last_client_voice = time.monotonic()
                        if n >= self.max_soft:
                            self._phase = "final_wait"
                            print(
                                f"[VOICE-SILENCE] entering final wait "
                                f"({self.final_wait_s:.0f}s) before coach alert"
                            )

                elif self._phase == "final_wait":
                    if silent_for < self.final_wait_s:
                        continue
                    print(
                        f"[VOICE-SILENCE] prolonged silence "
                        f"({silent_for:.0f}s after final check-in) — coach alert"
                    )
                    if self._alert_coach:
                        try:
                            await self._alert_coach(
                                f"Client {self._client_name} stayed silent through "
                                f"{self.max_soft} warm check-ins "
                                f"(~{int(self.checkin_s * self.max_soft + self.final_wait_s)}s). "
                                "Please check in with them."
                            )
                        except Exception as e:
                            logger.warning("silence coach alert failed: %s", e)
                    self._phase = "done"
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning("silence companion loop error: %s", e)


async def _default_alert_coach(ctx: dict, client_name: str, msg: str) -> None:
    """Route prolonged-silence alert to coach (check-in task or assigned coach)."""
    db = ctx.get("db_pool")
    tid = ctx.get("coach_checkin_task_id")
    coach = (ctx.get("coach_username") or "").strip()
    if tid and db:
        try:
            from app.services.coach_nate_checkin_service import CoachNateCheckinService

            svc = CoachNateCheckinService(db, ctx.get("app_state"))
            task = await svc.get_task(int(tid))
            if task:
                coach = (task.get("coach_username") or coach).strip()
                await svc._notify_coach(coach, int(tid), "prolonged_silence", msg)
                return
        except Exception as e:
            logger.warning("silence alert via check-in task failed: %s", e)
    if not coach:
        coach = (
            (ctx.get("profile") or {}).get("assigned_coach")
            or (ctx.get("profile") or {}).get("coach_username")
            or ""
        ).strip()
    if coach and db:
        try:
            from app.services.coach_notifications import notify_coach

            await notify_coach(
                db,
                coach,
                {
                    "urgency": "high",
                    "subject": "Nate: client silent on call",
                    "message": msg,
                    "payload": {
                        "source": "voice_silence_companion",
                        "client": client_name,
                    },
                },
            )
        except Exception as e:
            logger.warning("silence alert via notify_coach failed: %s", e)


def attach_silence_companion(
    ctx: dict,
    speak: SpeakFn,
    *,
    client_name: str = "",
) -> Optional["VoiceSilenceCompanion"]:
    """Factory used by the voice pipeline (keeps protected file under line budget)."""
    if not feature_enabled():
        return None
    name = client_name or ctx.get("name") or ctx.get("username") or ""

    async def _alert(msg: str) -> None:
        await _default_alert_coach(ctx, name, msg)

    companion = VoiceSilenceCompanion(
        speak=speak,
        alert_coach=_alert,
        client_name=name,
    )
    companion.start()
    return companion
