"""Add three-part narration to hero_video_thera_world_FINAL.mp4.

Generates 3 TTS segments, verifies timing, strips existing audio,
mixes narration with ambient pad, and muxes back into the video.

Run inside Docker:
  cd /app && python3 -m app.sse.hero_narration_mix
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
import subprocess
import math

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [NARRATE] %(levelname)s %(message)s",
)
logger = logging.getLogger("hero_narration")

WORK_DIR = "/tmp/hero_video_slaotqv4"
SOURCE_VIDEO = os.path.join(WORK_DIR, "hero_video_thera_world_FINAL.mp4")
R2_PREFIX = "sovereign-vault/marketing"

SEGMENTS = [
    {
        "name": "narration_act1",
        "text": (
            "There comes a moment when life pulls you somewhere you never "
            "expected to go. And in that moment — you discover you were "
            "never meant to go alone."
        ),
        "instructions": (
            "Speak in a warm, calm, grounded male voice with gentle authority. "
            "Pace: slightly slower than conversational — deliberate and present. "
            "Add a natural breath pause after 'go.' before 'And'. "
            "Place emphasis on the word 'never' in the last line. "
            "Sound like a wise companion, not a narrator."
        ),
        "delay_ms": 200,
        "max_duration": 7.5,
        "window": (0.0, 8.0),
    },
    {
        "name": "narration_act2",
        "text": (
            "This is the Thera-World. Where every battle you face becomes "
            "a story worth telling — and every step forward is yours to keep."
        ),
        "instructions": (
            "Speak in a warm, calm, grounded male voice with gentle authority. "
            "Pace: slightly slower than conversational. "
            "Pause slightly after 'Thera-World.' "
            "Say 'yours to keep' with quiet weight and conviction. "
            "Sound like someone sharing a truth, not reading a script."
        ),
        "delay_ms": 8000,
        "max_duration": 4.8,
        "window": (8.0, 13.0),
    },
    {
        "name": "narration_act3",
        "text": "Where your healing journey begins... but never alone.",
        "instructions": (
            "Speak in a warm, calm, grounded male voice. "
            "Pause for 400 milliseconds between 'begins' and 'but'. "
            "Say 'never alone' softly and warmly — like a promise, not a tagline. "
            "This is the landing moment. Make it feel intimate and assured."
        ),
        "delay_ms": 13000,
        "max_duration": 2.0,
        "window": (13.0, 15.1),
    },
]


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _wav_duration(path: str) -> float:
    p = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=noprint_wrappers=1:nokey=1", path], 10)
    try:
        return float(p.stdout.decode().strip())
    except Exception:
        return 0.0


def _atempo_compress(src: str, dst: str, target_duration: float) -> bool:
    """Compress audio to fit target duration using chained atempo filters.

    FFmpeg atempo only accepts 0.5-100.0 per stage but quality degrades
    above ~2.0, so we chain multiple stages for large ratios.
    """
    actual = _wav_duration(src)
    if actual <= 0 or actual <= target_duration:
        if src != dst:
            import shutil
            shutil.copy(src, dst)
        return True

    ratio = actual / target_duration
    filters = []
    remaining = ratio
    while remaining > 1.01:
        step = min(remaining, 2.0)
        filters.append(f"atempo={step:.4f}")
        remaining /= step

    if not filters:
        if src != dst:
            import shutil
            shutil.copy(src, dst)
        return True

    af = ",".join(filters)
    r = _run([
        "ffmpeg", "-y", "-i", src,
        "-af", af,
        "-ac", "2", "-ar", "44100",
        dst,
    ], 30)
    if r.returncode != 0:
        logger.error("atempo failed: %s", r.stderr.decode()[-200:])
        return False
    new_dur = _wav_duration(dst)
    logger.info("  Compressed %.2fs → %.2fs (ratio %.2fx) via %s",
                 actual, new_dur, ratio, af)
    return True


def _generate_ambient(duration: float, output_path: str) -> bool:
    """Generate a soft wind/nature ambient pad using FFmpeg's noise filter."""
    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-t", str(duration),
        "-i", (
            "anoisesrc=d={dur}:c=pink:r=44100:a=0.015,"
            "lowpass=f=800,highpass=f=100,"
            "afade=t=in:st=0:d=2,"
            "afade=t=out:st={fade_out}:d=2"
        ).format(dur=duration, fade_out=max(0, duration - 2)),
        "-ac", "2", "-ar", "44100",
        output_path,
    ], 30)
    return os.path.exists(output_path) and os.path.getsize(output_path) > 100


async def _generate_tts(text: str, instructions: str, output_path: str) -> bool:
    from app.sse.trailer_generator import _azure_tts
    audio = await _azure_tts(text=text, voice="ash", instructions=instructions)
    if not audio:
        logger.error("TTS generation failed for %s", output_path)
        return False
    with open(output_path, "wb") as f:
        f.write(audio)
    logger.info("  TTS → %d KB → %s", len(audio) // 1024, os.path.basename(output_path))
    return True


async def main() -> dict:
    report: dict = {"segments": {}, "timing_ok": False, "final": None}

    if not os.path.exists(SOURCE_VIDEO):
        logger.error("Source video not found: %s", SOURCE_VIDEO)
        report["final"] = {"error": "source video missing"}
        return report

    # ── STEP 1: Generate TTS segments ────────────────────────────────────
    logger.info("═" * 60)
    logger.info("STEP 1 — Generate Narration Audio (3 segments)")
    logger.info("═" * 60)

    wav_paths: dict[str, str] = {}

    for seg in SEGMENTS:
        path = os.path.join(WORK_DIR, f"{seg['name']}.wav")
        ok = await _generate_tts(seg["text"], seg["instructions"], path)
        if ok:
            dur = _wav_duration(path)
            wav_paths[seg["name"]] = path
            report["segments"][seg["name"]] = {
                "duration_s": round(dur, 2),
                "max_allowed": seg["max_duration"],
                "fits": dur <= seg["max_duration"],
                "window": seg["window"],
            }
            logger.info("  %s: %.2fs (max %.1fs) %s",
                         seg["name"], dur, seg["max_duration"],
                         "OK" if dur <= seg["max_duration"] else "TOO LONG")
        else:
            report["segments"][seg["name"]] = {"error": "TTS failed"}

    # ── STEP 2: Verify timing and compress to fit ─────────────────────────
    logger.info("═" * 60)
    logger.info("STEP 2 — Verify Timing & Compress")
    logger.info("═" * 60)

    for seg in SEGMENTS:
        name = seg["name"]
        info = report["segments"].get(name, {})
        if "error" in info or name not in wav_paths:
            continue

        raw_dur = info.get("duration_s", 0)
        target = seg["max_duration"]

        if raw_dur > target:
            src = wav_paths[name]
            compressed = os.path.join(WORK_DIR, f"{name}_fit.wav")
            padding = 0.2
            ok = _atempo_compress(src, compressed, target - padding)
            if ok and os.path.exists(compressed):
                new_dur = _wav_duration(compressed)
                wav_paths[name] = compressed
                report["segments"][name] = {
                    "raw_duration_s": round(raw_dur, 2),
                    "compressed_duration_s": round(new_dur, 2),
                    "max_allowed": target,
                    "fits": new_dur <= target,
                    "compression_ratio": round(raw_dur / max(new_dur, 0.1), 2),
                    "window": seg["window"],
                }
            else:
                logger.warning("  %s compression failed — using raw audio", name)

    all_fit = all(
        report["segments"].get(seg["name"], {}).get("fits", False)
        for seg in SEGMENTS
    )
    report["timing_ok"] = all_fit

    for seg in SEGMENTS:
        info = report["segments"].get(seg["name"], {})
        comp_dur = info.get("compressed_duration_s", info.get("duration_s", 0))
        logger.info("  %s: %.2fs → %.2fs / %.1fs window — %s",
                     seg["name"],
                     info.get("raw_duration_s", info.get("duration_s", 0)),
                     comp_dur,
                     seg["max_duration"],
                     "PASS" if info.get("fits") else "FAIL")

    if len(wav_paths) < 3:
        logger.error("Missing TTS segments — cannot proceed")
        report["final"] = {"error": "missing TTS segments"}
        return report

    # ── STEP 3: Mix narration into video ─────────────────────────────────
    logger.info("═" * 60)
    logger.info("STEP 3 — Mix Narration Into Video")
    logger.info("═" * 60)

    # 3a: Strip existing audio
    no_audio = os.path.join(WORK_DIR, "hero_video_no_audio.mp4")
    _run(["ffmpeg", "-y", "-i", SOURCE_VIDEO, "-an", "-c:v", "copy", no_audio])
    logger.info("  3a: Stripped audio → %s", os.path.basename(no_audio))

    # 3b: Get source video duration for ambient
    vid_dur = 15.1
    try:
        p = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                  "-of", "default=noprint_wrappers=1:nokey=1", SOURCE_VIDEO], 10)
        vid_dur = float(p.stdout.decode().strip())
    except Exception:
        pass

    # 3c: Generate ambient pad
    ambient_path = os.path.join(WORK_DIR, "ambient.wav")
    ambient_ok = _generate_ambient(vid_dur, ambient_path)
    report["ambient_added"] = ambient_ok
    if ambient_ok:
        logger.info("  3c: Ambient pad generated (%.1fs)", vid_dur)
    else:
        logger.warning("  3c: Ambient generation failed — narration only")

    # 3b+3d: Mix all narration segments with delay offsets + ambient
    mixed_audio = os.path.join(WORK_DIR, "mixed_narration.wav")

    filter_inputs = []
    filter_parts = []
    input_idx = 0

    for seg in SEGMENTS:
        name = seg["name"]
        if name not in wav_paths:
            continue
        filter_inputs.extend(["-i", wav_paths[name]])
        delay = seg["delay_ms"]
        filter_parts.append(f"[{input_idx}]adelay={delay}|{delay}[d{input_idx}]")
        input_idx += 1

    if ambient_ok:
        filter_inputs.extend(["-i", ambient_path])
        ambient_idx = input_idx
        filter_parts.append(f"[{ambient_idx}]volume=0.08[amb]")
        mix_sources = "".join(f"[d{i}]" for i in range(input_idx)) + "[amb]"
        n_inputs = input_idx + 1
    else:
        mix_sources = "".join(f"[d{i}]" for i in range(input_idx))
        n_inputs = input_idx

    filter_parts.append(
        f"{mix_sources}amix=inputs={n_inputs}:duration=longest:dropout_transition=2[out]"
    )
    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *filter_inputs,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-ac", "2", "-ar", "44100",
        mixed_audio,
    ]

    r = _run(cmd, 60)
    if r.returncode != 0:
        logger.error("  Audio mix failed: %s", r.stderr.decode()[-300:])
        report["final"] = {"error": "audio mix failed"}
        return report
    logger.info("  3b+3d: Mixed narration → %s", os.path.basename(mixed_audio))

    # 3d: Mux back into video
    final_path = os.path.join(WORK_DIR, "hero_video_thera_world_NARRATED.mp4")
    _run([
        "ffmpeg", "-y",
        "-i", no_audio,
        "-i", mixed_audio,
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v", "-map", "1:a",
        "-shortest",
        "-movflags", "+faststart",
        final_path,
    ], 120)

    if not os.path.exists(final_path) or os.path.getsize(final_path) < 10000:
        logger.error("  Final mux failed")
        report["final"] = {"error": "final mux failed"}
        return report

    size = os.path.getsize(final_path)
    final_dur = 0.0
    try:
        p = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                  "-of", "default=noprint_wrappers=1:nokey=1", final_path], 10)
        final_dur = float(p.stdout.decode().strip())
    except Exception:
        pass

    # ── STEP 4: Quality check ────────────────────────────────────────────
    logger.info("═" * 60)
    logger.info("STEP 4 — Quality Check")
    logger.info("═" * 60)

    under_15mb = size < 15 * 1024 * 1024

    if not under_15mb:
        logger.warning("  File is %.1fMB — re-encoding video at lower bitrate", size / 1024 / 1024)
        reenc_path = os.path.join(WORK_DIR, "hero_video_thera_world_NARRATED_reenc.mp4")
        _run([
            "ffmpeg", "-y",
            "-i", final_path,
            "-c:v", "libx264", "-b:v", "2000k", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            reenc_path,
        ], 300)
        if os.path.exists(reenc_path):
            os.replace(reenc_path, final_path)
            size = os.path.getsize(final_path)
            under_15mb = size < 15 * 1024 * 1024
            logger.info("  Re-encoded → %.1fMB", size / 1024 / 1024)

    logger.info("  Duration: %.2fs (original: %.2fs)", final_dur, vid_dur)
    logger.info("  File size: %.1fMB (under 15MB: %s)", size / 1024 / 1024, under_15mb)

    # ── STEP 5: Store and deliver ────────────────────────────────────────
    logger.info("═" * 60)
    logger.info("STEP 5 — Store and Deliver")
    logger.info("═" * 60)

    from app.sse.infrastructure.r2_storage import store_bytes
    with open(final_path, "rb") as f:
        final_bytes = f.read()

    r2_url = await store_bytes(
        final_bytes,
        f"{R2_PREFIX}/hero_video_thera_world_NARRATED.mp4",
        "video/mp4",
    )

    report["final"] = {
        "r2_url": r2_url,
        "local_path": final_path,
        "file_size_bytes": size,
        "file_size_mb": round(size / 1024 / 1024, 2),
        "under_15mb": under_15mb,
        "duration_seconds": round(final_dur, 2),
        "ambient_added": ambient_ok,
    }

    logger.info("  R2: %s", r2_url[:80])
    logger.info("  Local: %s", final_path)
    logger.info("  Size: %.1fMB | Duration: %.2fs", size / 1024 / 1024, final_dur)

    # Store report
    await store_bytes(
        json.dumps(report, indent=2, default=str).encode(),
        f"{R2_PREFIX}/hero_narration_report.json",
        "application/json",
    )

    logger.info("═" * 60)
    logger.info("DONE — docker cp command:")
    logger.info("  docker cp nate_backend:%s ~/Desktop/", final_path)
    logger.info("═" * 60)

    return report


if __name__ == "__main__":
    result = asyncio.run(main())
    print(json.dumps(result, indent=2, default=str))
