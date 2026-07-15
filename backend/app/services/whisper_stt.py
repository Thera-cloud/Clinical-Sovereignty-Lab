"""
Azure Whisper STT — speech-to-text via the nate-whisper deployment.

Uses the Azure OpenAI Whisper API (not the Realtime WebSocket) for
cost-effective transcription. This is the cheap voice path for
Threshold and Inner Chamber tiers.

Cost: ~$0.006 per minute of audio (vs Realtime at ~$0.06/min).
"""

import asyncio
import io
import logging
import os
from typing import Optional

import httpx

_logger = logging.getLogger("whisper_stt")

_AZURE_ENDPOINT = os.getenv(
    "AZURE_WHISPER_ENDPOINT",
    os.getenv("AZURE_OPENAI_ENDPOINT", ""),
).rstrip("/")

_AZURE_KEY = os.getenv(
    "AZURE_WHISPER_KEY",
    os.getenv("AZURE_API_KEY", ""),
)

_DEPLOYMENT = os.getenv("AZURE_WHISPER_DEPLOYMENT", "nate-whisper")
_API_VERSION = os.getenv("AZURE_WHISPER_API_VERSION", "2024-06-01")


def is_whisper_configured() -> bool:
    return bool(_AZURE_ENDPOINT and _AZURE_KEY and _DEPLOYMENT)


def _transcription_url() -> str:
    return (
        f"{_AZURE_ENDPOINT}/openai/deployments/{_DEPLOYMENT}"
        f"/audio/transcriptions?api-version={_API_VERSION}"
    )


async def transcribe(
    audio_data: bytes,
    *,
    language: str = "en",
    content_type: str = "audio/webm",
    prompt: Optional[str] = None,
) -> Optional[str]:
    """
    Transcribe audio bytes to text via Azure Whisper.

    Accepts any format Whisper supports: webm, mp3, mp4, wav, ogg, flac.
    Returns the transcribed text, or None on failure.
    """
    if not is_whisper_configured():
        _logger.warning("Whisper STT not configured — missing endpoint/key/deployment")
        return None

    if not audio_data or len(audio_data) < 100:
        return None

    ext_map = {
        "audio/webm": "audio.webm",
        "audio/wav": "audio.wav",
        "audio/mp3": "audio.mp3",
        "audio/ogg": "audio.ogg",
        "audio/flac": "audio.flac",
        "audio/mp4": "audio.mp4",
        "audio/mpeg": "audio.mp3",
    }
    filename = ext_map.get(content_type, "audio.webm")

    form_data = {
        "file": (filename, io.BytesIO(audio_data), content_type),
        "language": (None, language),
        "response_format": (None, "text"),
    }
    if prompt:
        form_data["prompt"] = (None, prompt)

    headers = {"api-key": _AZURE_KEY}

    try:
        # Chunked long-form STT may send 30–90s of audio; allow up to 2 minutes.
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                _transcription_url(),
                headers=headers,
                files=form_data,
            )

        if resp.status_code == 200:
            text = resp.text.strip()
            if text:
                _logger.debug("Whisper STT: %d bytes → %d chars", len(audio_data), len(text))
                return text
            return None

        _logger.warning(
            "Whisper STT failed: HTTP %d — %s",
            resp.status_code, resp.text[:200],
        )
        return None

    except httpx.TimeoutException:
        _logger.warning("Whisper STT timeout for %d bytes of audio", len(audio_data))
        return None
    except Exception as e:
        _logger.warning("Whisper STT error: %s", e)
        return None


async def transcribe_chunked(
    audio_data: bytes,
    *,
    chunk_seconds: int = 30,
    sample_rate: int = 16000,
    language: str = "en",
    content_type: str = "audio/wav",
) -> Optional[str]:
    """
    Transcribe longer audio by splitting into chunks and concatenating results.
    For audio under 30s, delegates directly to transcribe().
    """
    estimated_bytes_per_second = sample_rate * 2
    chunk_size = chunk_seconds * estimated_bytes_per_second

    if len(audio_data) <= chunk_size:
        return await transcribe(audio_data, language=language, content_type=content_type)

    chunks = []
    offset = 0
    while offset < len(audio_data):
        chunks.append(audio_data[offset:offset + chunk_size])
        offset += chunk_size

    tasks = [
        transcribe(chunk, language=language, content_type=content_type)
        for chunk in chunks
    ]
    results = await asyncio.gather(*tasks)

    texts = [r for r in results if r]
    return " ".join(texts) if texts else None
