#!/usr/bin/env bash
# A/B QLoRA on identical clean JSONL — one droplet for both recipes, then private bakeoff compare.
# Does NOT auto-activate (ENABLE_LN7_AUTO_PROMOTE=false / CEO only).
#
#   bash scripts/ln7_ab_qlora_drain.sh
# Optional handoff from GPU watcher:
#   LN7_EXISTING_DROPLET_ID / IP / REGION
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
# Dual-recipe wall + idle grace (heartbeat refreshed during train)
export LN7_GPU_TTL_S="${LN7_GPU_TTL_S:-1800}"
export LN7_GPU_HARD_MAX_S="${LN7_GPU_HARD_MAX_S:-14400}"

STATE_DIR="${LN7_GPU_WATCH_STATE_DIR:-$HOME/.local/state/ln7_gpu_watch}"
mkdir -p "$STATE_DIR"
HANDOFF="$STATE_DIR/droplet_handoff.env"
WORKER_LABEL="${LN7_CONTINUOUS_WORKER_LABEL:-com.sovereign.ln7-continuous-worker}"
SRC_REPO="${LN7_SRC_REPO:-$HOME/Desktop/Clinical-Sovereignty-Lab-2}"

# Auto FORCE_THIN only when clean rows < min (never force-thin a full set).
CLEAN_N="$(python3 - <<PY
import json,re
from pathlib import Path
stub=re.compile(r'^\[patch_hash=', re.I)
diff=re.compile(r'(?m)^(diff --git |--- |\+\+\+ |@@ )')
n=0
p=Path("$REPO/data/ln7_train.jsonl")
if p.is_file():
  for line in p.open():
    line=line.strip()
    if not line: continue
    r=json.loads(line)
    asst=""
    for m in r.get("messages") or []:
      if m.get("role")=="assistant": asst=m.get("content") or ""
    if asst and not stub.match(asst.strip()) and (diff.search(asst) or asst.count(chr(10)+'+')+asst.count(chr(10)+'-')>=2):
      n+=1
print(n)
PY
)"
if [[ "${CLEAN_N:-0}" -lt "${LN7_QLORA_MIN_ROWS}" ]]; then
  export LN7_QLORA_FORCE_THIN="${LN7_QLORA_FORCE_THIN:-1}"
  echo "[ab] thin set clean=$CLEAN_N — FORCE_THIN=${LN7_QLORA_FORCE_THIN}"
else
  unset LN7_QLORA_FORCE_THIN || true
  echo "[ab] clean=$CLEAN_N ≥ min — FORCE_THIN off"
fi

# Mirror sync: Desktop → this REPO tree when running from ~/sovereign-ln7
if [[ -d "$SRC_REPO/scripts" && "$REPO" != "$SRC_REPO" ]]; then
  for f in ln7_continuous_drain.sh ln7_ab_qlora_drain.sh ln7_ab_bakeoff_compare.sh \
           ln7_gpu_capacity_watch.sh ln7_gpu_orphan_reaper.sh ln7_drain_watchdog.sh \
           ln7_ab_compare_watchdog.sh \
           ln7_provision_cuda_droplet.sh ln7_destroy_cuda_droplet.sh; do
    [[ -f "$SRC_REPO/scripts/$f" ]] && cp "$SRC_REPO/scripts/$f" "$REPO/scripts/$f" && chmod +x "$REPO/scripts/$f"
  done
  [[ -f "$SRC_REPO/backend/scripts/ln7_qlora_train.py" ]] \
    && cp "$SRC_REPO/backend/scripts/ln7_qlora_train.py" "$REPO/backend/scripts/ln7_qlora_train.py"
  [[ -f "$SRC_REPO/data/ln7_train.jsonl" ]] \
    && cp "$SRC_REPO/data/ln7_train.jsonl" "$REPO/data/ln7_train.jsonl"
  echo "[ab] synced scripts/jsonl from $SRC_REPO → $REPO"
fi

pause_worker() {
  if launchctl print "gui/$(id -u)/$WORKER_LABEL" >/dev/null 2>&1; then
    launchctl bootout "gui/$(id -u)/$WORKER_LABEL" 2>/dev/null || true
    echo "paused $(date -u +%Y-%m-%dT%H%M%SZ)" >"$STATE_DIR/WORKER_PAUSED"
    echo "[ab] paused $WORKER_LABEL (GPU contention)"
  fi
}
resume_worker() {
  if [[ -f "$STATE_DIR/WORKER_PAUSED" ]]; then
    local plist="$HOME/Library/LaunchAgents/${WORKER_LABEL}.plist"
    if [[ -f "$plist" ]]; then
      launchctl bootstrap "gui/$(id -u)" "$plist" 2>/dev/null \
        || launchctl load "$plist" 2>/dev/null \
        || true
      echo "[ab] resumed $WORKER_LABEL"
    fi
    rm -f "$STATE_DIR/WORKER_PAUSED"
  fi
}
trap 'resume_worker' EXIT

pause_worker
echo "[ab] $(date -u +%Y-%m-%dT%H%M%SZ) start region=$LN7_GPU_REGION force_thin=${LN7_QLORA_FORCE_THIN:-0}"

echo "[ab] recipe=default (KEEP droplet)"
LN7_KEEP_DROPLET=1 \
LN7_HANDOFF_ENV="$HANDOFF" \
LN7_REVISION_OUT="$STATE_DIR/rev_a" \
LN7_LORA_RECIPE=default \
  bash "$REPO/scripts/ln7_continuous_drain.sh"
REV_A="$(tr -d '[:space:]' <"$STATE_DIR/rev_a" 2>/dev/null || true)"
[[ -n "$REV_A" ]] || { echo "[ab] missing rev_a"; exit 6; }

# Load same droplet for B
# shellcheck disable=SC1090
source "$HANDOFF"
export LN7_EXISTING_DROPLET_ID LN7_EXISTING_DROPLET_IP LN7_EXISTING_DROPLET_REGION
echo "[ab] recipe=all_linear (reuse id=$LN7_EXISTING_DROPLET_ID)"

LN7_KEEP_DROPLET=0 \
LN7_KEEP_ON_PREFAIL=0 \
LN7_REVISION_OUT="$STATE_DIR/rev_b" \
LN7_LORA_RECIPE=all_linear \
  bash "$REPO/scripts/ln7_continuous_drain.sh"
REV_B="$(tr -d '[:space:]' <"$STATE_DIR/rev_b" 2>/dev/null || true)"
[[ -n "$REV_B" ]] || { echo "[ab] missing rev_b"; exit 6; }

echo "[ab] private bakeoff compare $REV_A vs $REV_B"
# QUANTUM-CRYSTAL-ARCH — AB_OK only when compare succeeds (not on timeout/partial)
if ! bash "$REPO/scripts/ln7_ab_bakeoff_compare.sh" "$REV_A" "$REV_B"; then
  echo "[ab] bakeoff compare failed — NOT writing AB_OK (revisions still registered as shadow)"
  echo "fail compare $(date -u +%Y-%m-%dT%H%M%SZ) a=$REV_A b=$REV_B" >"$STATE_DIR/AB_FAIL"
  rm -f "$STATE_DIR/DRAINING" "$HANDOFF"
  exit 9
fi

echo "[ab] both registered — CEO activate only if bakeoff gate + READY"
echo "ok $(date -u +%Y-%m-%dT%H%M%SZ) a=$REV_A b=$REV_B" >"$STATE_DIR/AB_OK"
rm -f "$STATE_DIR/DRAINING" "$STATE_DIR/AB_FAIL" "$HANDOFF" "$STATE_DIR/DRAIN_FAIL_COUNT"
echo "[ab] AB_OK written"
