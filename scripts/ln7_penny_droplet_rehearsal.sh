#!/usr/bin/env bash
# Attempt 5 precondition: cheapest non-GPU droplet → destroy verified 404 (~$0.01).
# NOT a CUDA/bakeoff launch. Uses host-role destroy path.
#
#   bash scripts/ln7_penny_droplet_rehearsal.sh
#
# QUANTUM-CRYSTAL-ARCH
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/ln7_host_roles.sh
source "$REPO/scripts/ln7_host_roles.sh"

SIZE="${LN7_PENNY_SIZE:-s-1vcpu-512mb-10gb}"
REGION="${LN7_PENNY_REGION:-nyc3}"
NAME="ln7-penny-$(date -u +%Y%m%d%H%M%S)"

command -v doctl >/dev/null || { echo "FATAL: doctl missing" >&2; exit 2; }
doctl account get >/dev/null || { echo "FATAL: doctl not authenticated" >&2; exit 3; }

KEY_ID="${DO_SSH_KEY_ID:-$(doctl compute ssh-key list --format ID --no-header | awk 'NR==1{print $1}')}"
[[ -n "$KEY_ID" ]] || { echo "FATAL: no SSH key id" >&2; exit 4; }

DROPLET_ID=""
cleanup() {
  if [[ -n "${DROPLET_ID:-}" ]]; then
    echo "[penny] trap destroy id=$DROPLET_ID" >&2
    ln7_destroy_droplet_verified "$DROPLET_ID" 8 || {
      echo "[penny] ANOMALY destroy incomplete id=$DROPLET_ID" >&2
      exit 5
    }
  fi
}
trap cleanup EXIT

echo "[penny] create size=$SIZE region=$REGION name=$NAME" >&2
# Prefer ubuntu image (non-GPU). --wait for IP readiness then destroy immediately.
OUT="$(doctl compute droplet create "$NAME" \
  --size "$SIZE" \
  --image ubuntu-24-04-x64 \
  --region "$REGION" \
  --ssh-keys "$KEY_ID" \
  --tag-names ln7-penny,ephemeral \
  --wait \
  --format ID,Name,Status,PublicIPv4 \
  --no-header)"
DROPLET_ID="$(echo "$OUT" | awk '{print $1}')"
[[ "$DROPLET_ID" =~ ^[0-9]+$ ]] || { echo "FATAL: bad create output: $OUT" >&2; DROPLET_ID=""; exit 6; }
echo "[penny] created id=$DROPLET_ID — destroying via verified path" >&2
ln7_destroy_droplet_verified "$DROPLET_ID" 8
DROPLET_ID=""  # trap no-op
trap - EXIT
echo "PENNY_DESTROY_REHEARSAL=PASS"
