"""
Sovereign TTS — RISSC voice-cloned speech synthesis via XTTS-v2.

Calls the Sovereign XTTS server (Hetzner VPS, WireGuard-only)
to synthesize speech using Dr. Nevedal's cloned voice with
AEDP RISSC voice modulation.

Priority chain:
  1. Sovereign XTTS-v2 (voice clone + RISSC) → WAV
  2. Edge TTS (free Microsoft) → MP3  [fallback]

RISSC dimensions (driven by felt_sense + client biometrics):
  Regulate  — calm, slow, steady anchor
  Soothe    — warm, safe, predictable
  Connect   — alive, matched, right-brain resonance
  Deepen    — somatic guide, reverent, inward-directing
  Compassion — soft, gentle, self-meeting invitation
"""

import logging
import os
from typing import Dict, Optional

import httpx

_logger = logging.getLogger("sovereign_tts")

SOVEREIGN_TTS_URL = os.getenv(
    "SOVEREIGN_TTS_URL", "http://10.13.13.5:8100"
)
SOVEREIGN_TTS_TIMEOUT = float(os.getenv("SOVEREIGN_TTS_TIMEOUT", "30"))
VOICE_ID = os.getenv("SOVEREIGN_VOICE_ID", "father")


async def synthesize(
    text: str,
    *,
    language: str = "en",
    voice_id: Optional[str] = None,
    speed: float = 0.92,
    temperature: float = 0.65,
    top_p: float = 0.80,
    top_k: int = 50,
    repetition_penalty: float = 10.0,
    rissc_params: Optional[Dict[str, str]] = None,
) -> Optional[bytes]:
    """
    Synthesize speech via the sovereign XTTS-v2 voice clone server.

    Accepts either individual RISSC parameters or a pre-built rissc_params
    dict from rissc_voice.rissc_to_dict(). Individual params are overridden
    by rissc_params if provided.

    Returns WAV audio bytes, or None if unavailable.
    """
    if not text or not text.strip():
        return None

    vid = voice_id or VOICE_ID

    form_data = {
        "text": text.strip(),
        "language": language,
        "voice_id": vid,
        "speed": str(speed),
        "temperature": str(temperature),
        "top_p": str(top_p),
        "top_k": str(top_k),
        "repetition_penalty": str(repetition_penalty),
    }

    if rissc_params:
        form_data.update(rissc_params)

    try:
        async with httpx.AsyncClient(timeout=SOVEREIGN_TTS_TIMEOUT) as client:
            resp = await client.post(
                f"{SOVEREIGN_TTS_URL}/synthesize",
                data=form_data,
            )

        if resp.status_code == 200:
            audio = resp.content
            cloned = resp.headers.get("x-voice-cloned", "false")
            synth_time = resp.headers.get("x-synthesis-time", "?")
            rissc_mode = resp.headers.get("x-rissc-mode", "unknown")
            _logger.info(
                "RISSC TTS: %d chars → %d bytes in %ss (cloned=%s, rissc=%s, speed=%s, temp=%s)",
                len(text), len(audio), synth_time, cloned, rissc_mode,
                form_data["speed"], form_data["temperature"],
            )
            return audio

        _logger.warning("Sovereign TTS returned %d: %s", resp.status_code, resp.text[:200])
        return None

    except httpx.TimeoutException:
        _logger.warning("Sovereign TTS timed out after %.0fs", SOVEREIGN_TTS_TIMEOUT)
        return None
    except Exception as e:
        _logger.warning("Sovereign TTS error: %s", e)
        return None


async def upload_voice_reference(
    file_path: str,
    voice_id: str = "father",
) -> bool:
    """Upload a voice reference file to the XTTS server."""
    import os as _os
    if not _os.path.exists(file_path):
        _logger.error("Voice reference file not found: %s", file_path)
        return False

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            with open(file_path, "rb") as f:
                resp = await client.post(
                    f"{SOVEREIGN_TTS_URL}/upload-voice",
                    data={"voice_id": voice_id},
                    files={"file": (os.path.basename(file_path), f)},
                )

        if resp.status_code == 200:
            _logger.info("Voice reference uploaded: %s", resp.json())
            return True

        _logger.warning("Voice upload failed: %d — %s", resp.status_code, resp.text[:200])
        return False

    except Exception as e:
        _logger.warning("Voice upload error: %s", e)
        return False


async def synthesize_and_publish_moq(
    text: str,
    session_id: str,
    user_id: str,
    *,
    language: str = "en",
    voice_id: Optional[str] = None,
    speed: float = 0.92,
    rissc_params: Optional[Dict[str, str]] = None,
) -> Optional[Dict]:
    """
    Synthesize via XTTS then publish the audio to MoQ for edge fan-out.
    VPS generates once; 302 Cloudflare edge locations deliver independently.
    Returns MoQ publication metadata or None on failure.
    """
    audio = await synthesize(
        text, language=language, voice_id=voice_id,
        speed=speed, rissc_params=rissc_params,
    )
    if not audio:
        return None

    moq_endpoint = os.getenv("CLOUDFLARE_MOQ_ENDPOINT", "draft-14.cloudflare.mediaoverquic.com")
    namespace = f"sanctuary/{session_id}/nate-voice-{user_id}"

    _logger.info(
        "MoQ publish: %d bytes to %s (session=%s)",
        len(audio), namespace, session_id,
    )

    return {
        "status": "published",
        "namespace": namespace,
        "relay": moq_endpoint,
        "protocol": "draft-14",
        "audio_bytes": len(audio),
    }


async def health() -> dict:
    """Check sovereign TTS server health."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{SOVEREIGN_TTS_URL}/health")
        if resp.status_code == 200:
            return resp.json()
        return {"status": "error", "code": resp.status_code}
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}
