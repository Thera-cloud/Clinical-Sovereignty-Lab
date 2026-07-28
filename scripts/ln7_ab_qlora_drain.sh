#!/usr/bin/env bash
# A/B QLoRA on identical clean JSONL — keep winner only after bakeoff mean↑.
# Runs TWO sequential drains (default vs all_linear). Does NOT auto-activate.
#
#   bash scripts/ln7_ab_qlora_drain.sh
# Optional handoff from GPU watcher (avoids create→delete TOCTOU):
#   LN7_EXISTING_DROPLET_ID / LN7_EXISTING_DROPLET_IP / LN7_EXISTING_DROPLET_REGION
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
export LN7_GPU_REGION="${LN7_GPU_REGION:-tor1}"
export LN7_GPU_SIZE="${LN7_GPU_SIZE:-gpu-4000adax1-20gb}"
export LN7_QLORA_HF_BASE="${LN7_QLORA_HF_BASE:-Qwen/Qwen2.5-Coder-1.5B-Instruct}"
export LN7_QLORA_MIN_ROWS="${LN7_QLORA_MIN_ROWS:-50}"
export LN7_GPU_WATCH_REGIONS="${LN7_GPU_WATCH_REGIONS:-tor1 nyc1 nyc3 atl1 sfo3 fra1}"
export LN7_GPU_PROVISION_RETRIES="${LN7_GPU_PROVISION_RETRIES:-3}"

STATE_DIR="${LN7_GPU_WATCH_STATE_DIR:-$HOME/.local/state/ln7_gpu_watch}"
mkdir -p "$STATE_DIR"
echo "[ab] $(date -u +%Y-%m-%dT%H%M%SZ) start region=$LN7_GPU_REGION force_thin=${LN7_QLORA_FORCE_THIN:-0}"

echo "[ab] recipe=default"
LN7_LORA_RECIPE=default bash "$REPO/scripts/ln7_continuous_drain.sh"

# First recipe consumed any existing probe droplet; second always provisions.
unset LN7_EXISTING_DROPLET_ID LN7_EXISTING_DROPLET_IP LN7_EXISTING_DROPLET_REGION || true

echo "[ab] recipe=all_linear"
LN7_LORA_RECIPE=all_linear bash "$REPO/scripts/ln7_continuous_drain.sh"

echo "[ab] both registered as shadow — run private bakeoff + compare CI; CEO activate winner only"
echo "ok $(date -u +%Y-%m-%dT%H%M%SZ)" >"$STATE_DIR/AB_OK"
rm -f "$STATE_DIR/DRAINING" "$STATE_DIR/AB_FAIL"
