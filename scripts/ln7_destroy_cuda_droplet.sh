#!/usr/bin/env bash
# Destroy ephemeral LN7 CUDA train droplets (tag: ln7-train).
# Usage: bash scripts/ln7_destroy_cuda_droplet.sh [droplet_id|name]
set -euo pipefail
TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  doctl compute droplet list --tag-name ln7-train --format ID,Name,PublicIPv4,Status,Region
  echo "usage: $0 <id|name>   # destroys one tagged droplet"
  exit 0
fi
doctl compute droplet delete "$TARGET" --force
echo "destroyed $TARGET"
