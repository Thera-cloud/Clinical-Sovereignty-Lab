#!/usr/bin/env bash
# Destroy ephemeral LN7 CUDA train droplets (tag: ln7-train).
# Usage: bash scripts/ln7_destroy_cuda_droplet.sh [droplet_id|name]
# QUANTUM-CRYSTAL-ARCH — verified destroy (retry + 404); never ANOMALY-and-exit.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/ln7_host_roles.sh
source "$REPO/scripts/ln7_host_roles.sh"
TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  doctl compute droplet list --tag-name ln7-train --format ID,Name,PublicIPv4,Status,Region
  echo "usage: $0 <id|name>   # destroys one tagged droplet (verified 404)"
  exit 0
fi
ln7_destroy_droplet_verified "$TARGET"
