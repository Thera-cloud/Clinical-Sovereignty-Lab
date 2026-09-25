"""Show voice floor — one warm Rex session, short instruction, tools. QUANTUM-CRYSTAL-ARCH

Mirrors Grok Voice Think Fast constraints for the podcast without handing the
co-host brain to the voice model. Host and caller turns stay in our text path
(goal, public depth, on-air guard). This session only speaks the guarded line,
with reasoning off, and can call the same three tools if the model asks.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("studio_voice_floor")

VOICE_MODEL = os.getenv("STUDIO_VOICE_MODEL", "grok-voice-latest")
SMART_TURN_MS = 700
_IDLE_S = 600.0
_MOUTHS: Dict[str, "StudioVoiceMouth"] = {}
_LOCK = asyncio.Lock()

SHORT_INSTRUCTION = (
    "You are Little Nate on a live show. Speak the line you are given, verbatim, "
    "in a warm conversational voice. No extra words. If you need the working goal, "
    "public notes, or a fact the host asked for, call a tool first. "
    "Never name a person. Never mention a child or an age. "
    "A caller does not get a web lookup."
)

TOOLS = [
    {
        "type": "function",
        "name": "show_floor",
        "description": "Working goal, speaker, and constraints already on this show.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "onair_notes",
        "description": "Public de-identified notes for this question. No names, children, or ages.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "type": "function",
        "name": "host_lookup",
        "description": "Look up a fact the host asked. Refuse when the speaker is a caller.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "speaker": {"type": "string"},
            },
            "required": ["query"],
        },
    },
]


def voice_realtime_url() -> str:
    base = os.getenv("XAI_REALTIME_URL", "wss://api.x.ai/v1/realtime").split("?")[0]
    return f"{base}?model={VOICE_MODEL}"


def session_update_payload(voice: str) -> dict:
    return {
        "type": "session.update",
        "session": {
            "instructions": SHORT_INSTRUCTION,
            "voice": voice,
            "reasoning": {"effort": "none"},
            "tools": TOOLS,
            "turn_detection": {
                "type": "server_vad",
                "silence_duration_ms": SMART_TURN_MS,
                "threshold": 0.5,
                "prefix_padding_ms": 300,
            },
            "audio": {
                "input": {"format": {"type": "audio/pcmu"}},
                "output": {"format": {"type": "audio/pcmu"}},
            },
        },
    }


async def run_voice_tool(name: str, args: dict, session_id: str = "", db_pool=None) -> str:
    """Same three tools the voice model can call. Results stay short and scrubbed."""
    from app.services.studio_public_depth import guard_onair

    tool = (name or "").strip()
    payload = args if isinstance(args, dict) else {}
    if tool == "show_floor":
        from app.services.studio_show_thread import read_show

        state = read_show(session_id)
        cons = "; ".join(state.get("constraints") or []) or "none"
        text = (
            f"Speaker: {state.get('who') or 'host'}. "
            f"Goal: {state.get('goal') or 'not set'}. "
            f"Constraints: {cons}."
        )
        return guard_onair(text)[:500]
    if tool == "onair_notes":
        from app.services.studio_public_depth import depth_for_show

        notes = await depth_for_show(db_pool, str(payload.get("query") or ""))
        return guard_onair(notes or "No public note on that.")[:700]
    if tool == "host_lookup":
        from app.services.studio_show_thread import fresh_notes

        speaker = str(payload.get("speaker") or "host")
        query = str(payload.get("query") or "")
        if speaker.lower().startswith("caller"):
            return "No lookup for a caller."
        rows = await fresh_notes(query)
        if not rows:
            return "Nothing fresh came back."
        bits = [f"{r.get('title')}: {r.get('snippet')}" for r in rows[:3]]
        return guard_onair(" ".join(bits))[:700]
    return "Unknown tool."


class StudioVoiceMouth:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.ws = None
        self.lock = asyncio.Lock()
        self.touched = time.monotonic()

    async def close(self) -> None:
        ws = self.ws
        self.ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass

    async def _open(self):
        from app.services.studio_phone_voice import _ws_connect

        key = (os.getenv("XAI_API_KEY") or "").strip()
        if not key:
            return None
        voice = (os.getenv("GROK_VOICE") or "Rex").strip() or "Rex"
        ws = await asyncio.wait_for(
            _ws_connect(voice_realtime_url(), {"Authorization": f"Bearer {key}"}),
            timeout=12.0,
        )
        await ws.send(json.dumps(session_update_payload(voice)))
        self.ws = ws
        self.touched = time.monotonic()
        return ws

    async def speak(self, text: str) -> Optional[bytes]:
        line = (text or "").strip()
        if not line:
            return None
        if os.getenv("GROK_NATIVE_VOICE", "").lower() not in ("1", "true", "yes"):
            return None
        async with self.lock:
            try:
                ws = self.ws
                if ws is None:
                    ws = await self._open()
                if ws is None:
                    return None
                wav = await self._speak_on(ws, line)
                if wav:
                    self.touched = time.monotonic()
                    return wav
                await self.close()
                return None
            except Exception as exc:
                logger.warning("studio voice floor skipped: %s", exc)
                await self.close()
                return None

    async def _speak_on(self, ws, line: str) -> Optional[bytes]:
        from app.services.studio_phone_voice import _mulaw_to_wav

        await ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": line}],
                    },
                }
            )
        )
        await ws.send(
            json.dumps({"type": "response.create", "response": {"modalities": ["audio"]}})
        )
        chunks: list[bytes] = []
        deadline = asyncio.get_event_loop().time() + 45.0
        while asyncio.get_event_loop().time() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=16.0)
            ev = json.loads(raw)
            et = ev.get("type") or ""
            if et == "error":
                logger.warning("studio voice floor error: %s", ev.get("error"))
                return None
            if et in ("response.output_audio.delta", "response.audio.delta"):
                payload = ev.get("delta") or ev.get("audio") or ""
                if payload:
                    chunks.append(base64.b64decode(payload))
            if et in ("response.function_call_arguments.done", "response.output_item.done"):
                spoken = await self._maybe_tool(ws, ev)
                if spoken:
                    return spoken
            if et in ("response.output_audio.done", "response.audio.done", "response.done"):
                if chunks or et == "response.done":
                    break
        if not chunks:
            return None
        return _mulaw_to_wav(b"".join(chunks))

    async def _maybe_tool(self, ws, ev: dict) -> Optional[bytes]:
        item = ev.get("item") or ev
        name = item.get("name") or ev.get("name") or ""
        if not name:
            return None
        raw_args = item.get("arguments") or ev.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except Exception:
            args = {}
        result = await run_voice_tool(name, args if isinstance(args, dict) else {}, self.session_id)
        call_id = item.get("call_id") or ev.get("call_id") or ""
        await ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": result,
                    },
                }
            )
        )
        await ws.send(
            json.dumps({"type": "response.create", "response": {"modalities": ["audio"]}})
        )
        return None


async def mouth_for(session_id: str) -> StudioVoiceMouth:
    sid = (session_id or "").strip() or "_show"
    async with _LOCK:
        mouth = _MOUTHS.get(sid)
        if mouth is None:
            mouth = StudioVoiceMouth(sid)
            _MOUTHS[sid] = mouth
        return mouth


async def speak_guarded(session_id: str, text: str) -> Optional[bytes]:
    mouth = await mouth_for(session_id)
    return await mouth.speak(text)


async def close_mouth(session_id: str) -> None:
    sid = (session_id or "").strip()
    async with _LOCK:
        mouth = _MOUTHS.pop(sid, None)
    if mouth is not None:
        await mouth.close()


def drop_idle_mouths(now: Optional[float] = None) -> int:
    stamp = now if now is not None else time.monotonic()
    stale = [sid for sid, mouth in _MOUTHS.items() if stamp - mouth.touched > _IDLE_S]
    for sid in stale:
        _MOUTHS.pop(sid, None)
    return len(stale)
