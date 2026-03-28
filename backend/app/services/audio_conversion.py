"""
Audio format conversion utilities for Twilio <-> Little Nate pipeline.

Twilio Media Stream sends/receives mulaw 8kHz mono.
XTTS-v2 outputs PCM 22050Hz mono (WAV).
Sovereign Whisper expects PCM 16kHz mono.

Functions:
  mulaw_to_pcm16k  — Twilio input -> Whisper-ready PCM 16kHz
  wav_to_mulaw8k    — XTTS WAV output -> Twilio-ready mulaw 8kHz
  pcm_to_mulaw      — Raw PCM -> mulaw encoding
  mulaw_to_pcm      — Raw mulaw -> PCM decoding
"""

import audioop
import io
import struct
import wave
import logging
from typing import Optional

_logger = logging.getLogger("audio_conversion")

TWILIO_SAMPLE_RATE = 8000
WHISPER_SAMPLE_RATE = 16000
XTTS_SAMPLE_RATE = 22050
SAMPLE_WIDTH = 2  # 16-bit PCM


def mulaw_to_pcm(mulaw_bytes: bytes) -> bytes:
    """Decode mulaw-encoded audio to 16-bit linear PCM."""
    return audioop.ulaw2lin(mulaw_bytes, SAMPLE_WIDTH)


def pcm_to_mulaw(pcm_bytes: bytes) -> bytes:
    """Encode 16-bit linear PCM to mulaw."""
    return audioop.lin2ulaw(pcm_bytes, SAMPLE_WIDTH)


def resample_pcm(pcm_bytes: bytes, from_rate: int, to_rate: int) -> bytes:
    """Resample 16-bit PCM between sample rates."""
    if from_rate == to_rate:
        return pcm_bytes
    converted, _ = audioop.ratecv(
        pcm_bytes, SAMPLE_WIDTH, 1, from_rate, to_rate, None
    )
    return converted


def mulaw_to_pcm16k(mulaw_bytes: bytes) -> bytes:
    """
    Convert Twilio mulaw 8kHz -> PCM 16kHz for Whisper STT.

    Pipeline: mulaw decode -> 8kHz PCM -> resample to 16kHz PCM
    """
    pcm_8k = mulaw_to_pcm(mulaw_bytes)
    pcm_16k = resample_pcm(pcm_8k, TWILIO_SAMPLE_RATE, WHISPER_SAMPLE_RATE)
    return pcm_16k


def pcm16k_to_wav(pcm_bytes: bytes) -> bytes:
    """Wrap raw PCM 16kHz into a WAV container for Whisper."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(WHISPER_SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def wav_to_mulaw8k(wav_bytes: bytes) -> bytes:
    """
    Convert XTTS WAV output (22050Hz or any rate) -> mulaw 8kHz for Twilio.

    Pipeline: WAV decode -> get PCM + rate -> resample to 8kHz -> mulaw encode
    """
    buf = io.BytesIO(wav_bytes)
    try:
        with wave.open(buf, "rb") as wf:
            src_rate = wf.getframerate()
            src_width = wf.getsampwidth()
            src_channels = wf.getnchannels()
            pcm_data = wf.readframes(wf.getnframes())
    except wave.Error as e:
        _logger.warning("wav_to_mulaw8k: invalid WAV: %s", e)
        return b""

    if src_channels > 1:
        pcm_data = audioop.tomono(pcm_data, src_width, 1, 1)

    if src_width != SAMPLE_WIDTH:
        pcm_data = audioop.lin2lin(pcm_data, src_width, SAMPLE_WIDTH)

    pcm_8k = resample_pcm(pcm_data, src_rate, TWILIO_SAMPLE_RATE)
    return pcm_to_mulaw(pcm_8k)


def mulaw_chunks_to_whisper_wav(chunks: list) -> bytes:
    """
    Combine multiple mulaw chunks from Twilio into a single WAV
    suitable for Whisper STT.
    """
    combined = b"".join(chunks)
    pcm_16k = mulaw_to_pcm16k(combined)
    return pcm16k_to_wav(pcm_16k)
