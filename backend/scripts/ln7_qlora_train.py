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


# Must match ORANGE ln7_peft_server.py default (serve :11435)
DEFAULT_HF_BASE = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
ALL_LINEAR_MODULES = [
    "q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",
]
DEFAULT_MODULES = ["q_proj", "v_proj"]


def _load_jsonl(path: Path) -> list:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _assistant_text(row: dict) -> str:
    msgs = row.get("messages") or []
    for m in msgs:
        if (m.get("role") or "") == "assistant":
            return str(m.get("content") or "")
    return str(row.get("assistant") or "")


def filter_clean_rows(rows: list) -> list:
    """Drop stubs / dry-run noise; require real assistant patch body."""
    import re
    stub = re.compile(r"^\[patch_hash=", re.I)
    diff_mark = re.compile(r"(?m)^(diff --git |--- |\+\+\+ |@@ )")
    clean = []
    for r in rows:
        if r.get("method") == "dry_run_stub" or r.get("source") == "dry_run_stub":
            continue
        asst = _assistant_text(r)
        if not asst or stub.match(asst.strip()):
            continue
        if "dry_run_stub" in asst:
            continue
        if not (diff_mark.search(asst) or (asst.count("\n+") + asst.count("\n-") >= 2)):
            continue
        clean.append(r)
    return clean


def _lora_recipe(name: str) -> dict:
    """default = q/v r=16 α=32; all_linear = all Qwen proj r=32 α=64."""
    n = (name or "default").strip().lower()
    if n in ("all", "all_linear", "all-linear", "full"):
        return {
            "name": "all_linear",
            "r": int(os.getenv("LN7_LORA_R", "32") or "32"),
            "lora_alpha": int(os.getenv("LN7_LORA_ALPHA", "64") or "64"),
            "target_modules": list(ALL_LINEAR_MODULES),
        }
    return {
        "name": "default",
        "r": int(os.getenv("LN7_LORA_R", "16") or "16"),
        "lora_alpha": int(os.getenv("LN7_LORA_ALPHA", "32") or "32"),
        "target_modules": list(DEFAULT_MODULES),
    }


def train_cuda(
    train_path: Path,
    out_dir: Path,
    base: str,
    iters: int,
    *,
    recipe: str = "default",
    max_seq_len: int = 2048,
) -> dict:
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
    # Prefer explicit HF id; --base Ollama tags are not HF ids
    model_id = os.getenv("LN7_QLORA_HF_BASE") or (
        base if base.startswith("Qwen/") or "/" in base else DEFAULT_HF_BASE
    )
    if not model_id.startswith("Qwen/") and "Instruct" not in model_id:
        model_id = DEFAULT_HF_BASE
    cfg = _lora_recipe(recipe)
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
        LoraConfig(
            r=cfg["r"],
            lora_alpha=cfg["lora_alpha"],
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=cfg["target_modules"],
        ),
    )

    def _fmt(ex):
        msgs = ex.get("messages") or []
        text = ""
        for m in msgs:
            text += f"{m.get('role','user')}: {m.get('content','')}\n"
        return {"text": text or ex.get("prompt") or ""}

    ds = load_dataset("json", data_files=str(train_path), split="train")
    ds = ds.map(_fmt)
    ds = ds.map(
        lambda b: tok(b["text"], truncation=True, max_length=max_seq_len),
        batched=True,
    )

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
    # Never overwrite PEFT adapter_config.json — peft_type required for load
    (out_dir / "train_meta.json").write_text(
        json.dumps({
            "base": model_id,
            "method": "cuda_qlora_peft",
            "train_path": str(train_path),
            "lora_recipe": cfg,
            "iters": iters,
            "max_seq_len": max_seq_len,
        }, indent=2),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "method": "cuda_qlora_peft",
        "adapter_dir": str(out_dir),
        "hf_base": model_id,
        "base_checkpoint": model_id,
        "lora_recipe": cfg["name"],
        "lora_r": cfg["r"],
        "lora_alpha": cfg["lora_alpha"],
        "target_modules": cfg["target_modules"],
    }


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
    ap.add_argument(
        "--base",
        default=os.getenv("LN7_QLORA_HF_BASE", DEFAULT_HF_BASE),
        help="HF base id — must match LN7 PEFT serve (:11435)",
    )
    ap.add_argument("--out-dir", default="")
    ap.add_argument(
        "--revision-id",
        default="",
        help="Canonical revision id (LN7-… or bare ts). Prefer over minting a new UTC id.",
    )
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--quantization", default="q5_K_M")
    ap.add_argument(
        "--lora-recipe",
        default=os.getenv("LN7_LORA_RECIPE", "default"),
        choices=("default", "all_linear"),
        help="default=q/v r=16; all_linear=all Qwen proj r=32 α=64",
    )
    ap.add_argument("--max-seq-len", type=int, default=2048)
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

    raw_rows = _load_jsonl(train_path)
    rows = filter_clean_rows(raw_rows)
    min_rows = int(os.getenv("LN7_QLORA_MIN_ROWS", "50") or "50")
    force_thin = os.getenv("LN7_QLORA_FORCE_THIN", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    if not rows:
        print(json.dumps({
            "ok": False,
            "error": "empty_clean_train_set",
            "raw_n": len(raw_rows),
            "hint": "Re-export with ln7_export_train_jsonl.py (real diffs, no hash stubs)",
        }))
        return 2
    if len(rows) < min_rows and not force_thin:
        print(json.dumps({
            "ok": False,
            "error": "thin_train_set",
            "clean_n": len(rows),
            "min_rows": min_rows,
            "hint": "Collect ≥200–500 clean rows before all_linear/iters raise; "
                    "or LN7_QLORA_FORCE_THIN=1 for explicit thin runs",
        }))
        return 5
    # Rewrite filtered JSONL so datasets does not re-ingest stubs
    clean_path = train_path.parent / f"{train_path.stem}.clean.jsonl"
    with clean_path.open("w", encoding="utf-8") as cf:
        for r in rows:
            cf.write(json.dumps(r, default=str) + "\n")
    train_path = clean_path

    # Prefer explicit --revision-id, else LN7-* basename of --out-dir, else mint UTC.
    def _resolve_rid() -> str:
        raw = (args.revision_id or "").strip()
        if raw:
            return raw[4:] if raw.startswith("LN7-") else raw
        if args.out_dir:
            base = Path(args.out_dir).name
            if base.startswith("LN7-") and len(base) > 4:
                return base[4:]
        return _utc_rid()

    rid = _resolve_rid()
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
        result = train_cuda(
            train_path, out_dir, args.base, args.iters,
            recipe=args.lora_recipe, max_seq_len=args.max_seq_len,
        )
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

    # Prefer HF id actually trained (cuda), else Ollama tag used for mlx/dry_run.
    base_label = (
        result.get("hf_base")
        or result.get("base_checkpoint")
        or args.base
    )
    manifest = {
        "revision_id": f"LN7-{rid}",
        "base_checkpoint": base_label,
        "quantization": args.quantization if backend != "cuda" else "nf4_qlora",
        "adapter_dir": str(out_dir),
        "n_train": len(rows),
        "train_method": result.get("method"),
        "status": "shadow",
        "notes": "Offline QLoRA candidate — run statistical gate before activate.",
        "non_clinical_claim": True,
        "register_body": {
            "revision_id": f"LN7-{rid}",
            "base_checkpoint": base_label,
            "quantization": args.quantization if backend != "cuda" else "nf4_qlora",
            "status": "shadow",
            "notes": f"QLoRA from {len(rows)} samples; method={result.get('method')}; adapter={out_dir}",
            "harness_config": {
                "train_n": len(rows),
                "raw_n": len(raw_rows),
                "method": result.get("method"),
                "hf_base": result.get("hf_base"),
                "lora_recipe": result.get("lora_recipe") or args.lora_recipe,
                "lora_r": result.get("lora_r"),
                "tier": os.getenv("LN7_TRAIN_TIER", "fast"),
                "force_peft": True,
                "peft_url": os.getenv("LN7_PEFT_URL", "http://10.13.13.5:11435"),
                "serve_note": "PEFT adapter not auto-merged into Ollama; durable store only until merge path ships",
            },
        },
    }
    man_path = out_dir / "revision_manifest.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    man_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"ok": bool(result.get("ok")), **manifest, "manifest": str(man_path)}))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
