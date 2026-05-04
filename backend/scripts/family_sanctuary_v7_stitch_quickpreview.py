#!/usr/bin/env python3
"""Download motion scene_01..12 from R2, lossless concat → /tmp/family_sanctuary_quickpreview_v7.mp4."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

BUCKET = os.environ.get("R2_DEFAULT_BUCKET", "nate-vault").strip()
PREFIX = "sse/trailer/family_sanctuary/motion".rstrip("/")
OUT_PATH = os.environ.get("FS_QUICKPREVIEW_OUT", "/tmp/family_sanctuary_quickpreview_v7.mp4")


def _s3():
    import boto3
    from botocore.config import Config

    account = os.environ.get("R2_ACCOUNT_ID", "").strip()
    endpoint = os.environ.get("R2_ENDPOINT_URL", "").strip()
    if not endpoint and account:
        endpoint = f"https://{account}.r2.cloudflarestorage.com"
    if not endpoint:
        raise RuntimeError("Set R2_ACCOUNT_ID (or R2_ENDPOINT_URL) + R2_ACCESS_KEY_ID + R2_SECRET_ACCESS_KEY")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"].strip(),
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"].strip(),
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "adaptive"}),
        region_name="auto",
    )


def main() -> None:
    s3 = _s3()
    work = tempfile.mkdtemp(prefix="fs_v7_stitch_")
    try:
        files: list[str] = []
        for i in range(1, 13):
            key = f"{PREFIX}/scene_{i:02d}.mp4"
            loc = os.path.join(work, f"scene_{i:02d}.mp4")
            print("Downloading", key, "...")
            s3.download_file(BUCKET, key, loc)
            files.append(loc)

        lst_path = os.path.join(work, "concat.txt")
        with open(lst_path, "w", encoding="utf-8") as h:
            for p in files:
                # concat demuxer: escape single quotes in path
                safe = p.replace("'", "'\\''")
                h.write(f"file '{safe}'\n")

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            lst_path,
            "-c",
            "copy",
            OUT_PATH,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if proc.returncode != 0:
            print(proc.stderr[-4000:])
            raise RuntimeError("ffmpeg concat failed")

        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-show_streams", OUT_PATH],
            check=True,
            timeout=120,
        )
        print("OK:", OUT_PATH)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
