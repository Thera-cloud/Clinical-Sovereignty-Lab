"""Codec tests — load module by path to avoid importing app.services (numpy/nevedal on import)."""

import importlib.util
from pathlib import Path

_CODEC = Path(__file__).resolve().parent.parent / "app" / "services" / "twilio_voice_codec.py"
_spec = importlib.util.spec_from_file_location("twilio_voice_codec", _CODEC)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)

strip_wav_header = _mod.strip_wav_header
twilio_mulaw_to_pcm16 = _mod.twilio_mulaw_to_pcm16
xtts_pcm_to_twilio_mulaw = _mod.xtts_pcm_to_twilio_mulaw


def test_strip_wav_header():
    hdr = b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + (b"\x00" * 32)
    payload = b"pcmdata"
    wav = hdr + payload
    assert strip_wav_header(wav) == payload


def test_mulaw_to_pcm16_expands_rate():
    mulaw = bytes([0xFF]) * 160
    st: list = []
    pcm16 = twilio_mulaw_to_pcm16(mulaw, st)
    # 8k→16k ~2× samples; ratecv may trim 1 sample on a single chunk
    assert len(pcm16) % 2 == 0
    assert 600 <= len(pcm16) <= 660


def test_xtts_pcm_to_mulaw_from_silence_24k():
    pcm24 = b"\x00\x00" * 240
    st: list = []
    mulaw = xtts_pcm_to_twilio_mulaw(pcm24, st)
    assert len(mulaw) == 80
