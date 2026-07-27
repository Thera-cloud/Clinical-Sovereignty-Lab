#!/usr/bin/env bash
# Pull LN7 coder-class Ollama weights on ORANGE (or any Ollama host).
# Usage: bash backend/scripts/ln7_pull_coder_weights.sh
# Or via jump: ssh -J root@68.183.168.75 root@10.13.13.5 'bash -s' < backend/scripts/ln7_pull_coder_weights.sh
set -euo pipefail

FAST="${LN7_CODE_MODEL_FAST:-qwen2.5-coder:7b-instruct}"
MID="${LN7_CODE_MODEL_MID:-qwen2.5-coder:14b-instruct-q5_K_M}"
DEEP="${LN7_CODE_MODEL_DEEP:-qwen2.5-coder:32b-instruct-q5_K_M}"
HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"

echo "OLLAMA_HOST=$HOST"
for m in "$FAST" "$MID" "$DEEP"; do
  echo "=== pull $m ==="
  ollama pull "$m" || {
    # Tag may differ on registry — try without quant suffix
    alt="${m%-q5_K_M}"
    if [[ "$alt" != "$m" ]]; then
      echo "retry $alt"
      ollama pull "$alt" || true
    fi
  }
done

echo "=== tags ==="
ollama list | grep -i coder || ollama list | head -30

echo "=== smoke fast ==="
curl -sS "${HOST}/api/generate" -d "{\"model\":\"${FAST}\",\"prompt\":\"def add(a,b):\",\"stream\":false,\"options\":{\"num_predict\":32}}" \
  | head -c 400
echo
echo "LN7 coder weight pull complete."
