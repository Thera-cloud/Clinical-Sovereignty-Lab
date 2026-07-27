"""
Voice call sync — identity, emotion pacing, avatar expression broadcast.

Flag-gated orchestration for live phone calls. Keeps twilio_grok_xtts_pipeline
hooks thin (QUANTUM-CRYSTAL-ARCH / SOVEREIGN-VOICE).

Env:
  ENABLE_VOICE_IDENTITY=true     — LiveDiarization + gentle identity ask
  ENABLE_VOICE_AVATAR_SYNC=true  — Redis publish avatar expressions for app link
  ENABLE_VOICE_EMOTION_PACE=true — adaptive VAD silence from speech energy
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.voice_call_sync")

REDIS_CHANNEL = "nate:voice_avatar"

_IDENTITY = os.getenv("ENABLE_VOICE_IDENTITY", "false").lower() in ("1", "true", "yes")
_AVATAR = os.getenv("ENABLE_VOICE_AVATAR_SYNC", "false").lower() in ("1", "true", "yes")
_PACE = os.getenv("ENABLE_VOICE_EMOTION_PACE", "false").lower() in ("1", "true", "yes")

# 4 seconds of 8 kHz mono int16 PCM
_GREETING_BYTES = 8000 * 2 * 4


def voice_sync_enabled() -> bool:
    return _IDENTITY or _AVATAR or _PACE


IDENTITY_PROMPT_ADDON = """
VOICE IDENTITY & SAFE SPACE (ALWAYS FOLLOW):
- If you are unsure who is speaking, ask gently once: "I want to make sure I'm with the right person — may I ask your name?" Never interrogate.
- If they prefer not to share a name, thank them warmly and continue. Never pressure. This is a safe space.
- If more than one person seems to be on the line, note that kindly and ask who is speaking when it matters for care.
- Use any remembered name naturally; do not invent a name you were not given.
"""


class VoiceCallSyncSession:
    """Per-call session: diarization, pacing, avatar pub/sub."""

    def __init__(
        self,
        call_sid: str,
        username: Optional[str],
        db_pool=None,
        redis=None,
        guest_mode: bool = False,
    ):
        self.call_sid = call_sid or ""
        self.username = username or ""
        self.db_pool = db_pool
        self.redis = redis
        self.guest_mode = guest_mode
        self._diarization = None
        self._avatar_handler = None
        self._energy_samples: List[float] = []
        self._silence_ms = 700
        self._last_pace_adjust = 0.0
        self._turns = 0
        self._investigation_injected = False
        self._greeting_buf = bytearray()
        self._greeting_done = False
        self._pace_dirty = False

    async def start(self) -> None:
        if _IDENTITY and self.username:
            try:
                from app.services.live_diarization import LiveDiarizationSession

                self._diarization = LiveDiarizationSession(
                    call_sid=self.call_sid,
                    expected_user=self.username if not self.guest_mode else None,
                    db_pool=self.db_pool,
                )
            except Exception as e:
                logger.warning("VoiceCallSync: diarization init failed: %s", e)
        if _AVATAR:
            try:
                from pathlib import Path
                from app.websocket.avatar_handlers import create_avatar_handler

                root = Path(os.getenv("DATA_DIR", "/app/data"))
                self._avatar_handler = create_avatar_handler(root)
            except Exception as e:
                logger.warning("VoiceCallSync: avatar handler init failed: %s", e)

    def prompt_addon(self) -> str:
        parts = [IDENTITY_PROMPT_ADDON]
        if self.guest_mode:
            parts.append(
                "GUEST CALLER: You do not have a confirmed identity. "
                "Offer a warm welcome. Invite (do not demand) a name. "
                "If they decline, continue supportively without a name."
            )
        return "\n".join(parts)

    def silence_ms(self) -> int:
        return int(max(500, min(1500, self._silence_ms)))

    def feed_audio(self, pcm_chunk: bytes) -> None:
        if not pcm_chunk:
            return
        if self._diarization and _IDENTITY:
            try:
                self._diarization.process_audio_chunk(pcm_chunk)
                if not self._greeting_done:
                    self._greeting_buf.extend(pcm_chunk)
            except Exception as e:
                logger.debug("VoiceCallSync feed_audio diarization: %s", e)
        if _PACE:
            try:
                n = min(len(pcm_chunk), 320)
                energy = sum(abs(b - 128) for b in pcm_chunk[:n]) / max(n, 1)
                self._energy_samples.append(float(energy))
                if len(self._energy_samples) > 80:
                    self._energy_samples = self._energy_samples[-80:]
                self._maybe_adjust_pace()
            except Exception:
                pass

    async def maybe_greeting(self) -> None:
        if self._greeting_done or not self._diarization or not _IDENTITY:
            return
        if len(self._greeting_buf) < _GREETING_BYTES:
            return
        self._greeting_done = True
        try:
            await self._diarization.process_greeting(bytes(self._greeting_buf[:_GREETING_BYTES]))
        except Exception as e:
            logger.debug("VoiceCallSync greeting: %s", e)
        finally:
            self._greeting_buf.clear()

    def _maybe_adjust_pace(self) -> None:
        now = time.monotonic()
        if now - self._last_pace_adjust < 8.0 or len(self._energy_samples) < 20:
            return
        self._last_pace_adjust = now
        avg = sum(self._energy_samples) / len(self._energy_samples)
        prev = self._silence_ms
        if avg > 40:
            self._silence_ms = 550
        elif avg < 15:
            self._silence_ms = 1100
        else:
            self._silence_ms = 700
        if self._silence_ms != prev:
            self._pace_dirty = True

    async def on_user_text(self, text: str) -> Optional[str]:
        """Return optional investigation prompt to inject into Grok context."""
        self._turns += 1
        await self.maybe_greeting()
        if not text:
            return None
        if self._diarization and _IDENTITY:
            try:
                self._diarization.process_transcript(text, speaker="caller")
                if self._turns % 3 == 0:
                    await self._diarization.update_identity()
                overlay = self._diarization.get_system_prompt_overlay()
                if overlay and not self._investigation_injected:
                    self._investigation_injected = True
                    return overlay
            except Exception as e:
                logger.debug("VoiceCallSync on_user_text: %s", e)
        if self.guest_mode and self._turns == 1 and not self._investigation_injected:
            self._investigation_injected = True
            return (
                "Warmly invite their name once if natural. "
                "If they prefer not to share, thank them and continue as a safe space."
            )
        return None

    async def on_nate_text(self, nate_text: str, user_text: str = "") -> Optional[Dict[str, Any]]:
        if not nate_text or not _AVATAR or not self._avatar_handler:
            return None
        try:
            state = self._avatar_handler._determine_avatar_state(nate_text, user_text or "")
            state = dict(state)
            state["speaking"] = True
            state["source"] = "voice_call"
            state["call_sid"] = self.call_sid
            await self._publish_avatar(state)
            return state
        except Exception as e:
            logger.debug("VoiceCallSync on_nate_text: %s", e)
            return None

    async def on_nate_done(self) -> None:
        if not _AVATAR:
            return
        try:
            await self._publish_avatar(
                {
                    "expression": "ATTENTIVE",
                    "gesture": "NONE",
                    "body_position": "ATTENTIVE_LEAN",
                    "speaking": False,
                    "source": "voice_call",
                    "call_sid": self.call_sid,
                }
            )
        except Exception:
            pass

    async def _resolve_hw_id(self) -> str:
        if not self.db_pool or not self.username:
            return ""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT hardware_id FROM users WHERE username = $1 LIMIT 1",
                    self.username,
                )
                return (row["hardware_id"] if row else "") or ""
        except Exception:
            return ""

    async def _publish_avatar(self, avatar_state: Dict[str, Any]) -> None:
        if not self.redis or not self.username:
            return
        hw = await self._resolve_hw_id()
        payload = json.dumps(
            {
                "type": "voice_avatar_expression",
                "username": self.username,
                "hardware_id": hw,
                "avatar_state": avatar_state,
                "ts": time.time(),
            }
        )
        try:
            publish = getattr(self.redis, "publish", None)
            if publish is None:
                return
            result = publish(REDIS_CHANNEL, payload)
            if hasattr(result, "__await__"):
                await result
        except Exception as e:
            logger.debug("VoiceCallSync redis publish failed: %s", e)

    def take_pace_update(self) -> Optional[Dict[str, Any]]:
        if not _PACE or not self._pace_dirty:
            return None
        self._pace_dirty = False
        return {
            "type": "session.update",
            "session": {
                "turn_detection": {
                    "type": "server_vad",
                    "silence_duration_ms": self.silence_ms(),
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                }
            },
        }

    async def apply_user_turn(self, grok_ws, user_txt: str) -> None:
        """Inject identity note + pace update into live Grok session."""
        if not grok_ws:
            return
        try:
            inv = await self.on_user_text(user_txt or "")
            if inv:
                await grok_ws.send(json.dumps({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{
                            "type": "input_text",
                            "text": f"[SYSTEM NOTE — do not read aloud]\n{inv}",
                        }],
                    },
                }))
            pace = self.take_pace_update()
            if pace:
                await grok_ws.send(json.dumps(pace))
        except Exception as e:
            logger.debug("apply_user_turn: %s", e)

    async def finalize(self) -> None:
        if self._diarization:
            try:
                await self._diarization.finalize()
            except Exception as e:
                logger.warning("VoiceCallSync finalize diarization: %s", e)
        await self.on_nate_done()


async def attach_voice_sync(ctx: dict, call_sid: str, username: str, instructions: str):
    """One-call hook for pipeline start. Returns (session|None, instructions)."""
    if not voice_sync_enabled() or not username:
        return None, instructions
    try:
        if not ctx.get("redis"):
            from app.services.api_server import _get_auth_redis
            ctx["redis"] = await _get_auth_redis()
        sess = VoiceCallSyncSession(
            call_sid=call_sid or "",
            username=username,
            db_pool=ctx.get("db_pool"),
            redis=ctx.get("redis"),
            guest_mode=str(ctx.get("guest_mode", "")).lower() in ("1", "true", "yes"),
        )
        await sess.start()
        return sess, instructions + "\n\n" + sess.prompt_addon()
    except Exception as e:
        logger.warning("attach_voice_sync failed: %s", e)
        return None, instructions
