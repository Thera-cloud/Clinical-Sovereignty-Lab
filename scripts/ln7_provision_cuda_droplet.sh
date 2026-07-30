#!/usr/bin/env bash
# Ephemeral LN7 CUDA train host (never GREEN). Cheapest default: RTX 4000 Ada @ tor1.
# Usage: bash scripts/ln7_provision_cuda_droplet.sh [size] [region]
# Destroy: bash scripts/ln7_destroy_cuda_droplet.sh <id>
#
# Injects cloud-init TTL self-destruct (droplet carries its own death).
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail
SIZE="${1:-gpu-4000adax1-20gb}"
REGION="${2:-tor1}"
KEY_ID="${DO_SSH_KEY_ID:-$(doctl compute ssh-key list --format ID --no-header | awk 'NR==1{print $1}')}"
NAME="ln7-qlora-$(date -u +%Y%m%d%H%M)"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
USERDATA=""
if [[ -f "$REPO/scripts/ln7_droplet_ttl_cloudinit.sh" ]]; then
  USERDATA="$(bash "$REPO/scripts/ln7_droplet_ttl_cloudinit.sh")"
fi
ARGS=(
  compute droplet create "$NAME"
  --size "$SIZE"
  --image gpu-h100x1-base
  --region "$REGION"
  --ssh-keys "$KEY_ID"
  --tag-names ln7-train,ephemeral
  --wait
  --format ID,Name,PublicIPv4,Status,Region
)
if [[ -n "$USERDATA" ]]; then
  ARGS+=(--user-data "$USERDATA")
fi
doctl "${ARGS[@]}"
