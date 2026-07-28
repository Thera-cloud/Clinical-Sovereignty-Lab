#!/usr/bin/env python3
"""Offline LN7 QLoRA / adapter train entrypoint — BLUE (MLX) or rented GPU only.

GREEN must never invoke this. Writes a revision manifest for register_revision.

Usage (BLUE / Apple Silicon MLX):
  python backend/scripts/ln7_qlora_train.py \\
    --train-jsonl /tmp/ln7_train.jsonl \\
    --base qwen2.5-coder:7b-instruct \\
    --out-dir /tmp/ln7_adapters/LN7-<ts>

If mlx_lm is unavailable, writes a dry-run adapter stub + manifest so the
revision pipeline can be exercised end-to-end.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _utc_rid() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def _load_jsonl(path: Path) -> list:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def train_mlx(train_path: Path, out_dir: Path, base: str, iters: int) -> dict:
    """Best-effort MLX LoRA; falls back to dry-run."""
    try:
        # Optional dependency — only on BLUE training hosts
        import mlx_lm  # noqa: F401
    except Exception:
        out_dir.mkdir(parents=True, exist_ok=True)
        stub = out_dir / "adapter_config.json"
        stub.write_text(
            json.dumps({
                "base": base,
                "method": "dry_run_stub",
                "train_path": str(train_path),
                "note": "Install mlx-lm on BLUE to run real QLoRA.",
            }, indent=2),
            encoding="utf-8",
        )
        return {"ok": True, "method": "dry_run_stub", "adapter_dir": str(out_dir)}

    # Real train hook — document exact CLI for operators
    cmd_note = (
        f"mlx_lm.lora --model {base} --train --data {train_path} "
        f"--adapter-path {out_dir} --iters {iters}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "TRAIN_CMD.txt").write_text(cmd_note + "\n", encoding="utf-8")
    # Prefer subprocess when mlx_lm.lora entrypoint exists
    import shutil
    import subprocess

    if shutil.which("mlx_lm.lora") or shutil.which("python"):
        try:
            subprocess.run(
                [
                    sys.executable, "-m", "mlx_lm.lora",
                    "--model", base,
                    "--train",
                    "--data", str(train_path),
                    "--adapter-path", str(out_dir),
                    "--iters", str(iters),
                ],
                check=False,
                timeout=int(os.getenv("LN7_QLORA_TIMEOUT_S", "86400")),
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300], "cmd": cmd_note}
    return {"ok": True, "method": "mlx_lm.lora", "adapter_dir": str(out_dir), "cmd": cmd_note}


def main() -> int:
    if (os.getenv("NODE_COLOR") or "").strip().lower() == "green":
        print(json.dumps({"ok": False, "error": "refusing_train_on_green"}))
        return 3

    import platform

    # mlx / mlx-lm require Apple Silicon — Intel BLUE hosts must use a GPU rental.
    if platform.machine().lower() in ("x86_64", "amd64", "i386", "i686"):
        if os.getenv("LN7_QLORA_ALLOW_X86_DRY_RUN", "").strip().lower() not in (
            "1", "true", "yes", "on",
        ):
            print(json.dumps({
                "ok": False,
                "error": "mlx_requires_apple_silicon",
                "arch": platform.machine(),
                "hint": "Run QLoRA on Apple Silicon or a CUDA GPU droplet; "
                        "set LN7_QLORA_ALLOW_X86_DRY_RUN=1 only for stub manifests.",
            }))
            return 4

    ap = argparse.ArgumentParser()
    ap.add_argument("--train-jsonl", required=True)
    ap.add_argument("--base", default=os.getenv("LN7_CODE_MODEL_FAST", "qwen2.5-coder:7b-instruct"))
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--quantization", default="q5_K_M")
    args = ap.parse_args()

    train_path = Path(args.train_jsonl)
    if not train_path.is_file():
        print(json.dumps({"ok": False, "error": "missing_train_jsonl"}))
        return 2

    rows = _load_jsonl(train_path)
    if not rows:
        print(json.dumps({"ok": False, "error": "empty_train_set"}))
        return 2

    rid = _utc_rid()
    out_dir = Path(args.out_dir or f"/tmp/ln7_adapters/LN7-{rid}")
    result = train_mlx(train_path, out_dir, args.base, args.iters)

    manifest = {
        "revision_id": f"LN7-{rid}",
        "base_checkpoint": args.base,
        "quantization": args.quantization,
        "adapter_dir": str(out_dir),
        "n_train": len(rows),
        "train_method": result.get("method"),
        "status": "shadow",
        "notes": "Offline QLoRA candidate — run statistical gate before activate.",
        "non_clinical_claim": True,
        "register_body": {
            "revision_id": f"LN7-{rid}",
            "base_checkpoint": args.base,
            "quantization": args.quantization,
            "status": "shadow",
            "notes": f"QLoRA from {len(rows)} rejection samples; adapter={out_dir}",
            "harness_config": {"train_n": len(rows), "method": result.get("method")},
        },
    }
    man_path = out_dir / "revision_manifest.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    man_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"ok": bool(result.get("ok")), **manifest, "manifest": str(man_path)}))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
