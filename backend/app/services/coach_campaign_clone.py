"""Campaign-only XTTS clone. Never touches the live-call voice ladder."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("coach_campaign_clone")


def clone_enabled() -> bool:
    return os.getenv("ENABLE_COACH_VOICE_CLONE", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def voice_id_for(coach_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", (coach_id or "").strip())[:40]
    return f"coach_{safe or 'unknown'}"


async def register_clone(
    media: bytes,
    coach_id: str,
    *,
    content_type: str = "audio/wav",
) -> bool:
    """Upload coach-self reference to campaign XTTS. Does not start Hetzner live-call XTTS."""
    if not clone_enabled() or not media or len(media) < 200:
        return False
    vid = voice_id_for(coach_id)
    ext = "webm"
    if "wav" in (content_type or ""):
        ext = "wav"
    elif "mpeg" in (content_type or "") or "mp3" in (content_type or ""):
        ext = "mp3"
    elif "mp4" in (content_type or "") or "m4a" in (content_type or ""):
        ext = "m4a"
    try:
        from app.services.sovereign_tts import upload_voice_bytes

        return await upload_voice_bytes(media, vid, filename=f"{vid}.{ext}")
    except Exception as exc:
        logger.warning("campaign clone register skipped: %s", exc)
        return False


async def synthesize_campaign(
    text: str,
    coach_id: str,
    *,
    style: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[bytes], str]:
    """XTTS clone when flagged and reachable; Edge/Azure fallback is not a clone."""
    body = (text or "").strip()
    if not body:
        return None, "empty"
    style = style or {}
    vid = str(style.get("clone_voice_id") or voice_id_for(coach_id))
    if clone_enabled():
        try:
            from app.services.sovereign_tts import synthesize

            wav = await synthesize(body, voice_id=vid)
            if wav:
                return wav, "xtts_clone"
        except Exception as exc:
            logger.warning("campaign XTTS skipped: %s", exc)
    try:
        from app.services.edge_tts_service import synthesize as edge_synth

        mp3 = await edge_synth(body)
        if mp3:
            return mp3, "edge_fallback"
    except Exception as exc:
        logger.warning("campaign Edge TTS skipped: %s", exc)
    return None, "unavailable"


def wrap_audio_as_mp4(audio: bytes) -> Optional[bytes]:
    """Still + audio for LinkedIn video share. Campaign only."""
    if not audio:
        return None
    import subprocess

    suffix = ".wav" if audio[:4] == b"RIFF" else ".mp3"
    src = dst = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
            fh.write(audio)
            src = fh.name
        dst = src + ".mp4"
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x050505:s=1080x1080:r=1",
            "-i",
            src,
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            dst,
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=90)
        if proc.returncode != 0 or not os.path.exists(dst):
            logger.warning("campaign ffmpeg wrap failed: %s", (proc.stderr or b"")[:200])
            return None
        with open(dst, "rb") as out:
            return out.read()
    except Exception as exc:
        logger.warning("campaign ffmpeg wrap skipped: %s", exc)
        return None
    finally:
        for path in (src, dst):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
