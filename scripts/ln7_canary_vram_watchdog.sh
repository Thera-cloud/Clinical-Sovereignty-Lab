#!/usr/bin/env bash
# ORANGE PEFT VRAM ceiling during canary/bakeoff. Kill PEFT if VRAM ≥ threshold.
#
#   LN7_VRAM_CEILING_MB=18000 bash scripts/ln7_canary_vram_watchdog.sh &
#   # run canary …
#   kill $WATCH_PID
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail
CEIL_MB="${LN7_VRAM_CEILING_MB:-18000}"
INTERVAL_S="${LN7_VRAM_POLL_S:-5}"
GREEN="${LN7_GREEN_HOST:-root@68.183.168.75}"
ORANGE_IP="${LN7_ORANGE_WG:-10.13.13.5}"
SSH_OPTS=(-o BatchMode=yes -o ProxyJump="$GREEN" -o ConnectTimeout=15
          -o ServerAliveInterval=10 -o ServerAliveCountMax=3)

echo "[vram-watch] ceiling=${CEIL_MB}MB interval=${INTERVAL_S}s orange=$ORANGE_IP"
while true; do
  # Prefer nvidia VRAM; fall back to systemd MemoryCurrent (ORANGE CPU PEFT has no nvidia-smi).
  used="$(ssh "${SSH_OPTS[@]}" "root@${ORANGE_IP}" \
    "nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1" \
    2>/dev/null | tr -d '[:space:]' || true)"
  src="nvidia"
  if [[ ! "$used" =~ ^[0-9]+$ ]]; then
    used="$(ssh "${SSH_OPTS[@]}" "root@${ORANGE_IP}" \
      "systemctl show ln7_peft_server -p MemoryCurrent --value 2>/dev/null" \
      2>/dev/null | tr -d '[:space:]' || true)"
    if [[ "$used" =~ ^[0-9]+$ ]] && [[ "$used" != "0" ]] && [[ "$used" != "[notset]" ]]; then
      used=$((used / 1024 / 1024))
      src="cgroup"
    else
      used=""
    fi
  fi
  if [[ "$used" =~ ^[0-9]+$ ]]; then
    echo "[vram-watch] src=${src} used=${used}MB / ceil=${CEIL_MB}MB"
    if [[ "$used" -ge "$CEIL_MB" ]]; then
      echo "[vram-watch] FATAL MEM_CEILING used=${used}MB ≥ ${CEIL_MB}MB — stopping ln7_peft_server" >&2
      ssh "${SSH_OPTS[@]}" "root@${ORANGE_IP}" "systemctl stop ln7_peft_server" || true
      exit 42
    fi
  else
    echo "[vram-watch] warn: could not read nvidia-smi or MemoryCurrent"
  fi
  sleep "$INTERVAL_S"
done
