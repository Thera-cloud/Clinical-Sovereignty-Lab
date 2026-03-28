"""μ-law ↔ PCM resampling for Twilio (8 kHz) ↔ Grok (16 kHz) ↔ XTTS (24 kHz). No heavy imports."""

import audioop
from typing import List, Optional


def twilio_mulaw_to_pcm16(mulaw_bytes: bytes, state: Optional[List]) -> bytes:
    """Twilio 8 kHz μ-law → 16-bit PCM mono 16 kHz for Grok input."""
    if not mulaw_bytes:
        return b""
    pcm_8k = audioop.ulaw2lin(mulaw_bytes, 2)
    if state is None:
        state = []
    if len(state) == 0:
        state.append(None)
    pcm_16k, st = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, state[0])
    state[0] = st
    return pcm_16k


def strip_wav_header(wav_bytes: bytes) -> bytes:
    if len(wav_bytes) >= 44 and wav_bytes[:4] == b"RIFF" and wav_bytes[8:12] == b"WAVE":
        return wav_bytes[44:]
    return wav_bytes


def xtts_pcm_to_twilio_mulaw(pcm_24k_bytes: bytes, state: Optional[List]) -> bytes:
    """XTTS 24 kHz 16-bit mono PCM → 8 kHz μ-law for Twilio."""
    if not pcm_24k_bytes:
        return b""
    if state is None:
        state = []
    if len(state) == 0:
        state.append(None)
    pcm_8k, st = audioop.ratecv(pcm_24k_bytes, 2, 1, 24000, 8000, state[0])
    state[0] = st
    return audioop.lin2ulaw(pcm_8k, 2)
