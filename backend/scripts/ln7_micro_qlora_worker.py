#!/usr/bin/env python3
"""Drain one LN7 continuous train job on BLUE/CUDA (never GREEN).

Flow:
  1. GET /api/ln7/train/jobs (or local DB)
  2. Export JSONL for job outcome_ids
  3. ln7_qlora_train.py --backend auto|cuda
  4. POST /api/ln7/revision/register + /canary/evaluate?start=1

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    if (os.getenv("NODE_COLOR") or "").strip().lower() == "green":
        print(json.dumps({"ok": False, "error": "refusing_worker_on_green"}))
        return 3

    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", type=int, required=True)
    ap.add_argument("--train-jsonl", required=True, help="Pre-exported JSONL for this job")
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--iters", type=int, default=80)
    ap.add_argument("--api", default=os.getenv("LN7_API_BASE", "https://api.sovereignsanctuary.net"))
    ap.add_argument("--token", default=os.getenv("SKYEYE_AUDIT_TOKEN", ""))
    args = ap.parse_args()

    out = Path(f"/tmp/ln7_adapters/job_{args.job_id}")
    cmd = [
        sys.executable,
        str(ROOT / "backend/scripts/ln7_qlora_train.py"),
        "--train-jsonl", args.train_jsonl,
        "--out-dir", str(out),
        "--iters", str(args.iters),
        "--backend", args.backend,
    ]
    env = os.environ.copy()
    if args.backend == "dry_run":
        env["LN7_QLORA_ALLOW_X86_DRY_RUN"] = "1"
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr[-2000:], file=sys.stderr)
        return proc.returncode

    try:
        manifest = json.loads((out / "revision_manifest.json").read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"manifest:{exc}"}))
        return 1

    body = manifest.get("register_body") or {}
    if not args.token:
        print(json.dumps({"ok": True, "staged_local": True, "manifest": manifest, "hint": "register via API with token"}))
        return 0

    import urllib.request
    def _post(path, payload):
        req = urllib.request.Request(
            f"{args.api.rstrip('/')}{path}",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {args.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())

    # Optional durable copy (BLUE/ORANGE path) — never GREEN train host
    persist = (os.getenv("LN7_ADAPTER_STORE") or "").strip()
    if persist:
        import shutil
        dest = Path(persist) / str(body.get("revision_id") or f"job_{args.job_id}")
        dest.mkdir(parents=True, exist_ok=True)
        for p in out.iterdir():
            if p.is_file():
                shutil.copy2(p, dest / p.name)
        body.setdefault("harness_config", {})
        if isinstance(body.get("harness_config"), dict):
            body["harness_config"]["durable_store"] = str(dest)

    reg = _post("/api/ln7/revision/register", {**body, "notify_ceo": True})
    can = _post("/api/ln7/canary/evaluate", {"revision_id": body.get("revision_id"), "start": True})
    print(json.dumps({"ok": True, "register": reg, "canary": can, "job_id": args.job_id, "persisted": persist or None}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
