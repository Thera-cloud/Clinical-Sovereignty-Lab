#!/usr/bin/env bash
# A/B QLoRA on identical clean JSONL — keep winner only after bakeoff mean↑.
# Runs TWO sequential TOR drains (default vs all_linear). Does NOT auto-activate.
#
#   bash scripts/ln7_ab_qlora_drain.sh
# Requires: data/ln7_train.jsonl with ≥ LN7_QLORA_MIN_ROWS clean diffs
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
export LN7_GPU_REGION="${LN7_GPU_REGION:-tor1}"
export LN7_QLORA_HF_BASE="${LN7_QLORA_HF_BASE:-Qwen/Qwen2.5-Coder-1.5B-Instruct}"
export LN7_QLORA_MIN_ROWS="${LN7_QLORA_MIN_ROWS:-50}"

echo "[ab] recipe=default"
LN7_LORA_RECIPE=default bash "$REPO/scripts/ln7_continuous_drain.sh"
echo "[ab] recipe=all_linear"
LN7_LORA_RECIPE=all_linear bash "$REPO/scripts/ln7_continuous_drain.sh"
echo "[ab] both registered as shadow — run private bakeoff + compare CI; CEO activate winner only"
