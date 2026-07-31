#!/usr/bin/env bash
# Phase A — generate-only on burst GPU, freeze JSONL, destroy (verified 404).
#
# Attempt 6 override example:
#   LN7_BURST_ALLOW_PAID=1 LN7_PHASE_A_DRY_RUN=0 \
#   LN7_BURST_ID=Attempt6 \
#   bash scripts/ln7_bakeoff_phase_a_generate.sh \
#     LN7-2026-07-30T190327Z LN7-2026-07-30T191329Z
#
# QUANTUM-CRYSTAL-ARCH
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/ln7_host_roles.sh
source "$REPO/scripts/ln7_host_roles.sh"

REV_A="${1:-${LN7_BURST_REV_A:-LN7-2026-07-30T190327Z}}"
REV_B="${2:-${LN7_BURST_REV_B:-LN7-2026-07-30T191329Z}}"
DRY="${LN7_PHASE_A_DRY_RUN:-1}"
BURST_ID="${LN7_BURST_ID:-Attempt6}"
STATE_DIR="${LN7_GPU_WATCH_STATE_DIR:-$HOME/.local/state/ln7_gpu_watch}"
mkdir -p "$STATE_DIR"
export LN7_BURST_ID="$BURST_ID"
export LN7_BURST_MODE=generate_freeze
export LN7_PHASE_A_FREEZE_OUT="${LN7_PHASE_A_FREEZE_OUT:-$STATE_DIR/frozen_${BURST_ID}.jsonl}"

echo "=== Phase A generate→freeze→destroy burst_id=$BURST_ID a=$REV_A b=$REV_B dry=$DRY ==="
bash "$REPO/scripts/ln7_host_roles_preflight.sh"
bash "$REPO/scripts/ln7_binary_audit_preflight.sh"

if [[ "$DRY" == "1" || "$DRY" == "true" ]]; then
  echo "PHASE_A_DRY_RUN=PASS (no droplet)"
  exit 0
fi

ln7_assert_paid_burst_allowed || {
  echo "FATAL: paid Phase A refused (set LN7_BURST_ALLOW_PAID=1)" >&2
  exit 10
}

# Live hive burst window: provision → vLLM → identity → generate_freeze → destroy
exec bash "$REPO/scripts/ln7_hive_burst.sh" "$REV_A" "$REV_B"
