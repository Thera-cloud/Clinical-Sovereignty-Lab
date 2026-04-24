"""
Zoom audio → Whisper VTT fallback.

When a Zoom cloud recording finishes but Zoom did NOT auto-generate a
transcript (Audio Transcript disabled at account/meeting level, or the
account does not have the feature), we still have the audio file (M4A).

This module:
  1. Picks the first completed audio file (M4A / MP3 / M4P) from the
     Zoom recording_files list.
  2. Downloads it via ZoomClient.
  3. Uses ffmpeg to re-encode to 16 kHz mono Opus/WAV (small + Whisper-
     friendly), splitting into chunks if needed (Azure Whisper REST has
     a 25 MB upload limit).
  4. Transcribes each chunk via whisper_stt with response_format=vtt.
  5. Stitches the chunk VTTs back into a single offset-corrected VTT
     blob and returns it as bytes.

The resulting VTT has no real speaker diarization (Whisper does not do
speaker separation). We label every cue as `SPEAKER:` so the existing
ClassroomAnalyzer VTT parser still extracts duration / techniques /
question counts. Coach-vs-client talk-time will be inaccurate, which is
why we tag the synthesized output (callers should record
`transcript_source = "whisper_fallback"` on the session).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, List, Optional, Tuple

_logger = logging.getLogger("zoom_audio_fallback")

# Whisper REST upload cap is 25 MB; leave headroom for multipart overhead.
_MAX_CHUNK_BYTES = 22 * 1024 * 1024
_AUDIO_FILE_TYPES = ("M4A", "MP3", "AUDIO_ONLY")
_AUDIO_FILE_EXTS = ("M4A", "MP3", "WAV")


def is_fallback_enabled() -> bool:
    """Caller should also check whisper_stt.is_whisper_configured()."""
    flag = os.getenv("ZOOM_WHISPER_FALLBACK", "true").strip().lower()
    return flag in ("1", "true", "yes", "on")


def pick_audio_file(recording_files: List[Any]) -> Tuple[Optional[str], Optional[str]]:
    """Return (download_url, extension) for first completed audio file."""
    for rf in recording_files or []:
        if not isinstance(rf, dict):
            continue
        file_type = (rf.get("file_type") or "").upper()
        file_ext = (rf.get("file_extension") or "").upper()
        if file_type in _AUDIO_FILE_TYPES or file_ext in _AUDIO_FILE_EXTS:
            if (rf.get("status") or "").lower() != "completed":
                continue
            url = (rf.get("download_url") or "").strip()
            if not url:
                continue
            ext = (rf.get("file_extension") or "m4a").strip().lower() or "m4a"
            return url, ext
    return None, None


def _have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _probe_duration_seconds(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout.strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0


def _encode_mono_16k(src: Path, dst: Path) -> bool:
    """Re-encode any audio to 16 kHz mono Opus inside Ogg (very small)."""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-i", str(src),
             "-ac", "1", "-ar", "16000",
             "-c:a", "libopus", "-b:a", "16k",
             str(dst)],
            check=True, timeout=600,
        )
        return dst.exists() and dst.stat().st_size > 0
    except Exception as e:
        _logger.warning("ffmpeg encode failed: %s", e)
        return False


def _chunk_by_seconds(src: Path, out_dir: Path, chunk_seconds: int) -> List[Path]:
    """Split src into N <chunk_seconds> Opus chunks named chunk_000.ogg ..."""
    pattern = str(out_dir / "chunk_%03d.ogg")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-i", str(src),
             "-f", "segment", "-segment_time", str(chunk_seconds),
             "-c", "copy",
             pattern],
            check=True, timeout=600,
        )
    except Exception as e:
        _logger.warning("ffmpeg chunk split failed: %s", e)
        return []
    return sorted(out_dir.glob("chunk_*.ogg"))


_TS_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})")


def _ts_to_seconds(ts: str) -> float:
    m = _TS_RE.match(ts.strip())
    if not m:
        return 0.0
    h, mn, s, ms = m.groups()
    return int(h) * 3600 + int(mn) * 60 + int(s) + int(ms) / 1000.0


def _seconds_to_ts(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _shift_vtt(vtt_text: str, offset_seconds: float, speaker_label: str) -> List[str]:
    """Return a list of VTT cue blocks (without WEBVTT header) with timestamps shifted."""
    out: List[str] = []
    if not vtt_text or not vtt_text.strip():
        return out
    lines = vtt_text.splitlines()
    i = 0
    # Skip header
    while i < len(lines) and not _TS_RE.search(lines[i]):
        i += 1
    while i < len(lines):
        line = lines[i].strip()
        if "-->" in line:
            try:
                left, right = [p.strip() for p in line.split("-->", 1)]
                # Strip optional cue settings after the right timestamp.
                right_ts = right.split()[0] if right else right
                start = _ts_to_seconds(left) + offset_seconds
                end = _ts_to_seconds(right_ts) + offset_seconds
                cue_lines: List[str] = []
                i += 1
                while i < len(lines) and lines[i].strip():
                    cue_lines.append(lines[i].strip())
                    i += 1
                if cue_lines:
                    text = " ".join(cue_lines).strip()
                    if text:
                        out.append(
                            f"{_seconds_to_ts(start)} --> {_seconds_to_ts(end)}\n"
                            f"{speaker_label}: {text}"
                        )
            except Exception:
                i += 1
        else:
            i += 1
    return out


async def transcribe_zoom_audio_to_vtt(
    audio_bytes: bytes,
    *,
    speaker_label: str = "SPEAKER",
) -> Optional[bytes]:
    """
    Convert raw audio bytes (any container ffmpeg can read) into a VTT
    transcript via Azure Whisper. Handles chunking for files larger than
    the Whisper upload limit. Returns UTF-8 VTT bytes or None on failure.
    """
    if not audio_bytes or len(audio_bytes) < 1024:
        return None
    if not _have_ffmpeg():
        _logger.warning("ffmpeg not available — cannot run Whisper fallback")
        return None

    # Lazy import so this module is safe to import even if whisper_stt is
    # not configured at startup.
    from app.services import whisper_stt  # noqa: WPS433

    if not whisper_stt.is_whisper_configured():
        _logger.warning("Whisper STT not configured — cannot run audio fallback")
        return None

    with tempfile.TemporaryDirectory(prefix="zoom_whisper_") as td_str:
        td = Path(td_str)
        src_path = td / "source.bin"
        src_path.write_bytes(audio_bytes)

        normalized = td / "audio_16k.ogg"
        if not _encode_mono_16k(src_path, normalized):
            return None

        size = normalized.stat().st_size
        duration = _probe_duration_seconds(normalized)
        _logger.info(
            "[ZoomFallback] normalized audio: %.1f MB, %.1f s",
            size / (1024 * 1024), duration,
        )

        # Decide chunking
        chunk_paths: List[Path]
        chunk_starts: List[float]
        if size <= _MAX_CHUNK_BYTES or duration <= 0:
            chunk_paths = [normalized]
            chunk_starts = [0.0]
        else:
            # Conservative: 600 s per chunk at 16 kbps mono opus ≈ 1.2 MB,
            # leaves plenty of headroom under 22 MB.
            chunk_seconds = 600
            chunk_dir = td / "chunks"
            chunk_dir.mkdir()
            chunk_paths = _chunk_by_seconds(normalized, chunk_dir, chunk_seconds)
            if not chunk_paths:
                return None
            chunk_starts = [i * chunk_seconds for i in range(len(chunk_paths))]
            _logger.info("[ZoomFallback] split into %d chunks of ~%ds", len(chunk_paths), chunk_seconds)

        cues: List[str] = []
        for path, offset in zip(chunk_paths, chunk_starts):
            try:
                data = path.read_bytes()
            except Exception:
                continue
            vtt_text = await _transcribe_chunk_as_vtt(whisper_stt, data)
            if not vtt_text:
                continue
            cues.extend(_shift_vtt(vtt_text, offset, speaker_label))

        if not cues:
            _logger.warning("[ZoomFallback] no cues produced from %d chunks", len(chunk_paths))
            return None

        body = "WEBVTT\n\n" + "\n\n".join(cues) + "\n"
        return body.encode("utf-8")


async def _transcribe_chunk_as_vtt(whisper_stt_module, audio_data: bytes) -> Optional[str]:
    """
    Call Azure Whisper REST directly with response_format=vtt for this
    chunk. We bypass the public whisper_stt.transcribe() helper because
    that helper hardcodes response_format=text.
    """
    import io
    import httpx

    endpoint = os.getenv("AZURE_WHISPER_ENDPOINT", os.getenv("AZURE_OPENAI_ENDPOINT", "")).rstrip("/")
    key = os.getenv("AZURE_WHISPER_KEY", os.getenv("AZURE_API_KEY", ""))
    deployment = os.getenv("AZURE_WHISPER_DEPLOYMENT", "nate-whisper")
    api_version = os.getenv("AZURE_WHISPER_API_VERSION", "2024-06-01")
    if not (endpoint and key and deployment):
        return None

    url = f"{endpoint}/openai/deployments/{deployment}/audio/transcriptions?api-version={api_version}"
    files = {
        "file": ("audio.ogg", io.BytesIO(audio_data), "audio/ogg"),
        "language": (None, "en"),
        "response_format": (None, "vtt"),
    }
    headers = {"api-key": key}

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(url, headers=headers, files=files)
        if resp.status_code == 200:
            return resp.text
        _logger.warning("[ZoomFallback] Whisper VTT chunk HTTP %d: %s", resp.status_code, resp.text[:200])
        return None
    except Exception as e:
        _logger.warning("[ZoomFallback] Whisper VTT chunk error: %s", e)
        return None
