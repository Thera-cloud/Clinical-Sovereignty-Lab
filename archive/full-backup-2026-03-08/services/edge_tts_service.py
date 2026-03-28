"""
Edge TTS — free text-to-speech via Microsoft Edge's Read Aloud service.

Zero API cost. No API key required. Uses the `edge-tts` Python package
which communicates with Microsoft's public TTS endpoint (the same one
powering Edge browser's Read Aloud feature).

This is the cheap voice path for Threshold and Inner Chamber tiers.
Sovereign Circle uses Azure OpenAI gpt-4o-mini-tts (premium quality).
"""

import asyncio
import io
import logging
import os
from typing import Optional

_logger = logging.getLogger("edge_tts_service")

DEFAULT_VOICE = os.getenv("EDGE_TTS_VOICE", "en-US-GuyNeural")

VOICE_MAP = {
    "nate_warm": "en-US-GuyNeural",
    "nate_calm": "en-US-ChristopherNeural",
    "nate_empathic": "en-US-DavisNeural",
    "nate_female": "en-US-JennyNeural",
    "nate_british": "en-GB-RyanNeural",
}


def _get_voice(voice_id: Optional[str] = None) -> str:
    if voice_id and voice_id in VOICE_MAP:
        return VOICE_MAP[voice_id]
    return DEFAULT_VOICE


async def synthesize(
    text: str,
    *,
    voice: Optional[str] = None,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> Optional[bytes]:
    """
    Convert text to speech audio (MP3 bytes) using Microsoft Edge TTS.

    Args:
        text: The text to speak.
        voice: Voice ID from VOICE_MAP or a raw Edge voice name.
        rate: Speech rate adjustment (e.g., "+10%", "-5%").
        pitch: Pitch adjustment (e.g., "+2Hz", "-1Hz").

    Returns:
        MP3 audio bytes, or None if synthesis fails.
    """
    if not text or not text.strip():
        return None

    try:
        import edge_tts
    except ImportError:
        _logger.warning("edge-tts not installed — run: pip install edge-tts")
        return None

    voice_name = _get_voice(voice)

    try:
        communicate = edge_tts.Communicate(
            text=text.strip(),
            voice=voice_name,
            rate=rate,
            pitch=pitch,
        )

        audio_buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])

        audio_data = audio_buffer.getvalue()
        if not audio_data:
            _logger.warning("Edge TTS returned empty audio for %d chars", len(text))
            return None

        _logger.debug(
            "Edge TTS: %d chars → %d bytes (voice=%s)",
            len(text), len(audio_data), voice_name,
        )
        return audio_data

    except Exception as e:
        _logger.warning("Edge TTS synthesis failed: %s", e)
        return None


async def synthesize_streaming(
    text: str,
    *,
    voice: Optional[str] = None,
    rate: str = "+0%",
    pitch: str = "+0Hz",
):
    """
    Async generator that yields audio chunks as they're produced.
    Enables streaming playback — the client can start playing before
    the full synthesis is complete.

    Yields:
        (chunk_type, data) tuples where chunk_type is "audio" or "boundary".
    """
    if not text or not text.strip():
        return

    try:
        import edge_tts
    except ImportError:
        _logger.warning("edge-tts not installed — run: pip install edge-tts")
        return

    voice_name = _get_voice(voice)

    try:
        communicate = edge_tts.Communicate(
            text=text.strip(),
            voice=voice_name,
            rate=rate,
            pitch=pitch,
        )

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield "audio", chunk["data"]
            elif chunk["type"] == "WordBoundary":
                yield "boundary", {
                    "offset": chunk.get("offset"),
                    "duration": chunk.get("duration"),
                    "text": chunk.get("text", ""),
                }

    except Exception as e:
        _logger.warning("Edge TTS streaming failed: %s", e)


async def list_voices(language: str = "en") -> list:
    """List available Edge TTS voices for a language prefix."""
    try:
        import edge_tts
        voices = await edge_tts.list_voices()
        return [
            {"name": v["Name"], "gender": v.get("Gender", ""), "locale": v.get("Locale", "")}
            for v in voices
            if v.get("Locale", "").startswith(language)
        ]
    except ImportError:
        return []
    except Exception as e:
        _logger.warning("Edge TTS list_voices failed: %s", e)
        return []
