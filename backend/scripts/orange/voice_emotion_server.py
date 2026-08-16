"""
ORANGE Node — Voice Emotion Inference Server (Hetzner CAX41).

This is the wav2vec2 endpoint that GREEN's classroom_remote_dispatch
calls when CLASSROOM_VOICE_REMOTE_URL is set. ORANGE owns the model
weights (~1.5 GB) and the full audio pipeline so the GREEN VPS
(6 GB total, hosting 100+ services) never has to.

Deployment topology (per .cursor/rules/three-node-sync-discipline.mdc):
    Reachable from GREEN at:  http://10.13.13.5:8090   (WireGuard)
    Hardware:                  16 ARM64 cores, 32 GB RAM, 320 GB NVMe
    Process manager:           systemd (see voice_emotion_server.service)

Endpoints:
    GET  /health           — quick liveness + capability gate report
    POST /voice-emotion    — main inference endpoint (matches the contract
                             documented in classroom_remote_dispatch.py)
    POST /transcribe       — multipart file → {text} (faster-whisper; no GREEN load)

Request body for POST /voice-emotion:
    {
      "audio_url":        "https://r2-presigned/.../recording.mp4",
      "segment_seconds":  10
    }

Response body (verbatim VoiceEmotionAnalyzer.analyze_audio dict):
    {
      "segments_analyzed": 67,
      "emotion_timeline": [...],
      "emotion_distribution": {...},
      "dominant_emotion": "neutral",
      "emotional_shifts": [...],
      "shift_count": 12,
      "patterns": [...],
      "analysis_mode": "transformer" | "librosa_rules"
    }

Authentication:
    If env CLASSROOM_REMOTE_AUTH_TOKEN is set, requests must carry
    `Authorization: Bearer <token>` matching it. When unset, the only
    network path open is WireGuard 10.13.13.0/24, so we accept anything.

Run locally for testing:
    pip install fastapi uvicorn httpx librosa numpy \
        torch torchaudio transformers
    uvicorn voice_emotion_server:app --host 0.0.0.0 --port 8090
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Capability gates — match what voice_emotion_analyzer.py probes for.
# ---------------------------------------------------------------------------

_HAS_TRANSFORMERS = False
_HAS_TORCHAUDIO = False
_HAS_LIBROSA = False
try:
    import transformers as _t  # noqa: F401
    _HAS_TRANSFORMERS = True
except Exception:
    pass
try:
    import torchaudio as _ta  # noqa: F401
    _HAS_TORCHAUDIO = True
except Exception:
    pass
try:
    import librosa as _lr  # noqa: F401
    _HAS_LIBROSA = True
except Exception:
    pass


# ---------------------------------------------------------------------------
# Reuse the GREEN-side analyzer code so the result shape is identical.
#
# To avoid pulling in `app.services.__init__` (which imports DB/Stripe/etc
# that don't exist on ORANGE), we load voice_emotion_analyzer.py directly
# by file path. The deploy.sh script copies the analyzer next to this
# server file, so the local copy is the canonical source on ORANGE.
# ---------------------------------------------------------------------------

import importlib.util as _ilu
import sys

_HERE = Path(__file__).resolve().parent

_LOCAL_ANALYZER = _HERE / "voice_emotion_analyzer.py"
_REPO_ANALYZER = _HERE.parent.parent / "app" / "services" / "voice_emotion_analyzer.py"

_analyzer_path = _LOCAL_ANALYZER if _LOCAL_ANALYZER.exists() else _REPO_ANALYZER

if not _analyzer_path.exists():  # pragma: no cover
    raise RuntimeError(
        f"voice_emotion_analyzer.py not found at {_LOCAL_ANALYZER} or {_REPO_ANALYZER}"
    )

_spec = _ilu.spec_from_file_location("voice_emotion_analyzer", str(_analyzer_path))
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise RuntimeError(f"could not build import spec for {_analyzer_path}")

_mod = _ilu.module_from_spec(_spec)
sys.modules["voice_emotion_analyzer"] = _mod
_spec.loader.exec_module(_mod)
VoiceEmotionAnalyzer = _mod.VoiceEmotionAnalyzer  # type: ignore[attr-defined]


_ANALYZER: Optional[VoiceEmotionAnalyzer] = None
_WHISPER = None


def _have_faster_whisper() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


def _get_whisper():
    """Lazy faster-whisper on ORANGE only. Never import this module on GREEN."""
    global _WHISPER
    if _WHISPER is None:
        from faster_whisper import WhisperModel

        name = os.getenv("ORANGE_WHISPER_MODEL", "base")
        _WHISPER = WhisperModel(name, device="cpu", compute_type="int8")
    return _WHISPER


def _stt_wav(wav: Path) -> str:
    try:
        model = _get_whisper()
        segs, _info = model.transcribe(str(wav), language="en")
        return " ".join((s.text or "").strip() for s in segs if s.text).strip()
    except Exception as exc:
        print(f"[ORANGE] transcribe failed: {exc}")
        return ""


def _get_analyzer() -> VoiceEmotionAnalyzer:
    global _ANALYZER
    if _ANALYZER is None:
        # On ORANGE we want the transformer pipeline — explicitly clear
        # the GREEN-only force flag in case it leaked into the env.
        os.environ["VOICE_EMOTION_FORCE_LIBROSA"] = "0"
        _ANALYZER = VoiceEmotionAnalyzer()
        _ANALYZER._load_transformer()  # warm the model on first request
    return _ANALYZER


# ---------------------------------------------------------------------------
# Auth + helpers
# ---------------------------------------------------------------------------

_AUTH_TOKEN = (os.getenv("CLASSROOM_REMOTE_AUTH_TOKEN", "") or "").strip()
_DOWNLOAD_TIMEOUT = float(os.getenv("ORANGE_DOWNLOAD_TIMEOUT_SEC", "900"))
_FFMPEG_TIMEOUT = float(os.getenv("ORANGE_FFMPEG_TIMEOUT_SEC", "600"))


def _check_auth(authorization: Optional[str]) -> None:
    if not _AUTH_TOKEN:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    presented = authorization.split(" ", 1)[1].strip()
    if presented != _AUTH_TOKEN:
        raise HTTPException(status_code=403, detail="invalid bearer token")


def _have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg"))


async def _download(url: str, dest: Path) -> None:
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        async with client.stream("GET", url) as resp:
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"upstream R2 fetch failed HTTP {resp.status_code}",
                )
            with open(dest, "wb") as fh:
                async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                    fh.write(chunk)


def _extract_wav(src: Path, dst: Path) -> bool:
    """ffmpeg → mono 22.05 kHz WAV, what librosa+torchaudio expect."""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-i", str(src),
             "-ac", "1", "-ar", "22050",
             "-vn", "-c:a", "pcm_s16le",
             str(dst)],
            check=True, timeout=_FFMPEG_TIMEOUT,
        )
        return dst.exists() and dst.stat().st_size > 0
    except subprocess.CalledProcessError as exc:
        print(f"[ORANGE] ffmpeg failed: {exc}")
        return False
    except subprocess.TimeoutExpired:
        print(f"[ORANGE] ffmpeg timed out after {_FFMPEG_TIMEOUT}s")
        return False


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    print("[ORANGE] voice_emotion_server starting")
    print(f"  has_transformers={_HAS_TRANSFORMERS} has_torchaudio={_HAS_TORCHAUDIO} has_librosa={_HAS_LIBROSA}")
    print(f"  has_ffmpeg={_have_ffmpeg()}  auth_required={bool(_AUTH_TOKEN)}")
    if _HAS_TRANSFORMERS and _HAS_TORCHAUDIO:
        try:
            _get_analyzer()
            print("[ORANGE] wav2vec2 pipeline warmed")
        except Exception as exc:
            print(f"[ORANGE] wav2vec2 warm-up failed (will retry on first request): {exc}")
    yield
    print("[ORANGE] voice_emotion_server stopping")


app = FastAPI(title="ORANGE Voice Emotion Server", lifespan=_lifespan)


class VoiceEmotionRequest(BaseModel):
    audio_url: str
    segment_seconds: int = 10
    # Adaptive sampling: when set (>0 and < segment_seconds), ORANGE first
    # runs a coarse sweep at `segment_seconds`, then re-analyzes the
    # boundary windows around emotion transitions at this finer granularity.
    # Trade-off: ~3x faster than uniform fine sampling, with full precision
    # at the moments that matter for clinical signal (transitions).
    # Recommended: segment_seconds=30, adaptive_segment_seconds=10.
    adaptive_segment_seconds: Optional[int] = None
    # Pad on each side of a transition (in coarse seconds). 1 = re-analyze
    # the coarse segment immediately before and after the boundary.
    adaptive_window_pad: int = 1


def _slice_wav(src_wav: Path, start_sec: float, end_sec: float, dst_wav: Path) -> bool:
    """Slice [start_sec, end_sec] of a mono PCM WAV into a new file.

    Used for adaptive boundary re-analysis so we don't re-download or
    re-decode the full audio for each refined window.
    """
    try:
        import soundfile as sf
        info = sf.info(str(src_wav))
        sr = int(info.samplerate)
        start_frame = max(0, int(start_sec * sr))
        end_frame = min(int(info.frames), int(end_sec * sr))
        if end_frame <= start_frame:
            return False
        data, _ = sf.read(
            str(src_wav), start=start_frame, stop=end_frame, dtype="int16",
            always_2d=False,
        )
        sf.write(str(dst_wav), data, sr, subtype="PCM_16")
        return dst_wav.exists() and dst_wav.stat().st_size > 0
    except Exception as exc:
        print(f"[ORANGE] _slice_wav failed: {exc}")
        return False


def _find_transition_windows(
    timeline: list, coarse_sec: int, pad: int
) -> list:
    """Return list of (start_sec, end_sec) windows around emotion transitions.

    A transition is any adjacent pair where primary_emotion differs.
    Each window covers `pad` coarse segments on each side of the boundary.
    Overlapping windows are merged.
    """
    if not timeline or len(timeline) < 2:
        return []
    raw: list = []
    pad_sec = max(1, int(pad)) * int(coarse_sec)
    for i in range(len(timeline) - 1):
        a = timeline[i] or {}
        b = timeline[i + 1] or {}
        if a.get("primary_emotion") != b.get("primary_emotion"):
            boundary = float(a.get("timestamp", 0)) + float(a.get("duration", coarse_sec))
            raw.append((max(0.0, boundary - pad_sec), boundary + pad_sec))
    if not raw:
        return []
    raw.sort(key=lambda w: w[0])
    merged: list = [list(raw[0])]
    for s, e in raw[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(float(s), float(e)) for s, e in merged]


def _merge_adaptive_timeline(
    coarse: list, refined_windows: list
) -> list:
    """Replace coarse entries fully inside any refined window with the
    refined entries (already absolute-timestamped). Coarse entries outside
    every window are kept as-is. Result is sorted by timestamp.
    """
    if not refined_windows:
        return list(coarse or [])
    out: list = []
    for c in coarse or []:
        ts = float(c.get("timestamp", 0))
        dur = float(c.get("duration", 0))
        end = ts + dur
        covered = any(
            ts >= w_start and end <= w_end for (w_start, w_end, _) in refined_windows
        )
        if not covered:
            out.append(c)
    for w_start, _w_end, refined in refined_windows:
        for r in refined or []:
            shifted = dict(r)
            shifted["timestamp"] = float(r.get("timestamp", 0)) + float(w_start)
            out.append(shifted)
    out.sort(key=lambda e: float(e.get("timestamp", 0)))
    return out


@app.get("/health")
async def health() -> Dict[str, Any]:
    analyzer = _ANALYZER
    return {
        "status": "ok",
        "node": "orange",
        "service": "voice_emotion_server",
        "ffmpeg": _have_ffmpeg(),
        "has_transformers": _HAS_TRANSFORMERS,
        "has_torchaudio": _HAS_TORCHAUDIO,
        "has_librosa": _HAS_LIBROSA,
        "has_stt": _have_faster_whisper(),
        "analyzer_mode": analyzer.mode if analyzer else "uninit",
        "auth_required": bool(_AUTH_TOKEN),
    }


@app.post("/voice-emotion")
async def voice_emotion(
    body: VoiceEmotionRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)

    if not _have_ffmpeg():
        raise HTTPException(status_code=503, detail="ffmpeg missing on ORANGE")

    if not (body.audio_url.startswith("http://") or body.audio_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="audio_url must be http(s)")

    with tempfile.TemporaryDirectory(prefix="orange_voice_") as td_str:
        td = Path(td_str)
        src = td / "source.bin"
        wav = td / "audio.wav"

        try:
            await _download(body.audio_url, src)
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="R2 download timeout")
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"R2 download error: {exc}")

        ok = await asyncio.to_thread(_extract_wav, src, wav)
        if not ok:
            raise HTTPException(status_code=500, detail="ffmpeg extract failed")

        try:
            analyzer = _get_analyzer()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"analyzer init failed: {exc}")

        coarse_sec = int(body.segment_seconds)
        try:
            result = await analyzer.analyze_audio(
                str(wav), segment_seconds=coarse_sec
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"analyze_audio error: {exc}")

        # Adaptive boundary refinement: only re-analyze the windows where
        # the coarse pass shows an emotion transition. This concentrates
        # CPU on the moments that carry clinical signal (incongruence,
        # affect shift) instead of paying for fine-grained inference
        # across the 80% of the session where emotion is stable.
        adaptive_sec = body.adaptive_segment_seconds
        try:
            adaptive_sec = int(adaptive_sec) if adaptive_sec else 0
        except Exception:
            adaptive_sec = 0
        if (
            adaptive_sec
            and 0 < adaptive_sec < coarse_sec
            and isinstance(result, dict)
            and not result.get("error")
        ):
            timeline = list(result.get("emotion_timeline") or [])
            windows = _find_transition_windows(
                timeline, coarse_sec, body.adaptive_window_pad
            )
            refined_specs: list = []
            for idx, (w_start, w_end) in enumerate(windows):
                slice_path = td / f"refine_{idx:03d}.wav"
                ok_slice = await asyncio.to_thread(
                    _slice_wav, wav, w_start, w_end, slice_path
                )
                if not ok_slice:
                    continue
                try:
                    sub = await analyzer.analyze_audio(
                        str(slice_path), segment_seconds=adaptive_sec
                    )
                except Exception as sub_exc:
                    print(f"[ORANGE] adaptive slice analyze failed: {sub_exc}")
                    sub = None
                refined_entries = (
                    list(sub.get("emotion_timeline") or [])
                    if isinstance(sub, dict) else []
                )
                refined_specs.append((w_start, w_end, refined_entries))

            if refined_specs:
                merged = _merge_adaptive_timeline(timeline, refined_specs)
                result["emotion_timeline"] = merged
                result["segments_analyzed"] = len(merged)
                result["analysis_mode"] = "adaptive"
                n_ref = len(refined_specs)
                # Top-level alias for dashboards / grep (same as adaptive.windows_refined)
                result["adaptive_refinements"] = n_ref
                result["adaptive"] = {
                    "coarse_segment_sec": coarse_sec,
                    "fine_segment_sec": adaptive_sec,
                    "windows_refined": n_ref,
                    "windows": [
                        {"start": w[0], "end": w[1], "fine_segments": len(w[2])}
                        for w in refined_specs
                    ],
                }

        return result


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Multipart STT for coach campaign ingest. Weights stay on ORANGE."""
    _check_auth(authorization)
    if not _have_ffmpeg():
        raise HTTPException(status_code=503, detail="ffmpeg missing on ORANGE")
    if not _have_faster_whisper():
        raise HTTPException(status_code=503, detail="faster-whisper missing on ORANGE")
    raw = await file.read()
    if not raw or len(raw) < 100:
        raise HTTPException(status_code=400, detail="empty audio")
    with tempfile.TemporaryDirectory(prefix="orange_stt_") as td_str:
        td = Path(td_str)
        src = td / "source.bin"
        wav = td / "audio.wav"
        src.write_bytes(raw)
        ok = await asyncio.to_thread(_extract_wav, src, wav)
        if not ok:
            raise HTTPException(status_code=500, detail="ffmpeg extract failed")
        text = await asyncio.to_thread(_stt_wav, wav)
    if not text:
        raise HTTPException(status_code=503, detail="stt produced no text")
    return {"text": text, "transcript": text}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv("ORANGE_VOICE_HOST", "0.0.0.0"),
        port=int(os.getenv("ORANGE_VOICE_PORT", "8090")),
        log_level="info",
    )
