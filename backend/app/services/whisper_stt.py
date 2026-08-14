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
import time
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

# QUANTUM-CRYSTAL-ARCH — serialize Whisper to avoid S0 429 storms (LN-Observer)
_STT_LOCK = asyncio.Lock()
_STT_MIN_INTERVAL_S = float(os.getenv("WHISPER_MIN_INTERVAL_S", "1.25"))
_STT_LAST_AT = 0.0
_STT_MAX_RETRIES = int(os.getenv("WHISPER_MAX_RETRIES", "3"))


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
        "video/mp4": "video.mp4",
        "video/quicktime": "video.mov",
        "video/webm": "video.webm",
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

    global _STT_LAST_AT
    async with _STT_LOCK:
        # Pace calls so Observer chunk storms don't 429 the S0 tier
        gap = time.monotonic() - _STT_LAST_AT
        if gap < _STT_MIN_INTERVAL_S:
            await asyncio.sleep(_STT_MIN_INTERVAL_S - gap)

        last_err = ""
        for attempt in range(_STT_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(
                        _transcription_url(),
                        headers=headers,
                        files=form_data,
                    )
                _STT_LAST_AT = time.monotonic()

                if resp.status_code == 200:
                    text = resp.text.strip()
                    if text:
                        _logger.debug(
                            "Whisper STT: %d bytes → %d chars",
                            len(audio_data), len(text),
                        )
                        return text
                    return None

                last_err = f"HTTP {resp.status_code} — {resp.text[:200]}"
                if resp.status_code == 429 and attempt + 1 < _STT_MAX_RETRIES:
                    # Retry-After header or exponential backoff
                    ra = resp.headers.get("Retry-After")
                    try:
                        wait_s = float(ra) if ra else (1.5 * (2 ** attempt))
                    except ValueError:
                        wait_s = 1.5 * (2 ** attempt)
                    wait_s = min(max(wait_s, 1.0), 20.0)
                    _logger.warning(
                        "Whisper STT 429 — backoff %.1fs (attempt %d/%d)",
                        wait_s, attempt + 1, _STT_MAX_RETRIES,
                    )
                    await asyncio.sleep(wait_s)
                    continue

                _logger.warning("Whisper STT failed: %s", last_err)
                return None

            except httpx.TimeoutException:
                _logger.warning(
                    "Whisper STT timeout for %d bytes of audio", len(audio_data)
                )
                return None
            except Exception as e:
                _logger.warning("Whisper STT error: %s", e)
                return None

        _logger.warning("Whisper STT exhausted retries: %s", last_err)
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
