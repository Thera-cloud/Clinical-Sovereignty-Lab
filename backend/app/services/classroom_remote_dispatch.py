"""
Classroom analysis remote dispatch — three-node compute routing.

GREEN (this backend) is the orchestrator: it owns PostgreSQL, the
classroom_sessions ledger, R2 download, the WebSocket bridge, and the
Night-School push. It must NOT load wav2vec2 weights or run Apple-GPU
visual passes — that work crushes the 6 GB DigitalOcean VPS container
(see the OOM that wiped a recovered session).

Per `.cursor/rules/three-node-sync-discipline.mdc` and
`Crystal_Factory_Firehose_Spec_v1.md`:

    GREEN  (DigitalOcean VPS)  - orchestration, PG, bridge
    ORANGE (Hetzner CAX41)     - sovereign inference, wav2vec2 voice emotion, STT
    BLUE   (Mac via Twin Engine tunnel) - Apple GPU visual + 70B Ollama

This module is the GREEN-side client that hands the heavy parts of
auto_analyze_classroom_video to the right node. If the remote URL is
unset, the helpers return None and the caller falls back to a local
lightweight path (librosa-only voice; basic frame summary).

Env vars (defaults in parens):
    NODE_COLOR                       - "green" | "orange" | "blue" (green)
    CLASSROOM_VOICE_REMOTE_URL       - http://10.13.13.5:8090     (unset)
    CLASSROOM_VISUAL_REMOTE_URL      - http://twin.internal.../classroom/visual (unset)
    CLASSROOM_REMOTE_TIMEOUT_SEC     - per-call HTTP timeout       (300)
    CLASSROOM_REMOTE_AUTH_TOKEN      - shared bearer between nodes (unset)

The remote endpoints contract (kept tiny on purpose):

    POST {CLASSROOM_VOICE_REMOTE_URL}/voice-emotion
        Authorization: Bearer <token>
        Content-Type: application/json
        Body: {"audio_url": "https://r2-presigned/...", "segment_seconds": 10}
        Returns: VoiceEmotionAnalyzer.analyze_audio() dict verbatim.

    POST {CLASSROOM_VISUAL_REMOTE_URL}/classroom/visual
        Authorization: Bearer <token>
        Content-Type: application/json
        Body: {"video_url": "https://r2-presigned/...",
               "interval_seconds": 5, "max_frames": 5}
        Returns: VideoAnalyzer.analyze_classroom_frames() dict verbatim
                 (with frames_analyzed and key_moments).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

_logger = logging.getLogger("classroom_remote_dispatch")


def node_color() -> str:
    return (os.getenv("NODE_COLOR", "green") or "green").strip().lower()


def _voice_url() -> str:
    return (os.getenv("CLASSROOM_VOICE_REMOTE_URL", "") or "").strip().rstrip("/")


def _visual_url() -> str:
    return (os.getenv("CLASSROOM_VISUAL_REMOTE_URL", "") or "").strip().rstrip("/")


def _timeout() -> float:
    try:
        return float(os.getenv("CLASSROOM_REMOTE_TIMEOUT_SEC", "300"))
    except Exception:
        return 300.0


def _auth_headers() -> Dict[str, str]:
    token = (os.getenv("CLASSROOM_REMOTE_AUTH_TOKEN", "") or "").strip()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def voice_emotion_remote_enabled() -> bool:
    return bool(_voice_url())


def visual_remote_enabled() -> bool:
    return bool(_visual_url())


def force_local_librosa_only() -> bool:
    """
    GREEN must never load wav2vec2 weights inside the FastAPI container.
    If we're on GREEN and the ORANGE voice endpoint is not configured,
    the local VoiceEmotionAnalyzer must run in librosa-rules mode only
    (no transformer pipeline load). Honored by VoiceEmotionAnalyzer via
    the VOICE_EMOTION_FORCE_LIBROSA env var, which we set here.
    """
    explicit = (os.getenv("VOICE_EMOTION_FORCE_LIBROSA", "") or "").strip().lower()
    if explicit in ("1", "true", "yes", "on"):
        return True
    if explicit in ("0", "false", "no", "off"):
        return False
    return node_color() == "green" and not voice_emotion_remote_enabled()


async def remote_voice_emotion(
    audio_url: str,
    *,
    segment_seconds: int = 30,
    adaptive_segment_seconds: Optional[int] = 10,
    adaptive_window_pad: int = 1,
) -> Optional[Dict[str, Any]]:
    """
    Dispatch wav2vec2 voice-emotion analysis to ORANGE (Hetzner). Returns
    the analyzer result dict, or None if the remote is unconfigured /
    failed. Caller should fall back to local librosa on None.

    Defaults run an adaptive two-pass: coarse 30s sweep, then 10s
    re-analysis around emotion transitions only. ~3-4 min on ORANGE for a
    1h54m session vs ~10-12 min uniform 10s. To force uniform sampling,
    pass adaptive_segment_seconds=None.
    """
    base = _voice_url()
    if not base:
        return None
    url = f"{base}/voice-emotion"
    payload: Dict[str, Any] = {
        "audio_url": audio_url,
        "segment_seconds": int(segment_seconds),
    }
    if adaptive_segment_seconds and int(adaptive_segment_seconds) > 0:
        payload["adaptive_segment_seconds"] = int(adaptive_segment_seconds)
        payload["adaptive_window_pad"] = int(adaptive_window_pad)
    headers = {"Content-Type": "application/json", **_auth_headers()}

    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            n_adapt = data.get("adaptive_refinements")
            if n_adapt is None and isinstance(data.get("adaptive"), dict):
                n_adapt = (data.get("adaptive") or {}).get("windows_refined")
            _logger.info(
                "[remote_voice_emotion] ORANGE returned %d segments (mode=%s, adaptive_refinements=%s)",
                int(data.get("segments_analyzed", 0) or 0),
                data.get("analysis_mode", "?"),
                n_adapt if n_adapt is not None else "n/a",
            )
            return data
        _logger.warning(
            "[remote_voice_emotion] ORANGE HTTP %d — %s",
            resp.status_code, resp.text[:200],
        )
        return None
    except httpx.TimeoutException:
        _logger.warning("[remote_voice_emotion] ORANGE timeout after %.0fs", _timeout())
        return None
    except Exception as exc:
        _logger.warning("[remote_voice_emotion] ORANGE error: %s", exc)
        return None


async def remote_visual_frames(
    video_url: str,
    *,
    interval_seconds: int = 5,
    max_frames: int = 5,
) -> Optional[Dict[str, Any]]:
    """
    Dispatch visual frame analysis to BLUE (Mac via overseer-manifold
    tunnel). Returns the analyzer result dict, or None if unconfigured /
    failed. Caller should fall back to local VideoAnalyzer on None.
    """
    base = _visual_url()
    if not base:
        return None
    url = f"{base}/classroom/visual"
    payload = {
        "video_url": video_url,
        "interval_seconds": interval_seconds,
        "max_frames": max_frames,
    }
    headers = {"Content-Type": "application/json", **_auth_headers()}

    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            _logger.info(
                "[remote_visual_frames] BLUE returned frames_analyzed=%s",
                data.get("frames_analyzed", 0),
            )
            return data
        _logger.warning(
            "[remote_visual_frames] BLUE HTTP %d — %s",
            resp.status_code, resp.text[:200],
        )
        return None
    except httpx.TimeoutException:
        _logger.warning("[remote_visual_frames] BLUE timeout after %.0fs", _timeout())
        return None
    except Exception as exc:
        _logger.warning("[remote_visual_frames] BLUE error: %s", exc)
        return None


def routing_summary() -> Dict[str, Any]:
    """For /health and dashboard visibility."""
    return {
        "node_color": node_color(),
        "voice_remote": _voice_url() or None,
        "visual_remote": _visual_url() or None,
        "force_local_librosa_only": force_local_librosa_only(),
        "auth_configured": bool(_auth_headers()),
    }
