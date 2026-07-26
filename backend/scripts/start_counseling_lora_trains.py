#!/usr/bin/env python3
"""Start Replicate LoRA trains for Counseling Office characters (run on GREEN)."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

ENV = Path("/opt/clinical-sovereignty-lab/.env")
PID = "5c712188-7d01-4d0a-b7f4-40b49eaa14b3"
BASE = "http://localhost:8000/api/sse/admin/studio"
CHARS = ("little_nate", "ask_client")


def env_val(key: str) -> str:
    for line in ENV.read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {env_val('SKYEYE_AUDIT_TOKEN')}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode()[:500]
        return {"detail": body_txt, "status_code": e.code}


def main() -> None:
    for c in CHARS:
        z = post("/lora/zip-training-images", {"character_key": c, "project_id": PID})
        zip_url = z.get("zip_url")
        print(c, "zip_ok", bool(zip_url))
        if not zip_url:
            print(c, "zip_fail", z)
            continue
        t = post(
            "/lora/train",
            {"character_key": c, "training_images_zip_url": zip_url},
        )
        tid = t.get("training_id")
        print(c, "status", t.get("status"), "training_id", tid, "detail", t.get("detail"))
        Path(f"/tmp/lora_{c}_tid.txt").write_text((tid or "") + "\n")


if __name__ == "__main__":
    main()
