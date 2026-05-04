#!/usr/bin/env python3
"""Family Sanctuary hero v9 — single continuous Nate narration over scored 18.3s base.

Azure gpt-4o-mini-tts (voice ash) → −3 dBFS peak mono → duck scored music + mix + loudnorm → mux.

Run in ``nate_backend``::

  docker cp family_sanctuary_v8_scored_18s.mp4 nate_backend:/tmp/
  docker cp backend/scripts/family_sanctuary_hero_v9.py nate_backend:/tmp/
  docker exec -w /app nate_backend env PYTHONPATH=/app python3 /tmp/family_sanctuary_hero_v9.py

Env:
  FS_V9_SCORED_MP4 — default /tmp/family_sanctuary_v8_scored_18s.mp4
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

if "/app" not in sys.path:
    sys.path.insert(0, "/app")

SCORED_DEFAULT = "/tmp/family_sanctuary_v8_scored_18s.mp4"
NARR_LOCAL = "/tmp/nate_narration_v9.wav"
MUSIC_LOCAL = "/tmp/music_only_v9.wav"
AUDIO_MIX_LOCAL = "/tmp/final_audio_v9.wav"
OUT_MP4_LOCAL = "/tmp/family_sanctuary_hero_v9.mp4"
NARR_R2_KEY = "sse/trailer/family_sanctuary/narration/nate_full_v9.wav"
FINAL_R2_KEY = "sse/trailer/family_sanctuary/final/hero_v9.mp4"
BUCKET = os.environ.get("R2_DEFAULT_BUCKET", "nate-vault").strip()

SCRIPT = (
    "A family needs to unite. Then something unexpected happens. "
    "We get separated between two realities of thought. Unified we stand "
    "together against whatever is against us. Finding your glow of a "
    "family is a Kingdom on the horizon."
)

TARGET_START_MS = 500
LAST_WORD_TAIL_S = 1.0  # narration should leave ~1s before video end


def _run(cmd: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)


def _ffprobe_duration(path: str) -> float:
    r = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        timeout=30,
    )
    try:
        return float((r.stdout or "").strip())
    except ValueError:
        return 0.0


def _s3_client():
    import boto3
    from botocore.config import Config

    account = os.environ.get("R2_ACCOUNT_ID", "").strip()
    endpoint = os.environ.get("R2_ENDPOINT_URL", "").strip()
    if not endpoint and account:
        endpoint = f"https://{account}.r2.cloudflarestorage.com"
    if not endpoint:
        raise RuntimeError("Set R2_ACCOUNT_ID (derive endpoint); do not rely on R2_ENDPOINT_URL.")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"].strip(),
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"].strip(),
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "adaptive"}),
        region_name="auto",
    )


def _r2_upload(s3, local: str, key: str, content_type: str) -> None:
    s3.upload_file(local, BUCKET, key, ExtraArgs={"ContentType": content_type})


def _normalize_peak_dbfs(inp: str, outp: str, target_dbfs: float = -3.0) -> None:
    r = _run(["ffmpeg", "-i", inp, "-af", "volumedetect", "-f", "null", "-"], timeout=60)
    err = r.stderr or ""
    m = re.search(r"max_volume:\s*([-\d.]+)\s*dB", err)
    if not m:
        shutil.copyfile(inp, outp)
        return
    peak_db = float(m.group(1))
    gain_db = target_dbfs - peak_db
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            inp,
            "-af",
            f"volume={gain_db:.4f}dB",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-sample_fmt",
            "s16",
            outp,
        ],
        check=True,
        timeout=120,
    )


async def _tts_narration(text: str, speed: float, out_wav: str) -> None:
    from app.sse.trailer_generator import _azure_tts

    audio = await _azure_tts(
        text=text,
        voice="ash",
        instructions=(
            "Cinematic trailer narrator. Confident, deliberate pace with clear natural "
            "pauses between sentences. Do not rush. Warm authority, not hype."
        ),
        response_format="wav",
        speed=float(speed),
    )
    if not audio:
        raise RuntimeError("Azure TTS failed for Nate narration v9")
    raw = out_wav + ".raw.wav"
    with open(raw, "wb") as f:
        f.write(audio)
    _normalize_peak_dbfs(raw, out_wav)
    try:
        os.remove(raw)
    except OSError:
        pass


async def _generate_narration_with_duration_checks(narr_path: str) -> float:
    """Return final narration duration (seconds). Retries speed per brief."""
    speed = 1.0
    for attempt in range(8):
        await _tts_narration(SCRIPT, speed, narr_path)
        d = _ffprobe_duration(narr_path)
        print(f"[FS-V9] narration attempt {attempt + 1} speed={speed} duration={d:.3f}s")

        if d < 14.0:
            speed = 0.95
            continue
        if d > 19.0:
            speed = 1.05
            continue
        if d > 16.8:
            if speed <= 1.0:
                speed = 1.05
            else:
                speed = round(speed + 0.05, 2)
                if speed > 1.25:
                    break
            print(f"[FS-V9] narration > 16.8s — retry speed={speed}")
            continue
        return d

    d = _ffprobe_duration(narr_path)
    if d > 16.8:
        raise SystemExit(
            f"[FS-V9] ABORT: narration still {d:.2f}s after retries; max slot 16.8s "
            "(start 0.5s, last word ~1s before 18.3s end)."
        )
    return d


def _extract_music(scored_mp4: str, out_wav: str) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            scored_mp4,
            "-vn",
            "-c:a",
            "pcm_s16le",
            out_wav,
        ],
        check=True,
        timeout=120,
    )


def _build_mixed_audio(
    music_wav: str,
    narr_wav: str,
    video_dur: float,
    out_wav: str,
) -> None:
    """Duck music with sidechain from delayed voice; mix; loudnorm; trim to video_dur."""
    d = f"{video_dur:.6f}"
    # Music trimmed to exact container length; voice delayed 500 ms, stereo duplicate;
    # SC ducks music ~9 dB when voice present; voice +3 dB-ish via volume=1.4; loudnorm web.
    fc = (
        f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo:sample_fmts=fltp,"
        f"atrim=0:{d},asetpts=PTS-STARTPTS[music];"
        f"[1:a]aformat=sample_rates=44100:sample_fmts=fltp,pan=stereo|c0=c0|c1=c0[a1];"
        f"[a1]asplit[vraw][vraw2];"
        f"[vraw]adelay={TARGET_START_MS}|{TARGET_START_MS},asetpts=PTS-STARTPTS[vsc];"
        f"[music][vsc]sidechaincompress=threshold=0.05:ratio=4:attack=20:release=400:makeup=0[duck];"
        f"[vraw2]adelay={TARGET_START_MS}|{TARGET_START_MS},asetpts=PTS-STARTPTS[vd];"
        f"[vd]volume=1.4[v_loud];"
        f"[duck][v_loud]amix=inputs=2:duration=first:normalize=0[mix];"
        f"[mix]loudnorm=I=-15:TP=-1.5:LRA=7[ln];"
        f"[ln]atrim=0:{d},asetpts=PTS-STARTPTS[out]"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            music_wav,
            "-i",
            narr_wav,
            "-filter_complex",
            fc,
            "-map",
            "[out]",
            "-c:a",
            "pcm_s16le",
            "-ar",
            "44100",
            "-ac",
            "2",
            out_wav,
        ],
        check=True,
        timeout=600,
    )


def main() -> None:
    scored = os.environ.get("FS_V9_SCORED_MP4", SCORED_DEFAULT).strip()
    if not os.path.isfile(scored):
        raise SystemExit(f"Missing scored base: {scored}")

    video_dur = _ffprobe_duration(scored)
    print(f"[FS-V9] scored video duration {video_dur:.3f}s")
    max_narr_dur = video_dur - (TARGET_START_MS / 1000.0) - LAST_WORD_TAIL_S
    max_end = video_dur - LAST_WORD_TAIL_S
    print(f"[FS-V9] target voice start {TARGET_START_MS}ms; max narration end {max_end:.3f}s; slot {max_narr_dur:.3f}s")

    work = tempfile.mkdtemp(prefix="fs_v9_")
    try:
        narr_work = os.path.join(work, "nate.wav")

        narr_dur = asyncio.run(_generate_narration_with_duration_checks(narr_work))

        voice_end = TARGET_START_MS / 1000.0 + narr_dur
        if voice_end > max_end + 0.05:
            raise SystemExit(
                f"[FS-V9] ABORT: narration ends ~{voice_end:.2f}s > max {max_end:.2f}s "
                f"(need ~{LAST_WORD_TAIL_S}s tail). Regenerate faster or shorten script."
            )

        shutil.copyfile(narr_work, NARR_LOCAL)
        s3 = _s3_client()
        _r2_upload(s3, NARR_LOCAL, NARR_R2_KEY, "audio/wav")
        print("[FS-V9] Uploaded narration", NARR_R2_KEY)

        _extract_music(scored, MUSIC_LOCAL)
        print("[FS-V9] extracted music bed →", MUSIC_LOCAL)

        _build_mixed_audio(MUSIC_LOCAL, NARR_LOCAL, video_dur, AUDIO_MIX_LOCAL)
        print("[FS-V9] mixed audio →", AUDIO_MIX_LOCAL)

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                scored,
                "-i",
                AUDIO_MIX_LOCAL,
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-shortest",
                "-movflags",
                "+faststart",
                OUT_MP4_LOCAL,
            ],
            check=True,
            timeout=300,
        )

        out_dur = _ffprobe_duration(OUT_MP4_LOCAL)
        print(f"[FS-V9] FINAL mp4 duration {out_dur:.3f}s → {OUT_MP4_LOCAL}")

        pr = _run(
            ["ffprobe", "-v", "error", "-show_streams", "-print_format", "json", OUT_MP4_LOCAL],
            timeout=30,
        )

        meta = json.loads(pr.stdout or "{}")
        streams = meta.get("streams") or []
        v = [s for s in streams if s.get("codec_type") == "video"]
        a = [s for s in streams if s.get("codec_type") == "audio"]
        if not v or not a:
            raise SystemExit("[FS-V9] mux missing video or audio stream")
        print(
            "[FS-V9] streams:",
            "v=",
            v[0].get("codec_name"),
            v[0].get("width"),
            v[0].get("height"),
            v[0].get("r_frame_rate"),
            "a=",
            a[0].get("codec_name"),
            a[0].get("sample_rate"),
        )

        _r2_upload(s3, OUT_MP4_LOCAL, FINAL_R2_KEY, "video/mp4")
        print("[FS-V9] Uploaded", FINAL_R2_KEY)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
