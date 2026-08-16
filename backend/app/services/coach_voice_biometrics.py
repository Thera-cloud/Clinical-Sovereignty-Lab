"""Campaign-ingest voice presence. Numpy extractor only — no GREEN Whisper weights."""

from __future__ import annotations

import io
import logging
import os
import re
import shutil
import struct
import subprocess
import tempfile
import wave
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("coach_voice_biometrics")


def pcm16_from_wav(data: bytes) -> Tuple[bytes, int]:
    """Return (pcm16_mono, sample_rate). Empty bytes if not a readable WAV."""
    if not data or len(data) < 44 or data[:4] != b"RIFF":
        return b"", 0
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            rate = int(wav.getframerate() or 0)
            width = wav.getsampwidth()
            ch = wav.getnchannels()
            frames = wav.readframes(wav.getnframes())
        if rate < 8000 or not frames:
            return b"", 0
        if width == 2 and ch == 1:
            return frames, rate
        if width == 2 and ch >= 2:
            mono = bytearray()
            frame = ch * 2
            for i in range(0, len(frames) - frame + 1, frame):
                mono.extend(frames[i : i + 2])
            return bytes(mono), rate
        if width == 1:
            out = bytearray()
            step = max(ch, 1)
            for i in range(0, len(frames), step):
                sample = (frames[i] - 128) * 256
                out.extend(struct.pack("<h", max(-32768, min(32767, sample))))
            return bytes(out), rate
    except Exception as exc:
        logger.warning("wav decode skipped: %s", exc)
    return b"", 0


def pcm16_via_ffmpeg(data: bytes) -> Tuple[bytes, int]:
    if not data or len(data) < 100 or not shutil.which("ffmpeg"):
        return b"", 0
    src = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            tmp.write(data)
            src = tmp.name
        proc = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                src,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "s16le",
                "pipe:1",
            ],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout and len(proc.stdout) >= 512:
            return proc.stdout, 16000
    except Exception as exc:
        logger.warning("ffmpeg pcm skipped: %s", exc)
    finally:
        if src:
            try:
                os.unlink(src)
            except OSError:
                pass
    return b"", 0


def to_pcm16_mono(media: bytes, content_type: str = "") -> Tuple[bytes, int]:
    ctype = (content_type or "").lower()
    pcm, rate = pcm16_from_wav(media)
    if pcm:
        return pcm, rate
    if "wav" in ctype or (media[:4] == b"RIFF"):
        return b"", 0
    return pcm16_via_ffmpeg(media)


def presence_from_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Map acoustic numbers into writing-presence fields. No clone."""
    if not metrics:
        return {}
    try:
        warmth = float(metrics.get("voice_warmth_index") or 0)
        pause = float(metrics.get("pause_ratio") or 0)
        rate = float(metrics.get("speech_rate") or 0)
        stress = float(metrics.get("voice_stress_index") or 0)
    except (TypeError, ValueError):
        return {}
    if warmth >= 0.55 and pause >= 0.22:
        presence = "slow, warm, leaves space before the next sentence"
        cadence = "unhurried"
    elif rate >= 160 or stress >= 0.6:
        presence = "brisk, pointed, little air between thoughts"
        cadence = "brisk"
    else:
        presence = "steady, measured, one idea then a pause"
        cadence = "measured"
    bios = {}
    for key, val in metrics.items():
        if isinstance(val, (int, float)):
            bios[str(key)] = round(float(val), 4)
    return {
        "presence_style": presence,
        "cadence": cadence,
        "voice_biometrics": bios,
        "presence_source": "voice_biometrics",
    }


def extract_campaign_biometrics(media: bytes, content_type: str = "") -> Dict[str, Any]:
    """Lazy-import extractor. Empty dict on any failure — never blocks ingest."""
    pcm, rate = to_pcm16_mono(media, content_type)
    if not pcm or rate < 8000 or len(pcm) < 512:
        return {}
    try:
        from app.services.nevedal_engine import VoiceBiometricExtractor

        extractor = VoiceBiometricExtractor(sample_rate=rate)
        chunk = max(rate, 256) * 2
        last: Dict[str, Any] = {}
        for i in range(0, len(pcm), chunk):
            piece = pcm[i : i + chunk]
            if len(piece) < 512:
                continue
            last = extractor.process_audio_chunk(piece) or last
        return presence_from_metrics(last)
    except Exception as exc:
        logger.warning("campaign biometrics skipped: %s", exc)
        return {}


def presence_from_transcript(text: str) -> Dict[str, Any]:
    """Typed/STT fallback when audio is too short for acoustics. Not a clone."""
    body = (text or "").strip()
    if len(body) < 40:
        return {}
    sentences = [s.strip() for s in re.split(r"[.!?]+", body) if s.strip()]
    words = re.findall(r"[A-Za-z']+", body)
    avg = len(words) / max(len(sentences), 1)
    pauses = (
        body.count("...")
        + body.count("—")
        + body.count(" -- ")
        + len(re.findall(r"\bum+\b", body, re.I))
    )
    if avg <= 10 or pauses >= 3:
        presence = "short sentences, leaves air, speaks in pieces"
        cadence = "unhurried"
    elif avg >= 22:
        presence = "long, unfolding sentences, few hard stops"
        cadence = "measured"
    else:
        presence = "plain spoken, one thought then the next"
        cadence = "measured"
    return {
        "presence_style": presence,
        "cadence": cadence,
        "presence_source": "transcript",
    }


def extract_visual_presence(media: bytes) -> Dict[str, Any]:
    """ffmpeg frame luma/motion — no ML, no BLUE visual server."""
    if not media or len(media) < 2000 or not shutil.which("ffmpeg"):
        return {}
    src = None
    td = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            tmp.write(media)
            src = tmp.name
        td = tempfile.mkdtemp(prefix="vis_")
        dest = os.path.join(td, "frames.rgb")
        proc = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                src,
                "-vf",
                "fps=1,scale=64:64",
                "-frames:v",
                "8",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                dest,
            ],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if proc.returncode != 0 or not os.path.isfile(dest):
            return {}
        with open(dest, "rb") as fh:
            raw = fh.read()
        frame = 64 * 64 * 3
        if len(raw) < frame:
            return {}
        n = len(raw) // frame
        lumas = []
        for i in range(n):
            chunk = raw[i * frame : (i + 1) * frame]
            total = 0.0
            pixels = 0
            for j in range(0, len(chunk) - 2, 3):
                total += 0.2126 * chunk[j] + 0.7152 * chunk[j + 1] + 0.0722 * chunk[j + 2]
                pixels += 1
            lumas.append((total / max(pixels, 1)) / 255.0)
        motion = 0.0
        if n >= 2:
            diffs = []
            for i in range(1, n):
                a = raw[(i - 1) * frame : i * frame]
                b = raw[i * frame : (i + 1) * frame]
                acc = 0
                samples = 0
                for k in range(0, frame, 12):
                    acc += abs(a[k] - b[k])
                    samples += 1
                diffs.append((acc / max(samples, 1)) / 255.0)
            motion = sum(diffs) / len(diffs)
        mean_luma = sum(lumas) / len(lumas)
        if motion < 0.04 and mean_luma < 0.25:
            visual = "still, low light, close and contained"
        elif motion >= 0.12:
            visual = "moves while speaking, more energy in the frame"
        else:
            visual = "steady camera, even light, seated presence"
        return {
            "visual_presence": visual,
            "visual_metrics": {
                "luma": round(mean_luma, 3),
                "motion": round(motion, 3),
            },
        }
    except Exception as exc:
        logger.warning("visual presence skipped: %s", exc)
        return {}
    finally:
        if src:
            try:
                os.unlink(src)
            except OSError:
                pass
        if td:
            shutil.rmtree(td, ignore_errors=True)


def style_presence_block(profile: Optional[Dict[str, Any]]) -> str:
    profile = profile or {}
    presence = str(profile.get("presence_style") or "").strip()
    visual = str(profile.get("visual_presence") or "").strip()
    bios = profile.get("voice_biometrics") or {}
    if not presence and not bios and not visual:
        return ""
    bits = []
    if presence:
        bits.append(f"Spoken presence: {presence}.")
    if visual:
        bits.append(f"On camera: {visual}.")
    if isinstance(bios, dict) and bios:
        bits.append(
            "Acoustic (do not invent numbers in copy; match the feel): "
            f"warmth={bios.get('voice_warmth_index')}, "
            f"pause_ratio={bios.get('pause_ratio')}, "
            f"speech_rate={bios.get('speech_rate')}."
        )
    bits.append("Write at that spoken pace. Do not mention biometrics or recordings.")
    return " ".join(bits)
