#!/usr/bin/env python3
"""W9: one-shot domain_tag backfill on ln_sandbox_ci_packs/*/task.json.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app" / "data" / "ln_sandbox_ci_packs"


def infer_domain(name: str, task: dict) -> str:
    blob = (
        name
        + " "
        + str(task.get("task_key") or "")
        + " "
        + str(task.get("title") or "")
        + " "
        + str(task.get("prompt") or "")[:400]
    ).lower()
    if any(x in blob for x in ("flutter", "dart", "widget")):
        return "flutter"
    if any(x in blob for x in ("nginx", "docker", "compose", "wireguard")):
        return "infra"
    if any(x in blob for x in ("clinical", "therapeutic", "crisis", "sensitive")):
        return "clinical"
    if any(x in blob for x in ("qlora", "lora", "ollama", "vllm", "ada")):
        return "ml"
    if any(x in blob for x in ("auditor", "trust", "baseline")):
        return "trust"
    if any(x in blob for x in ("stripe", "billing", "token", "quickbooks")):
        return "billing"
    return "python"


def main() -> int:
    dry = "--dry-run" in sys.argv
    n = 0
    for path in sorted(ROOT.glob("*/task.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("domain_tag"):
            continue
        tag = infer_domain(path.parent.name, data)
        data["domain_tag"] = tag
        # Default split train unless pack name implies heldout
        if "split" not in data:
            data["split"] = "heldout" if "heldout" in path.parent.name else "train"
        if not dry:
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        n += 1
        print(f"{path.parent.name}: {tag}")
    print(f"{'would update' if dry else 'updated'} {n} packs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
