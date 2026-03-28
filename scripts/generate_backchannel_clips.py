"""
Generate pre-rendered mulaw WAV backchannel clips using Azure OpenAI gpt-4o-mini-tts.

Uses the Azure OpenAI TTS REST API with voice instructions for prosodic control.
No extra SDK needed beyond `requests`.

Env vars:
    AZURE_API_KEY                    -- Azure OpenAI API key
    AZURE_OPENAI_ENDPOINT            -- Azure OpenAI resource hostname (no protocol)
    AZURE_OPENAI_MINI_TTS_DEPLOYMENT -- Deployment name (default: gpt-4o-mini-tts)

Output: 8kHz 8-bit mono mulaw WAV files in backend/assets/backchannel_clips/{register}/
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. pip install requests")
    sys.exit(1)

CLIPS_DIR = Path(__file__).resolve().parent.parent / "backend" / "assets" / "backchannel_clips"

CLIP_DEFINITIONS = {
    "neutral": [
        {"text": "Mm-hmm.", "mood": "Calm, neutral acknowledgment. Brief.", "speed": 1.0},
        {"text": "Mm.", "mood": "Soft, brief acknowledgment.", "speed": 0.9},
        {"text": "Uh-huh.", "mood": "Natural, slight upward inflection. Brief.", "speed": 1.0},
        {"text": "Yeah.", "mood": "Calm, brief acknowledgment.", "speed": 1.0},
        {"text": "Right.", "mood": "Grounded, brief acknowledgment.", "speed": 1.0},
        {"text": "Okay.", "mood": "Warm, calm, brief.", "speed": 1.0},
    ],
    "warm": [
        {"text": "Mm-hmm.", "mood": "Warm, gentle, caring. Slow and soft.", "speed": 0.85},
        {"text": "Yeah.", "mood": "Soft and warm. Slow, caring.", "speed": 0.85},
        {"text": "I see.", "mood": "Warm understanding. Slow, soft.", "speed": 0.85},
        {"text": "Of course.", "mood": "Gentle, validating. Slow pace.", "speed": 0.85},
        {"text": "Sure.", "mood": "Soft warmth. Brief, caring.", "speed": 0.85},
    ],
    "empathic": [
        {"text": "Mm.", "mood": "Very soft and slow. Deep empathy, holding space for pain.", "speed": 0.75},
        {"text": "I hear you.", "mood": "Deep empathy. Very soft, slow, holding space.", "speed": 0.8},
        {"text": "That makes sense.", "mood": "Deep understanding. Soft, slow, validating.", "speed": 0.8},
        {"text": "Yeah.", "mood": "Very soft. Deep empathy, almost a whisper.", "speed": 0.75},
        {"text": "I understand.", "mood": "Genuine deep empathy. Soft, slow, holding space.", "speed": 0.8},
        {"text": "Mm-hmm.", "mood": "Very soft and slow. Deep empathy, holding space.", "speed": 0.75},
    ],
    "validating": [
        {"text": "Absolutely.", "mood": "Genuine enthusiasm and validation. Affirming.", "speed": 1.0},
        {"text": "Yes!", "mood": "Warm enthusiasm. Affirming energy.", "speed": 1.0},
        {"text": "Exactly.", "mood": "Enthusiastic validation. Affirming.", "speed": 1.0},
        {"text": "That's right.", "mood": "Warm validation. Slight enthusiasm.", "speed": 1.0},
        {"text": "Mm-hmm!", "mood": "Enthusiastic validation. Upward inflection.", "speed": 1.0},
    ],
}

VOICE_NAME = "onyx"

# Base voice persona — must match the instructions used in both voice pipelines
# (twilio_grok_xtts_pipeline.py and littlenate_realtime.py)
NATE_VOICE_PERSONA = (
    "Speak as a warm, confident young man in his late 20s. "
    "Natural and conversational — like talking to a trusted older brother. "
    "Relaxed pace, occasional light laugh energy. Never robotic or clinical."
)
API_VERSION = "2025-01-01-preview"


def pcm_to_mulaw(sample: int) -> int:
    """Encode a single 16-bit PCM sample to 8-bit mu-law."""
    MULAW_MAX = 0x1FFF
    MULAW_BIAS = 33
    sign = 0
    if sample < 0:
        sign = 0x80
        sample = -sample
    sample = min(sample + MULAW_BIAS, MULAW_MAX)
    exponent = 7
    for exp_val in range(7, -1, -1):
        if sample >= (1 << (exp_val + 4)):
            exponent = exp_val
            break
    else:
        exponent = 0
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


def convert_pcm16_to_mulaw_wav(pcm_data: bytes, src_rate: int = 24000, dst_rate: int = 8000) -> bytes:
    """Convert 16-bit mono PCM to 8kHz 8-bit mu-law WAV."""
    samples = struct.unpack(f"<{len(pcm_data) // 2}h", pcm_data)
    ratio = src_rate / dst_rate
    resampled = []
    i = 0.0
    while int(i) < len(samples):
        resampled.append(samples[int(i)])
        i += ratio

    mulaw_bytes = bytes(pcm_to_mulaw(s) for s in resampled)

    data_size = len(mulaw_bytes)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        18,
        7,  # mu-law format
        1,  # mono
        dst_rate,
        dst_rate,
        1,
        8,
        b"data",
        data_size,
    )
    return header + mulaw_bytes


def strip_wav_header(wav_data: bytes) -> tuple[bytes, int]:
    """Strip WAV header and return (PCM data, sample_rate)."""
    if wav_data[:4] != b"RIFF":
        raise ValueError("Not a WAV file")
    fmt_offset = wav_data.find(b"fmt ")
    if fmt_offset == -1:
        raise ValueError("No fmt chunk found")
    sample_rate = struct.unpack_from("<I", wav_data, fmt_offset + 12)[0]
    data_offset = wav_data.find(b"data")
    if data_offset == -1:
        raise ValueError("No data chunk found")
    data_size = struct.unpack_from("<I", wav_data, data_offset + 4)[0]
    pcm_start = data_offset + 8
    return wav_data[pcm_start : pcm_start + data_size], sample_rate


def generate_clips() -> None:
    api_key = os.getenv("AZURE_API_KEY", "").strip()
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    deployment = os.getenv("AZURE_OPENAI_MINI_TTS_DEPLOYMENT", "gpt-4o-mini-tts").strip()

    if not api_key or not endpoint:
        print("ERROR: Set AZURE_API_KEY and AZURE_OPENAI_ENDPOINT env vars")
        sys.exit(1)

    if not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"

    url = f"{endpoint}/openai/deployments/{deployment}/audio/speech?api-version={API_VERSION}"
    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
    }

    total = 0
    failed = 0
    for register, clips in CLIP_DEFINITIONS.items():
        out_dir = CLIPS_DIR / register
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, clip_def in enumerate(clips):
            payload = {
                "model": deployment,
                "input": clip_def["text"],
                "voice": VOICE_NAME,
                "instructions": f"{NATE_VOICE_PERSONA} {clip_def['mood']}",
                "response_format": "wav",
                "speed": clip_def["speed"],
            }
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
                if resp.status_code == 200:
                    wav_data = resp.content
                    pcm_data, src_rate = strip_wav_header(wav_data)
                    mulaw_wav = convert_pcm16_to_mulaw_wav(pcm_data, src_rate=src_rate, dst_rate=8000)
                    safe_text = clip_def["text"].lower().replace(" ", "_").replace(".", "").replace("!", "").replace("'", "")
                    filename = f"{i:02d}_{safe_text}.wav"
                    out_path = out_dir / filename
                    out_path.write_bytes(mulaw_wav)
                    print(f"  [{register}] {filename} ({len(mulaw_wav)} bytes)")
                    total += 1
                else:
                    print(f"  [{register}] FAILED: {clip_def['text']} — HTTP {resp.status_code}: {resp.text[:200]}")
                    failed += 1
            except Exception as e:
                print(f"  [{register}] ERROR: {clip_def['text']} — {e}")
                failed += 1

    print(f"\nGenerated {total} backchannel clips ({failed} failed) in {CLIPS_DIR}")


if __name__ == "__main__":
    generate_clips()
