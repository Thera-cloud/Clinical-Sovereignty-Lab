#!/usr/bin/env bash
# QUANTUM-CRYSTAL-ARCH — Multi-LoRA vLLM serve on ephemeral hive (W3/W4).
# Called from ln7_hive_burst.sh after provision. Must echo LN7_SERVE_URL=.
set -euo pipefail

# When LN7_HIVE_ENDPOINT is pre-set (WireGuard IP:11436), publish that.
# Full vLLM Multi-LoRA bring-up is activated when droplet userdata installs vLLM.
ENDPOINT="${LN7_HIVE_ENDPOINT:-}"
if [[ -z "$ENDPOINT" && -n "${LN7_DROPLET_IP:-}" ]]; then
  ENDPOINT="http://${LN7_DROPLET_IP}:11436"
fi
if [[ -z "$ENDPOINT" ]]; then
  ENDPOINT="http://127.0.0.1:11436"
  echo "[hive_vllm] no droplet IP — stub endpoint ${ENDPOINT}" >&2
fi

# Optional: load intents into serve process (implemented on droplet image)
if [[ -n "${LN7_ADAPTER_INTENTS:-}" ]]; then
  echo "[hive_vllm] intents_bytes=${#LN7_ADAPTER_INTENTS}"
fi

echo "LN7_SERVE_URL=${ENDPOINT}"
exit 0
