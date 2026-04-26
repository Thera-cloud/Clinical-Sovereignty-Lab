"""
BLUE Node — Classroom Visual Analysis Server (Mac, Apple Silicon GPU).

This is the visual frame endpoint that GREEN's classroom_remote_dispatch
calls when CLASSROOM_VISUAL_REMOTE_URL is set. BLUE owns the Apple
M-series GPU and is the natural home for vision passes — see
`.cursor/rules/cloudflare-tunnel-twin-engine.mdc`:

    "Mac (Twin) Owns: 70B model weights, Apple GPU, XTTS voice refs"
    "Mac (Twin) Serves: Deep inference, voice clone TTS, batch coherence"

Deployment topology:
    Local bind:       http://127.0.0.1:8200
    Public path:      Cloudflare Tunnel (Little Nate Twin Engine, d40e5315...)
                      → VPC service `classroom-visual-vpc` (TBD)
                      → 127.0.0.1:8200 on this Mac
    LaunchDaemon:     com.sovereignsanctuary.classroom-visual.plist

Endpoints:
    GET  /health             — liveness + capability gates (cv2, moviepy, mps)
    POST /classroom/visual   — frame extraction + analysis on the Mac GPU

Request body for POST /classroom/visual:
    {
      "video_url":         "https://r2-presigned/.../recording.mp4",
      "interval_seconds":  5,
      "max_frames":        5
    }

Response body (matches VideoAnalyzer.analyze_classroom_frames + extras):
    {
      "coaching_insights":         "...",
      "key_moments":               [...],
      "therapeutic_presence_score": 7.5,
      "frames_analyzed":           5,
      "node":                      "blue",
      "device":                    "mps" | "cpu"
    }

Authentication:
    If CLASSROOM_REMOTE_AUTH_TOKEN is set, requests must carry
    `Authorization: Bearer <token>`. The tunnel route should ALSO be
    behind a Cloudflare Access service-token policy — see Rule #3 in
    `cloudflare-tunnel-twin-engine.mdc`.

Run for testing:
    cd backend/scripts/blue
    python -m venv .venv && source .venv/bin/activate
    pip install fastapi uvicorn httpx pydantic opencv-python numpy moviepy
    python classroom_visual_server.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Capability probes — kept cheap. Heavy models load lazily on first request.
# ---------------------------------------------------------------------------

_HAS_CV2 = False
_HAS_MOVIEPY = False
_HAS_MPS = False
try:
    import cv2  # noqa: F401
    _HAS_CV2 = True
except Exception:
    pass
try:
    from moviepy.editor import VideoFileClip  # noqa: F401
    _HAS_MOVIEPY = True
except Exception:
    pass
try:
    import torch
    _HAS_MPS = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
except Exception:
    _HAS_MPS = False


# ---------------------------------------------------------------------------
# Reuse the GREEN-side VideoAnalyzer so the result shape stays identical.
#
# Imported by file path to avoid pulling app.services.__init__ (which loads
# DB/Stripe/etc not present on this Mac). The setup script copies
# video_analyzer.py next to this server file so it's self-sufficient.
# ---------------------------------------------------------------------------

import importlib.util as _ilu

_HERE = Path(__file__).resolve().parent

_LOCAL_ANALYZER = _HERE / "video_analyzer.py"
_REPO_ANALYZER = _HERE.parent.parent / "app" / "services" / "video_analyzer.py"
_analyzer_path = _LOCAL_ANALYZER if _LOCAL_ANALYZER.exists() else _REPO_ANALYZER

if not _analyzer_path.exists():  # pragma: no cover
    raise RuntimeError(
        f"video_analyzer.py not found at {_LOCAL_ANALYZER} or {_REPO_ANALYZER}"
    )


def _load_video_analyzer_module():
    # video_analyzer.py at the top level imports `from app.config import settings`.
    # Provide a tiny stub so the module loads cleanly outside the GREEN backend.
    if "app" not in sys.modules:
        import types as _types
        _app = _types.ModuleType("app")
        _config = _types.ModuleType("app.config")
        _settings = _types.SimpleNamespace()
        _config.settings = _settings  # type: ignore[attr-defined]
        _app.config = _config  # type: ignore[attr-defined]
        sys.modules["app"] = _app
        sys.modules["app.config"] = _config

    spec = _ilu.spec_from_file_location("video_analyzer", str(_analyzer_path))
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"could not build import spec for {_analyzer_path}")
    mod = _ilu.module_from_spec(spec)
    sys.modules["video_analyzer"] = mod
    spec.loader.exec_module(mod)
    return mod


_video_mod = _load_video_analyzer_module()
VideoAnalyzer = _video_mod.VideoAnalyzer  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Auth + helpers
# ---------------------------------------------------------------------------

_AUTH_TOKEN = (os.getenv("CLASSROOM_REMOTE_AUTH_TOKEN", "") or "").strip()
_DOWNLOAD_TIMEOUT = float(os.getenv("BLUE_DOWNLOAD_TIMEOUT_SEC", "900"))


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


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    print("[BLUE] classroom_visual_server starting")
    print(f"  has_cv2={_HAS_CV2} has_moviepy={_HAS_MOVIEPY} has_mps={_HAS_MPS}")
    print(f"  has_ffmpeg={_have_ffmpeg()}  auth_required={bool(_AUTH_TOKEN)}")
    yield
    print("[BLUE] classroom_visual_server stopping")


app = FastAPI(title="BLUE Classroom Visual Server", lifespan=_lifespan)


class VisualRequest(BaseModel):
    video_url: str
    interval_seconds: int = 5
    max_frames: int = 5


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "node": "blue",
        "service": "classroom_visual_server",
        "ffmpeg": _have_ffmpeg(),
        "has_cv2": _HAS_CV2,
        "has_moviepy": _HAS_MOVIEPY,
        "has_mps": _HAS_MPS,
        "device": "mps" if _HAS_MPS else "cpu",
        "auth_required": bool(_AUTH_TOKEN),
    }


def _run_visual_sync(video_path: Path, interval: int, max_frames: int) -> Dict[str, Any]:
    analyzer = VideoAnalyzer()
    frames = analyzer.extract_frames(
        video_path, interval_seconds=interval, max_frames=max_frames
    )
    if not frames:
        return {
            "coaching_insights": "No frames extracted on BLUE (codec or read error).",
            "key_moments": [],
            "therapeutic_presence_score": 6.0,
            "frames_analyzed": 0,
        }
    return analyzer.analyze_classroom_frames(frames)


@app.post("/classroom/visual")
async def classroom_visual(
    body: VisualRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)

    if not (_HAS_CV2 or _HAS_MOVIEPY):
        raise HTTPException(
            status_code=503,
            detail="neither opencv-python nor moviepy available on BLUE",
        )
    if not (body.video_url.startswith("http://") or body.video_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="video_url must be http(s)")

    with tempfile.TemporaryDirectory(prefix="blue_visual_") as td_str:
        td = Path(td_str)
        src = td / "source.mp4"

        try:
            await _download(body.video_url, src)
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="R2 download timeout")
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"R2 download error: {exc}")

        try:
            result = await asyncio.to_thread(
                _run_visual_sync,
                src,
                int(body.interval_seconds),
                int(body.max_frames),
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"visual analyzer error: {exc}")

    result["node"] = "blue"
    result["device"] = "mps" if _HAS_MPS else "cpu"
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv("BLUE_VISUAL_HOST", "127.0.0.1"),
        port=int(os.getenv("BLUE_VISUAL_PORT", "8200")),
        log_level="info",
    )
