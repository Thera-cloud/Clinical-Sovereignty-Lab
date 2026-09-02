"""STUDIO co-host TTS — same voice as the phone call (Grok Rex, Azure Onyx fallback)."""

from __future__ import annotations

import audioop
import asyncio
import base64
import json
import logging
import os
import struct
from typing import Optional

logger = logging.getLogger("studio_phone_voice")

XAI_REALTIME_URL = os.getenv("XAI_REALTIME_URL", "wss://api.x.ai/v1/realtime")


def studio_audio_media_type(audio: bytes) -> str:
    if audio[:4] == b"RIFF":
        return "audio/wav"
    if audio[:3] == b"ID3" or (len(audio) > 1 and audio[0] == 0xFF):
        return "audio/mpeg"
    return "audio/wav"


def _wav_pcm16(pcm: bytes, rate: int) -> bytes:
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        rate,
        rate * 2,
        2,
        16,
        b"data",
        len(pcm),
    )
    return header + pcm


def _mulaw_to_wav(mulaw: bytes) -> bytes:
    return _wav_pcm16(audioop.ulaw2lin(mulaw, 2), 8000)


async def _ws_connect(url: str, headers: dict):
    import websockets

    try:
        return await websockets.connect(
            url, additional_headers=headers, max_size=None, open_timeout=12
        )
    except TypeError:
        return await websockets.connect(url, extra_headers=headers, max_size=None)


async def synthesize_rex_wav(text: str) -> Optional[bytes]:
    """One-shot Grok Rex via xAI Realtime — same voice as GROK_NATIVE_VOICE phone calls."""
    if os.getenv("GROK_NATIVE_VOICE", "").lower() not in ("1", "true", "yes"):
        return None
    key = (os.getenv("XAI_API_KEY") or "").strip()
    if not key:
        logger.warning("studio Rex skipped: XAI_API_KEY unset")
        return None
    voice = (os.getenv("GROK_VOICE") or "Rex").strip() or "Rex"
    line = (text or "").strip()
    if not line:
        return None
    chunks: list[bytes] = []
    ws = None
    try:
        ws = await asyncio.wait_for(
            _ws_connect(
                XAI_REALTIME_URL,
                {"Authorization": f"Bearer {key}"},
            ),
            timeout=12.0,
        )
        await ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "instructions": (
                            "You are a text-to-speech voice. Read the user's message "
                            "verbatim in your normal speaking voice. No extra words."
                        ),
                        "voice": voice,
                        "turn_detection": {
                            "type": "server_vad",
                            "silence_duration_ms": 700,
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                        },
                        "audio": {
                            "input": {"format": {"type": "audio/pcmu"}},
                            "output": {"format": {"type": "audio/pcmu"}},
                        },
                    },
                }
            )
        )
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
            json.dumps(
                {"type": "response.create", "response": {"modalities": ["audio"]}}
            )
        )
        deadline = asyncio.get_event_loop().time() + 28.0
        while asyncio.get_event_loop().time() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=12.0)
            ev = json.loads(raw)
            et = ev.get("type") or ""
            if et == "error":
                logger.warning("studio Rex error: %s", ev.get("error"))
                break
            if et in (
                "response.output_audio.delta",
                "response.audio.delta",
            ):
                payload = ev.get("delta") or ev.get("audio") or ""
                if payload:
                    chunks.append(base64.b64decode(payload))
            if et in ("response.output_audio.done", "response.audio.done", "response.done"):
                if chunks or et == "response.done":
                    break
        if not chunks:
            return None
        wav = _mulaw_to_wav(b"".join(chunks))
        logger.info("studio Rex: %d chunks → %d bytes wav", len(chunks), len(wav))
        return wav
    except Exception as exc:
        logger.warning("studio Rex skipped: %s", exc)
        return None
    finally:
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass


async def synthesize_onyx_wav(text: str) -> Optional[bytes]:
    """Phone-call Azure Onyx path (preview API + warm instructions). Not Edge GuyNeural."""
    import httpx

    endpoint = (os.environ.get("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
    api_key = os.environ.get("AZURE_API_KEY", "")
    deployment = os.environ.get("AZURE_OPENAI_MINI_TTS_DEPLOYMENT", "gpt-4o-mini-tts")
    if not endpoint or not api_key:
        return None
    url = (
        f"https://{endpoint}/openai/deployments/{deployment}"
        f"/audio/speech?api-version=2025-04-01-preview"
    )
    payload = {
        "model": deployment,
        "input": text,
        "voice": "onyx",
        "response_format": "wav",
        "speed": 1.05,
        "instructions": (
            "Speak as a warm, confident young man in his late 20s. "
            "Natural and conversational — like talking to a trusted older brother. "
            "Relaxed pace, occasional light laugh energy. Never robotic or clinical."
        ),
    }
    try:
        async with httpx.AsyncClient(timeout=24.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"api-key": api_key, "Content-Type": "application/json"},
            )
        if resp.status_code == 200 and len(resp.content) > 100:
            logger.info("studio Onyx: %d bytes wav", len(resp.content))
            return resp.content
        logger.warning("studio Onyx HTTP %s: %s", resp.status_code, resp.text[:160])
    except Exception as exc:
        logger.warning("studio Onyx skipped: %s", exc)
    return None


async def synthesize_studio_voice(text: str) -> bytes:
    line = (text or "").strip()
    if not line:
        return b""
    rex = await synthesize_rex_wav(line)
    if rex:
        return rex
    onyx = await synthesize_onyx_wav(line)
    return onyx or b""
