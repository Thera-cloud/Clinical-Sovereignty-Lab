#!/usr/bin/env python3
"""Family Sanctuary v7 Task 1 — Grok Imagine scene 12 PNG regen + FFmpeg Ken Burns + R2 motion upload.

Run inside nate_backend:

  docker exec -w /app nate_backend env PYTHONPATH=/app python3 /tmp/task1_scene12_png.py

Requires prior deploy of trailer_generator.py with png_prompt_overrides support.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

if "/app" not in sys.path:
    sys.path.insert(0, "/app")

SCENE12_PNG_PROMPT = (
    "Painterly cinematic illustration, Pixar-Disney inspired but with photorealistic skin texture and fabric. "
    "Black African American family of four walking away from camera holding hands, viewed from back-three-quarter "
    "angle, walking toward a sunrise portal sanctum on the horizon with golden embers floating in the air. "
    "Distant sanctum spire glowing soft gold center-frame. Dusk hills, warm ember firefly motes throughout, "
    "atmospheric haze. "
    "CHARACTERS LEFT TO RIGHT: "
    "Mother (left): Black woman, terracotta dress with sage green INSET PANELS and patterned woven cuff bands at "
    "sleeves. Hair in low bun. Walking, holding daughter's hand. NOT a wrap robe. NOT a solid color robe. "
    "Daughter: ~8y Black girl, twin Afro puffs with beads, bright yellow dress, holding mother's hand and son's hand. "
    "Son: ~12y Black boy, olive jacket over graphic tee, dark jeans, holding daughter's hand and father's hand. "
    "Father (right): Black man, NAVY HENLEY 3-button placket shirt, DARK BLUE JEANS. NOT a black tee. NOT cargo pants. "
    "NO side pockets visible. Trimmed beard. Walking. "
    "ONLY FOUR CHARACTERS in the image. No extras."
)


def _s3():
    import boto3
    from botocore.config import Config

    account = os.environ.get("R2_ACCOUNT_ID", "").strip()
    endpoint = os.environ.get("R2_ENDPOINT_URL", "").strip()
    if not endpoint and account:
        endpoint = f"https://{account}.r2.cloudflarestorage.com"
    bucket = os.environ.get("R2_DEFAULT_BUCKET", "nate-vault").strip()
    if not endpoint:
        raise RuntimeError("R2_ACCOUNT_ID or R2_ENDPOINT_URL required")
    return (
        boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"].strip(),
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"].strip(),
            config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "adaptive"}),
            region_name="auto",
        ),
        bucket,
    )


async def _regen_png() -> list:
    from app.sse.trailer_generator import regenerate_family_sanctuary_hero_scene_pngs

    pid = os.environ.get("FS_REGEN_PROJECT_ID", "family_sanctuary_v7_scene12_png").strip()
    return await regenerate_family_sanctuary_hero_scene_pngs(
        pid,
        [12],
        backup_name="pre_v7_scene12_tableau",
        audit_identity_strict=False,
        png_prompt_overrides={12: SCENE12_PNG_PROMPT},
        cost_ceiling_usd=float(os.environ.get("FS_PNG_REGEN_CEILING_USD", "5")),
    )


def main() -> None:
    res = asyncio.run(_regen_png())
    print("PNG_REGEN_JSON:")
    print(json.dumps(res, indent=2, default=str))
    if not any(r.get("status") == "success" for r in res):
        raise SystemExit("scene 12 PNG regen failed — aborting Ken Burns")

    png_key = "sse/trailer/family_sanctuary/scenes/scene_12.png"
    png_local = "/tmp/scene_12_new.png"
    mp4_local = "/tmp/scene_12_kenburns_v2.mp4"
    motion_key = "sse/trailer/family_sanctuary/motion/scene_12.mp4"

    s3, bucket = _s3()
    print("Downloading", png_key, "...")
    s3.download_file(bucket, png_key, png_local)

    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        png_local,
        "-vf",
        "scale=1696:960,zoompan=z='min(zoom+0.0008,1.12)':d=150:s=848x480:fps=24,format=yuv420p",
        "-t",
        "6.25",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        mp4_local,
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True, timeout=600)
    subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-show_streams", "-i", mp4_local],
        check=True,
        timeout=60,
    )

    print("Uploading motion →", motion_key)
    s3.upload_file(mp4_local, bucket, motion_key, ExtraArgs={"ContentType": "video/mp4"})
    print("OK: Task 1 complete —", motion_key)


if __name__ == "__main__":
    main()
