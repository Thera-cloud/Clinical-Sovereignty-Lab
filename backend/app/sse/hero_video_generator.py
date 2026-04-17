"""Landing page hero video generator — 15-second cinematic sequence.

Three acts:
  ACT 1 (0-8s): The Pull — two women drawn through a mirror into Thera-World
  ACT 2 (8-13s): The World Reveal — epic pan of the full fantasy landscape
  ACT 3 (13-15s): The Title — fire text + voice tagline

Run inside Docker:
  docker exec nate_backend python3 /app/app/sse/hero_video_generator.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [HERO] %(levelname)s %(message)s",
)
logger = logging.getLogger("hero_video")

R2_PREFIX = "sovereign-vault/marketing"

# ── Character Descriptions ────────────────────────────────────────────────

YOUNG_WOMAN = (
    "young woman late teens/early 20s, soft wildflower aesthetic, "
    "petal-like flowing dress in muted lavender and cream, "
    "vines and small flowers woven through long auburn hair, "
    "wide uncertain eyes balancing wonder and vulnerability, bare feet"
)

OLDER_WOMAN = (
    "woman late 30s/early 40s, guardian-warrior blend, "
    "strong but feminine build, worn dark traveling cloak over layered armor, "
    "determined fierce expression, short dark hair, weathered leather bracers"
)

STYLE = (
    "Cinematic painterly fantasy illustration, 16:9 widescreen framing, "
    "dramatic volumetric lighting, deep jewel tones — midnight blue, "
    "deep emerald, burning amber, breathtaking otherworldly atmosphere, "
    "film grain subtle, epic fantasy art, no text, no words, no lettering — "
)

# ── Keyframe Prompts ──────────────────────────────────────────────────────

KEYFRAMES = {
    "act1_mirror": (
        f"{STYLE}"
        f"Two women stand before an enormous ornate ancient mirror in a fog-filled "
        f"stone chamber. The mirror surface ripples like mercury revealing infinite "
        f"dark space with stars beyond. "
        f"The younger woman ({YOUNG_WOMAN}) reaches toward the mirror with wonder and fear. "
        f"The older woman ({OLDER_WOMAN}) stands ready behind her with fierce protective intensity. "
        f"Deep jewel tone lighting — midnight blue stone walls, golden candlelight, "
        f"mercury-silver mirror glow. Camera: eye level, facing mirror, both women in frame."
    ),
    "act1_landing": (
        f"{STYLE}"
        f"Two women have just landed in a vast twilight fantasy landscape. "
        f"The older woman ({OLDER_WOMAN}) catches the younger ({YOUNG_WOMAN}), "
        f"both looking out at the world. "
        f"In the far distance: castle ruins lit by fire, dark storm clouds, "
        f"flashes of battle on the horizon. "
        f"Ancient forests to the sides, a river of light cutting through the terrain, "
        f"twilight sky with stars appearing. "
        f"Camera: wide shot from behind them, the world sprawling ahead."
    ),
    "act2_world": (
        f"{STYLE}"
        f"EPIC WIDE AERIAL PANORAMA of a vast fantasy world from high above. "
        f"Ancient forests on the left with towering crystalline trees. "
        f"A glowing sacred sanctuary city of golden spires in the center distance. "
        f"Mountains and dark storm on the right where a war rages with distant fire. "
        f"A luminous river of light cuts through the landscape. "
        f"Small archetype figures visible throughout — warriors, healers, travelers. "
        f"Two tiny women figures at the bottom together, looking out. "
        f"Warm golden light breaking through storm clouds from the sanctuary. "
        f"Camera: very high, looking down, the full world visible."
    ),
}

MOTION = {
    "act1": (
        "Dramatic cinematic sequence: camera starts close on two women before "
        "an ancient mirror, the mirror surface ripples and pulls the younger "
        "woman in, the older leaps after, they fall through fractal mirror "
        "space with reflections swirling, light bending and warping, then "
        "they burst through into a vast twilight landscape, landing together, "
        "looking out at a distant war on the horizon. Camera moves from "
        "intimate close-up to epic wide reveal."
    ),
    "act2": (
        "Slow majestic camera pullback and upward rise — starting at ground "
        "level with two small figures, slowly rising higher to reveal the "
        "immense scale of a fantasy world. Ancient forests stretch left, "
        "a glowing sanctuary city shines center, mountains and storm rage "
        "right. A river of light winds through everything. Smooth, grand, "
        "meditative camera movement revealing infinite possibility."
    ),
}

VOICE_TEXT = "Where your healing journey begins... but never alone."
VOICE_INSTRUCTIONS = (
    "Speak in a warm, feminine, resonant voice. Calm and assured, maternal "
    "but not weak. Slightly breathy, intimate quality. Natural human cadence. "
    "Pause for 400 milliseconds after 'begins' before saying 'but never alone.' "
    "The last three words should carry quiet conviction."
)


# ── Image Generation ──────────────────────────────────────────────────────

async def _generate_keyframe(name: str, prompt: str) -> tuple[str, bytes]:
    from app.sse.infrastructure.grok_imagine_client import generate_image, GROK_IMAGINE_LOCK
    from app.sse.infrastructure.r2_storage import store_image

    logger.info("Generating keyframe: %s", name)
    async with GROK_IMAGINE_LOCK:
        img = await generate_image(prompt)
    r2_url = await store_image(img, f"{R2_PREFIX}/keyframes/{name}.png")
    logger.info("  %s → %d KB, stored", name, len(img) // 1024)
    return r2_url, img


# ── Video Generation ──────────────────────────────────────────────────────

async def _generate_clip(
    source_url: str,
    motion_prompt: str,
    name: str,
    end_frame_url: str | None = None,
) -> tuple[str | None, bytes | None]:
    from app.sse.trailer_generator import _generate_video_from_image, _apply_faststart

    logger.info("Generating video clip: %s", name)
    result = await _generate_video_from_image(
        image_url=source_url,
        motion_prompt=motion_prompt,
        end_frame_url=end_frame_url,
    )
    if not result or not result.get("video_url"):
        logger.error("  %s — video generation failed", name)
        return None, None

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as s:
        async with s.get(result["video_url"]) as r:
            if r.status != 200:
                logger.error("  %s — download failed: %d", name, r.status)
                return None, None
            raw = await r.read()

    vid = await _apply_faststart(raw)
    from app.sse.infrastructure.r2_storage import store_bytes
    url = await store_bytes(vid, f"{R2_PREFIX}/clips/{name}.mp4", "video/mp4")
    logger.info("  %s → %d KB, stored", name, len(vid) // 1024)
    return url, vid


# ── TTS Voice ─────────────────────────────────────────────────────────────

async def _generate_voice() -> bytes | None:
    from app.sse.trailer_generator import _azure_tts
    logger.info("Generating TTS voice line…")
    audio = await _azure_tts(
        text=VOICE_TEXT, voice="coral", instructions=VOICE_INSTRUCTIONS,
    )
    if audio:
        logger.info("  TTS → %d KB", len(audio) // 1024)
    else:
        logger.error("  TTS generation failed")
    return audio


# ── FFmpeg Helpers ─────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _extract_last_frame(video_bytes: bytes, work: str) -> bytes | None:
    src = os.path.join(work, "_lastframe_src.mp4")
    dst = os.path.join(work, "_lastframe.png")
    with open(src, "wb") as f:
        f.write(video_bytes)
    r = _run(["ffmpeg", "-y", "-sseof", "-0.1", "-i", src, "-frames:v", "1", dst], 30)
    if r.returncode != 0 or not os.path.exists(dst):
        return None
    with open(dst, "rb") as f:
        return f.read()


def _trim(video_bytes: bytes, seconds: float, work: str) -> bytes:
    src = os.path.join(work, "_trim_src.mp4")
    dst = os.path.join(work, "_trim_dst.mp4")
    with open(src, "wb") as f:
        f.write(video_bytes)
    _run([
        "ffmpeg", "-y", "-i", src, "-t", str(seconds),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
        "-preset", "fast", "-crf", "18", dst,
    ])
    if os.path.exists(dst):
        with open(dst, "rb") as f:
            return f.read()
    return video_bytes


def _compose_title_card(bg_bytes: bytes, duration: float, work: str) -> str | None:
    """Create Act 3: gold title text over darkened background frame."""
    bg_path = os.path.join(work, "act3_bg.png")
    out_path = os.path.join(work, "act3.mp4")
    with open(bg_path, "wb") as f:
        f.write(bg_bytes)

    font = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
    if not os.path.exists(font):
        font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter

        bg = Image.open(bg_path).convert("RGBA")
        bg = bg.resize((1920, 1080), Image.LANCZOS)

        dark = Image.new("RGBA", (1920, 1080), (0, 0, 0, 60))
        bg = Image.alpha_composite(bg, dark)

        text_layer = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
        draw = ImageDraw.Draw(text_layer)

        try:
            title_font = ImageFont.truetype(font, 80)
            sub_font = ImageFont.truetype(font, 36)
        except Exception:
            title_font = ImageFont.load_default()
            sub_font = title_font

        title = "THERA-WORLD"
        subtitle = "by Sovereign Sanctuary"

        tb = draw.textbbox((0, 0), title, font=title_font)
        tw = tb[2] - tb[0]
        tx = (1920 - tw) // 2
        ty = 1080 // 2 - 70

        sb = draw.textbbox((0, 0), subtitle, font=sub_font)
        sw = sb[2] - sb[0]
        sx = (1920 - sw) // 2
        sy = 1080 // 2 + 30

        draw.text((tx, ty), title, fill=(201, 169, 98, 180), font=title_font)
        draw.text((sx, sy), subtitle, fill=(201, 169, 98, 180), font=sub_font)

        glow = text_layer.filter(ImageFilter.GaussianBlur(radius=10))
        sharp_layer = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sharp_layer)
        sd.text((tx, ty), title, fill=(232, 213, 163, 255), font=title_font)
        sd.text((sx, sy), subtitle, fill=(201, 169, 98, 255), font=sub_font)

        composite = Image.alpha_composite(bg, glow)
        composite = Image.alpha_composite(composite, sharp_layer)
        composite_rgb = composite.convert("RGB")

        comp_path = os.path.join(work, "act3_composite.png")
        composite_rgb.save(comp_path)

        _run([
            "ffmpeg", "-y", "-loop", "1", "-t", str(duration), "-i", comp_path,
            "-vf", "scale=1920:1080",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
            "-preset", "fast", "-crf", "18", out_path,
        ])
    except ImportError:
        logger.warning("PIL not available — using FFmpeg drawtext fallback")
        vf = (
            "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
            "eq=brightness=-0.12:contrast=1.05,"
            f"drawtext=text='THERA-WORLD':fontfile={font}:fontsize=80:"
            "fontcolor=0xE8D5A3:x=(w-text_w)/2:y=(h/2)-70,"
            f"drawtext=text='by Sovereign Sanctuary':fontfile={font}:fontsize=36:"
            "fontcolor=0xC9A962:x=(w-text_w)/2:y=(h/2)+30"
        )
        _run([
            "ffmpeg", "-y", "-loop", "1", "-t", str(duration), "-i", bg_path,
            "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-r", "24", "-preset", "fast", "-crf", "18", out_path,
        ])

    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        logger.info("  Act 3 title card composed")
        return out_path
    logger.error("  Act 3 compositing failed")
    return None


def _stitch_final(
    act_paths: list[str],
    audio_path: str | None,
    output_path: str,
    work: str,
) -> bool:
    normalized = []
    for i, src in enumerate(act_paths, 1):
        if not os.path.exists(src):
            logger.error("  Missing act %d at %s", i, src)
            return False
        norm = os.path.join(work, f"norm_{i}.mp4")
        _run([
            "ffmpeg", "-y", "-i", src,
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
                   "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
            "-preset", "fast", "-crf", "18", "-an", norm,
        ])
        if not os.path.exists(norm):
            logger.error("  Normalization failed for act %d", i)
            return False
        normalized.append(norm)

    concat_txt = os.path.join(work, "concat.txt")
    with open(concat_txt, "w") as f:
        for p in normalized:
            f.write(f"file '{p}'\n")

    silent_video = os.path.join(work, "concat.mp4")
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
        "-preset", "slow", "-crf", "20", "-movflags", "+faststart",
        silent_video,
    ], 300)

    if not os.path.exists(silent_video):
        logger.error("  Concat failed")
        return False

    if audio_path and os.path.exists(audio_path):
        padded = os.path.join(work, "padded_audio.wav")
        _run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-t", "13.0", "-i", "anullsrc=r=44100:cl=mono",
            "-i", audio_path,
            "-filter_complex", "[0][1]concat=n=2:v=0:a=1",
            padded,
        ], 60)

        if os.path.exists(padded):
            _run([
                "ffmpeg", "-y",
                "-i", silent_video, "-i", padded,
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-map", "0:v", "-map", "1:a", "-shortest",
                "-movflags", "+faststart", output_path,
            ])
        else:
            shutil.copy(silent_video, output_path)
    else:
        shutil.copy(silent_video, output_path)

    return os.path.exists(output_path)


# ── Main Orchestrator ─────────────────────────────────────────────────────

async def main() -> dict:
    work = tempfile.mkdtemp(prefix="hero_video_")
    logger.info("Work dir: %s", work)

    report: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "keyframes": {},
        "clips": {},
        "tts": None,
        "final": None,
        "moderation_retries": [],
    }

    # ────── STEP 1: Keyframe images ──────
    logger.info("═" * 60)
    logger.info("STEP 1 — Keyframe Images (3 images)")
    logger.info("═" * 60)

    kf: dict[str, dict] = {}
    for name, prompt in KEYFRAMES.items():
        try:
            url, img = await _generate_keyframe(name, prompt)
            kf[name] = {"url": url, "bytes": img}
            report["keyframes"][name] = {"url": url, "size_kb": len(img) // 1024}
            with open(os.path.join(work, f"{name}.png"), "wb") as f:
                f.write(img)
            await asyncio.sleep(3)
        except Exception as e:
            err = str(e)
            logger.error("  %s failed: %s", name, err)
            report["keyframes"][name] = {"error": err}
            if "moderation" in err.lower():
                report["moderation_retries"].append({"keyframe": name, "error": err})

    if "act1_mirror" not in kf or "act2_world" not in kf:
        logger.error("Critical keyframes missing — aborting")
        report["final"] = {"error": "critical keyframes missing"}
        return report

    # ────── STEP 2: Video clips ──────
    logger.info("═" * 60)
    logger.info("STEP 2 — Video Clips (2 clips via Grok Video)")
    logger.info("═" * 60)

    act1_end = kf.get("act1_landing", {}).get("url")
    act1_url, act1_bytes = await _generate_clip(
        source_url=kf["act1_mirror"]["url"],
        motion_prompt=MOTION["act1"],
        name="act1_the_pull",
        end_frame_url=act1_end,
    )
    report["clips"]["act1"] = {
        "url": act1_url,
        "size_kb": (len(act1_bytes) // 1024) if act1_bytes else 0,
    }

    act1_path = os.path.join(work, "act1.mp4")
    if act1_bytes:
        with open(act1_path, "wb") as f:
            f.write(act1_bytes)
        await asyncio.sleep(5)

    act2_url, act2_raw = await _generate_clip(
        source_url=kf["act2_world"]["url"],
        motion_prompt=MOTION["act2"],
        name="act2_world_reveal",
    )
    report["clips"]["act2"] = {
        "url": act2_url,
        "size_kb": (len(act2_raw) // 1024) if act2_raw else 0,
    }

    act2_path = os.path.join(work, "act2.mp4")
    last_frame: bytes | None = None
    if act2_raw:
        trimmed = _trim(act2_raw, 5.0, work)
        with open(act2_path, "wb") as f:
            f.write(trimmed)
        last_frame = _extract_last_frame(trimmed, work)

    # ────── STEP 3: TTS voice ──────
    logger.info("═" * 60)
    logger.info("STEP 3 — TTS Voice Line")
    logger.info("═" * 60)

    tts = await _generate_voice()
    tts_path: str | None = None
    if tts:
        tts_path = os.path.join(work, "voice.wav")
        with open(tts_path, "wb") as f:
            f.write(tts)
        from app.sse.infrastructure.r2_storage import store_bytes
        tts_url = await store_bytes(tts, f"{R2_PREFIX}/voice_tagline.wav", "audio/wav")
        report["tts"] = {"url": tts_url, "size_kb": len(tts) // 1024}

    # ────── STEP 4: Act 3 title card ──────
    logger.info("═" * 60)
    logger.info("STEP 4 — Act 3 Title Card (fire text)")
    logger.info("═" * 60)

    if last_frame is None:
        last_frame = kf.get("act2_world", {}).get("bytes")
    act3_path: str | None = None
    if last_frame:
        act3_path = _compose_title_card(last_frame, 2.0, work)

    # ────── STEP 5: Final stitch ──────
    logger.info("═" * 60)
    logger.info("STEP 5 — Final Stitch (15s)")
    logger.info("═" * 60)

    missing = []
    if not act1_bytes:
        missing.append("act1")
    if not os.path.exists(act2_path):
        missing.append("act2")
    if not act3_path:
        missing.append("act3")
    if missing:
        logger.error("Missing acts: %s — cannot stitch", missing)
        report["final"] = {"error": f"missing acts: {missing}"}
        return report

    final_path = os.path.join(work, "hero_video_thera_world.mp4")
    ok = _stitch_final([act1_path, act2_path, act3_path], tts_path, final_path, work)

    if ok and os.path.exists(final_path):
        size = os.path.getsize(final_path)
        with open(final_path, "rb") as f:
            final_bytes = f.read()

        from app.sse.infrastructure.r2_storage import store_bytes as _sb
        r2_url = await _sb(final_bytes, f"{R2_PREFIX}/hero_video_thera_world.mp4", "video/mp4")

        local_out = os.path.join(work, "hero_video_thera_world_FINAL.mp4")
        shutil.copy(final_path, local_out)

        dur = 0.0
        try:
            p = _run([
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", final_path,
            ], 10)
            dur = float(p.stdout.decode().strip())
        except Exception:
            pass

        report["final"] = {
            "r2_url": r2_url,
            "local_path": local_out,
            "file_size_bytes": size,
            "file_size_mb": round(size / 1024 / 1024, 2),
            "under_15mb": size < 15 * 1024 * 1024,
            "duration_seconds": dur,
        }
        logger.info("  FINAL: %.1fMB, %.1fs, stored at %s", size / 1024 / 1024, dur, r2_url[:80])
    else:
        report["final"] = {"error": "stitch failed"}

    report["completed_at"] = datetime.now(timezone.utc).isoformat()

    from app.sse.infrastructure.r2_storage import store_bytes as _sb2
    await _sb2(
        json.dumps(report, indent=2, default=str).encode(),
        f"{R2_PREFIX}/hero_video_report.json",
        "application/json",
    )

    logger.info("═" * 60)
    logger.info("GENERATION REPORT")
    logger.info("═" * 60)
    for n, info in report["keyframes"].items():
        logger.info("  Keyframe %-18s %s", n, "OK" if "url" in info else "FAILED")
    for n, info in report["clips"].items():
        logger.info("  Clip     %-18s %s", n, "OK" if info.get("url") else "FAILED")
    logger.info("  TTS      %-18s %s", "", "OK" if report["tts"] else "FAILED")
    f = report.get("final", {})
    if "error" in f:
        logger.info("  FINAL    %-18s FAILED: %s", "", f["error"])
    else:
        logger.info("  FINAL    %-18s OK — %.1fMB, %.1fs", "",
                     f.get("file_size_mb", 0), f.get("duration_seconds", 0))
        logger.info("  R2 URL:  %s", f.get("r2_url", "N/A"))
    if report.get("moderation_retries"):
        for mr in report["moderation_retries"]:
            logger.info("  MODERATION RETRY: %s — %s", mr["keyframe"], mr["error"][:100])

    return report


if __name__ == "__main__":
    result = asyncio.run(main())
    print(json.dumps(result, indent=2, default=str))
