#!/usr/bin/env bash
# Family Sanctuary scene 12 — FFmpeg Ken Burns only (no Grok). Run inside nate_backend.
set -euo pipefail

PNG_LOCAL="${PNG_LOCAL:-/tmp/scene_12.png}"
MP4_LOCAL="${MP4_LOCAL:-/tmp/scene_12_kenburns.mp4}"
DST_KEY="sse/trailer/family_sanctuary/motion/scene_12.mp4"
export PNG_LOCAL MP4_LOCAL

python3 << 'PY'
import os
import boto3
from botocore.config import Config

account = os.environ.get("R2_ACCOUNT_ID", "").strip()
endpoint = os.environ.get("R2_ENDPOINT_URL", "").strip()
if not endpoint and account:
    endpoint = f"https://{account}.r2.cloudflarestorage.com"
bucket = os.environ.get("R2_DEFAULT_BUCKET", "nate-vault").strip()
s3 = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"].strip(),
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"].strip(),
    config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "adaptive"}),
    region_name="auto",
)
out_png = os.environ.get("PNG_LOCAL", "/tmp/scene_12.png")
s3.download_file(bucket, "sse/trailer/family_sanctuary/scenes/scene_12.png", out_png)
print("downloaded scene_12.png ->", out_png)
PY

ffmpeg -y -loop 1 -i "$PNG_LOCAL" \
  -vf "scale=1696:960,zoompan=z='min(zoom+0.0008,1.12)':d=150:s=848x480:fps=24,format=yuv420p" \
  -t 6.25 -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
  "$MP4_LOCAL"

ffprobe -v error -show_entries format=duration -show_entries stream=width,height,r_frame_rate "$MP4_LOCAL"

export MP4_LOCAL DST_KEY
python3 << 'PY'
import os
import boto3
from botocore.config import Config

account = os.environ.get("R2_ACCOUNT_ID", "").strip()
endpoint = os.environ.get("R2_ENDPOINT_URL", "").strip()
if not endpoint and account:
    endpoint = f"https://{account}.r2.cloudflarestorage.com"
bucket = os.environ.get("R2_DEFAULT_BUCKET", "nate-vault").strip()
mp4 = os.environ["MP4_LOCAL"]
dst = os.environ["DST_KEY"]
s3 = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"].strip(),
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"].strip(),
    config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "adaptive"}),
    region_name="auto",
)
s3.upload_file(mp4, bucket, dst, ExtraArgs={"ContentType": "video/mp4"})
print("uploaded", dst)
PY
