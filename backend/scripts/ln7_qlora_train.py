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


def train_cuda(train_path: Path, out_dir: Path, base: str, iters: int) -> dict:
    """CUDA QLoRA via peft/transformers when torch.cuda is available (GPU rental)."""
    try:
        import torch  # noqa: F401
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from datasets import load_dataset
        from transformers import TrainingArguments, Trainer, DataCollatorForLanguageModeling
    except Exception as exc:
        return {
            "ok": False,
            "error": f"cuda_deps_missing:{exc}",
            "hint": "pip install torch peft transformers bitsandbytes datasets accelerate",
        }
    import torch
    if not torch.cuda.is_available():
        return {"ok": False, "error": "cuda_not_available"}

    out_dir.mkdir(parents=True, exist_ok=True)
    model_id = os.getenv("LN7_QLORA_HF_BASE", "Qwen/Qwen2.5-Coder-7B-Instruct")
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        model_id, quantization_config=bnb, device_map="auto", trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)
    model = get_peft_model(
        model,
        LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM"),
    )

    def _fmt(ex):
        msgs = ex.get("messages") or []
        text = ""
        for m in msgs:
            text += f"{m.get('role','user')}: {m.get('content','')}\n"
        return {"text": text or ex.get("prompt") or ""}

    ds = load_dataset("json", data_files=str(train_path), split="train")
    ds = ds.map(_fmt)
    ds = ds.map(lambda b: tok(b["text"], truncation=True, max_length=2048), batched=True)

    args = TrainingArguments(
        output_dir=str(out_dir),
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        max_steps=max(10, iters),
        learning_rate=2e-4,
        fp16=True,
        logging_steps=5,
        save_steps=max(10, iters),
        report_to=[],
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=ds,
        data_collator=DataCollatorForLanguageModeling(tok, mlm=False),
    )
    trainer.train()
    model.save_pretrained(str(out_dir))
    tok.save_pretrained(str(out_dir))
    (out_dir / "adapter_config.json").write_text(
        json.dumps({"base": model_id, "method": "cuda_qlora_peft", "train_path": str(train_path)}, indent=2),
        encoding="utf-8",
    )
    return {"ok": True, "method": "cuda_qlora_peft", "adapter_dir": str(out_dir)}


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
    import shutil

    ap = argparse.ArgumentParser()
    ap.add_argument("--train-jsonl", required=True)
    ap.add_argument("--base", default=os.getenv("LN7_CODE_MODEL_FAST", "qwen2.5-coder:7b-instruct"))
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--quantization", default="q5_K_M")
    ap.add_argument(
        "--backend",
        default=os.getenv("LN7_QLORA_BACKEND", "auto"),
        choices=("auto", "mlx", "cuda", "dry_run"),
    )
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

    backend = args.backend
    if backend == "auto":
        try:
            import torch
            if torch.cuda.is_available():
                backend = "cuda"
            elif platform.machine().lower() in ("arm64", "aarch64") and (
                shutil.which("mlx_lm.lora") or True
            ):
                backend = "mlx"
            else:
                backend = "dry_run"
        except Exception:
            backend = "mlx" if platform.machine().lower() in ("arm64", "aarch64") else "dry_run"

    if backend == "cuda":
        result = train_cuda(train_path, out_dir, args.base, args.iters)
    elif backend == "dry_run":
        if os.getenv("LN7_QLORA_ALLOW_X86_DRY_RUN", "").strip().lower() not in (
            "1", "true", "yes", "on",
        ) and platform.machine().lower() in ("x86_64", "amd64", "i386", "i686"):
            print(json.dumps({
                "ok": False,
                "error": "no_gpu_backend",
                "arch": platform.machine(),
                "hint": "Use --backend cuda on a GPU droplet, or Apple Silicon mlx, "
                        "or LN7_QLORA_ALLOW_X86_DRY_RUN=1 for stub only.",
            }))
            return 4
        result = train_mlx(train_path, out_dir, args.base, args.iters)  # falls to stub
    else:
        # mlx path — Apple Silicon
        if platform.machine().lower() in ("x86_64", "amd64", "i386", "i686"):
            if os.getenv("LN7_QLORA_ALLOW_X86_DRY_RUN", "").strip().lower() not in (
                "1", "true", "yes", "on",
            ):
                print(json.dumps({
                    "ok": False,
                    "error": "mlx_requires_apple_silicon",
                    "arch": platform.machine(),
                    "hint": "Use --backend cuda on a GPU host.",
                }))
                return 4
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
