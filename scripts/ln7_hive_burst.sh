#!/usr/bin/env bash
# QUANTUM-CRYSTAL-ARCH — hive_burst worker body (W3).
# Orchestrated via cli_task_bus kind=hive_burst. Do not run ad-hoc in prod
# without bus claim.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BURST_ID="${LN7_BURST_ID:-burst_manual}"
echo "[hive_burst] start burst_id=${BURST_ID}"

# Prefer existing provision/destroy scripts when present
PROVISION="${ROOT}/scripts/ln7_provision_cuda_droplet.sh"
DESTROY="${ROOT}/scripts/ln7_destroy_cuda_droplet.sh"

SERVE="${ROOT}/scripts/ln7_hive_vllm_serve.sh"

if [[ "${LN7_HIVE_DRY_RUN:-0}" == "1" ]]; then
  echo "[hive_burst] dry-run — skip DO provision"
  echo "LN7_SERVE_URL=${LN7_HIVE_ENDPOINT:-http://127.0.0.1:11436}"
  exit 0
fi

if [[ ! -x "$PROVISION" ]]; then
  echo "[hive_burst] provision script missing or not executable: $PROVISION" >&2
  echo "[hive_burst] skeleton exit 0 (wire DO GPU in deploy)" >&2
  echo "LN7_SERVE_URL=${LN7_HIVE_ENDPOINT:-http://127.0.0.1:11436}"
  exit 0
fi

# shellcheck disable=SC1091
"$PROVISION"
# Optional: start Multi-LoRA vLLM on droplet and print LN7_SERVE_URL=
if [[ -x "$SERVE" ]]; then
  # shellcheck disable=SC1091
  "$SERVE" || {
    echo "[hive_burst] vllm serve failed" >&2
    exit 3
  }
elif [[ -n "${LN7_HIVE_ENDPOINT:-}" ]]; then
  echo "LN7_SERVE_URL=${LN7_HIVE_ENDPOINT}"
fi
# Load adapters from LN7_ADAPTER_INTENTS JSON is done inside provision/vLLM start
# Destroy + verify (suspenders)
if [[ -x "$DESTROY" ]]; then
  "$DESTROY" || {
    echo "[hive_burst] destroy failed — anomaly burst_destroy_fail" >&2
    exit 2
  }
fi

echo "[hive_burst] done burst_id=${BURST_ID}"
