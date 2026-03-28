"""
Sovereign Whisper — Phase 7.4 of Sovereign Quantum Nate Build.

Self-hosted speech-to-text using faster-whisper, with Azure Whisper fallback.
Eliminates dependency on external STT for standard transcription.
"""

import asyncio
import io
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
_model = None
_model_loaded = False


def _ensure_model():
    """Lazy-load the whisper model on first use."""
    global _model, _model_loaded
    if _model_loaded:
        return _model

    try:
        from faster_whisper import WhisperModel
        _model = WhisperModel(
            _MODEL_SIZE,
            device=_DEVICE,
            compute_type=_COMPUTE_TYPE,
        )
        _model_loaded = True
        logger.info("Sovereign Whisper loaded: model=%s device=%s", _MODEL_SIZE, _DEVICE)
    except ImportError:
        logger.warning("faster-whisper not installed — sovereign STT unavailable")
        _model_loaded = True
    except Exception as e:
        logger.warning("Whisper model load failed: %s", e)
        _model_loaded = True

    return _model


async def transcribe(
    audio_data: bytes,
    language: Optional[str] = None,
    task: str = "transcribe",
) -> Dict[str, Any]:
    """
    Transcribe audio using sovereign Whisper, falling back to Azure if unavailable.
    Returns {"text": str, "provider": str, "language": str, "latency_ms": int}
    """
    start = time.time()

    # Try sovereign first
    model = _ensure_model()
    if model is not None:
        try:
            result = await asyncio.to_thread(
                _transcribe_sync, model, audio_data, language, task
            )
            latency = int((time.time() - start) * 1000)
            result["provider"] = "sovereign"
            result["latency_ms"] = latency
            return result
        except Exception as e:
            logger.warning("Sovereign Whisper failed: %s", e)

    # Azure fallback
    try:
        result = await _transcribe_azure(audio_data, language)
        latency = int((time.time() - start) * 1000)
        result["provider"] = "azure"
        result["latency_ms"] = latency
        return result
    except Exception as e:
        logger.warning("Azure Whisper fallback failed: %s", e)

    return {
        "text": "",
        "provider": "none",
        "language": language or "unknown",
        "latency_ms": int((time.time() - start) * 1000),
        "error": "All STT providers unavailable",
    }


def _transcribe_sync(model, audio_data: bytes, language, task) -> Dict:
    """Run faster-whisper in thread (CPU/GPU bound)."""
    audio_file = io.BytesIO(audio_data)
    segments, info = model.transcribe(
        audio_file,
        language=language,
        task=task,
        beam_size=5,
        vad_filter=True,
    )
    text_parts = [seg.text for seg in segments]
    return {
        "text": " ".join(text_parts).strip(),
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
    }


async def _transcribe_azure(audio_data: bytes, language: Optional[str]) -> Dict:
    """Azure Whisper fallback."""
    import aiohttp

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    key = os.getenv("AZURE_API_KEY", "")
    deployment = os.getenv("AZURE_WHISPER_DEPLOYMENT", "whisper")

    if not endpoint or not key:
        raise RuntimeError("Azure Whisper not configured")

    url = f"https://{endpoint}/openai/deployments/{deployment}/audio/transcriptions?api-version=2024-06-01"

    form = aiohttp.FormData()
    form.add_field("file", audio_data, filename="audio.wav", content_type="audio/wav")
    if language:
        form.add_field("language", language)

    async with aiohttp.ClientSession() as sess:
        async with sess.post(
            url, data=form,
            headers={"api-key": key},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Azure Whisper returned {resp.status}")
            data = await resp.json()
            return {
                "text": data.get("text", "").strip(),
                "language": language or data.get("language", "en"),
            }


def is_available() -> bool:
    model = _ensure_model()
    return model is not None


def get_status() -> Dict[str, Any]:
    return {
        "sovereign_available": _model is not None,
        "model_size": _MODEL_SIZE,
        "device": _DEVICE,
        "azure_configured": bool(os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_API_KEY")),
    }
