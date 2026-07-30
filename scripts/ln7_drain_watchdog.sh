#!/usr/bin/env bash
# BLUE drain/train watchdog — stale DRAIN_HEARTBEAT or dead mid-train → clear DRAINING + reap.
# Same LaunchAgent pattern as compare watchdog.
#
# F1 observability (2026-07-30): a watchdog that cannot see must freeze, not shoot.
# Stale-kill requires heartbeat EXISTS + readable + mtime past threshold while pid alive.
# Absent/unreadable HB with live pid → freeze + alarm (do not destroy / re-probe).
# Orphan reaper still runs as the third strap (independent of heartbeat).
#
# Install: bash scripts/ln7_install_drain_watchdog.sh
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail
REPO="${LN7_SOVEREIGN_HOME:-$HOME/sovereign-ln7}"
STATE_DIR="${LN7_GPU_WATCH_STATE_DIR:-$HOME/.local/state/ln7_gpu_watch}"
LOG="${LN7_DRAIN_WATCHDOG_LOG:-$HOME/Library/Logs/ln7_drain_watchdog.log}"
STALE_S="${LN7_DRAIN_HEARTBEAT_STALE_S:-1800}"
MAX_KILLS="${LN7_DRAIN_WATCHDOG_MAX_KILLS:-3}"
DRAINING="$STATE_DIR/DRAINING"
PIDFILE="$STATE_DIR/ab_drain.pid"
DRAIN_HB="$STATE_DIR/DRAIN_HEARTBEAT"
DRAIN_LOCK="$STATE_DIR/DRAIN_LOCK"
TTL_HB="$STATE_DIR/ttl_heartbeat"
mkdir -p "$STATE_DIR" "$(dirname "$LOG")"

# shellcheck disable=SC1091
source "${REPO}/scripts/ln7_watchdog_observability.sh" 2>/dev/null \
  || source "$(cd "$(dirname "$0")" && pwd)/ln7_watchdog_observability.sh"

log() { echo "[drain-watchdog] $(date -u +%Y-%m-%dT%H%M%SZ) $*" | tee -a "$LOG" >&2; }

# Always attempt orphan reaper (cheap; protects live train IDs) — third strap
if [[ -x "$REPO/scripts/ln7_gpu_orphan_reaper.sh" ]]; then
  bash "$REPO/scripts/ln7_gpu_orphan_reaper.sh" || true
elif [[ -f "$REPO/scripts/ln7_gpu_orphan_reaper.sh" ]]; then
  bash "$REPO/scripts/ln7_gpu_orphan_reaper.sh" || true
fi

# Compare owns BLUE — do not kill drain under compare lock (orphan reaper already ran)
if [[ -f "$STATE_DIR/COMPARE_LOCK" ]]; then
  exit 0
fi

if ln7_wd_operator_paused; then
  log "WORKER_PAUSED — freeze drain kill path (orphan reaper already ran)"
  exit 0
fi

if ! ln7_wd_probe_io; then
  log "BLIND: state I/O failed — freeze (no kill/re-probe)"
  exit 0
fi

# Nothing claiming a drain
if [[ ! -f "$DRAINING" && ! -f "$DRAIN_LOCK" && ! -f "$PIDFILE" ]]; then
  exit 0
fi

pid_alive() {
  local p="$1"
  [[ -n "$p" && "$p" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$p" 2>/dev/null
}

PID=""
[[ -f "$PIDFILE" ]] && PID="$(tr -d '[:space:]' <"$PIDFILE" || true)"
if [[ -z "$PID" && -f "$DRAIN_HB" ]]; then
  PID="$(awk -F= '/^pid=/{print $2; exit}' "$DRAIN_HB" | tr -d '[:space:]')"
fi
if [[ -z "$PID" && -f "$DRAIN_LOCK" ]]; then
  PID="$(awk -F= '/^pid=/{print $2; exit}' "$DRAIN_LOCK" | tr -d '[:space:]')"
fi

ALIVE=0
pid_alive "$PID" && ALIVE=1

# Resolve heartbeat age with positive-evidence semantics
HB_PATH=""
AGE_HB=""
hb_rc=1
if [[ -f "$DRAIN_HB" ]]; then
  HB_PATH="$DRAIN_HB"
  AGE_HB="$(ln7_wd_hb_age "$DRAIN_HB")" && hb_rc=0 || hb_rc=$?
elif [[ -f "$TTL_HB" ]]; then
  HB_PATH="$TTL_HB"
  AGE_HB="$(ln7_wd_hb_age "$TTL_HB")" && hb_rc=0 || hb_rc=$?
else
  hb_rc=1
fi

# Live pid + missing/unreadable HB → freeze (was: treat missing as stale → kill)
if [[ "$ALIVE" == "1" && "$hb_rc" -ne 0 ]]; then
  if [[ "$hb_rc" -eq 1 ]]; then
    ln7_wd_alarm "drain_hb_absent" "live_pid=$PID DRAINING set but no heartbeat"
    log "BLIND: live drain pid=$PID but heartbeat absent — freeze + alarm"
  else
    ln7_wd_alarm "drain_hb_unreadable" "live_pid=$PID path=${HB_PATH:-none}"
    log "BLIND: live drain pid=$PID but heartbeat unreadable — freeze + alarm"
  fi
  exit 0
fi

if [[ "$ALIVE" == "1" && "$hb_rc" -eq 0 && "$AGE_HB" -lt "$STALE_S" ]]; then
  exit 0
fi

# Dead process but DRAINING left — clear for capacity watch re-probe
if [[ "$ALIVE" != "1" ]]; then
  log "drain dead pid=${PID:-none} — clear DRAINING/LOCK (hb_rc=${hb_rc} age_hb=${AGE_HB:-n/a})"
  echo "fail $(date -u +%Y-%m-%dT%H%M%SZ) pid=${PID:-none} watchdog=dead" >"$STATE_DIR/AB_FAIL"
  rm -f "$DRAINING" "$PIDFILE" "$DRAIN_LOCK" "$DRAIN_HB" "$TTL_HB"
  if [[ -f "$STATE_DIR/probe.env" ]]; then
    mv "$STATE_DIR/probe.env" "$STATE_DIR/probe.env.stale.$(date -u +%Y%m%d%H%M%S)" 2>/dev/null || \
      rm -f "$STATE_DIR/probe.env"
  fi
  bash "$REPO/scripts/ln7_gpu_orphan_reaper.sh" || true
  exit 0
fi

# Alive + positive stale heartbeat — mid-train hung
KILLS=0
[[ -f "$STATE_DIR/DRAIN_WATCHDOG_KILLS" ]] && KILLS="$(tr -d '[:space:]' <"$STATE_DIR/DRAIN_WATCHDOG_KILLS" || true)"
KILLS="${KILLS:-0}"
if [[ "$KILLS" -ge "$MAX_KILLS" ]]; then
  log "FAIL: max kills ($MAX_KILLS) — manual intervention"
  echo "stale $(date -u +%Y-%m-%dT%H%M%SZ) kills=$KILLS pid=$PID" >"$STATE_DIR/DRAIN_STALE"
  exit 2
fi

DROPLET_ID="$(awk -F= '/^droplet_id=/{print $2; exit}' "$DRAIN_HB" 2>/dev/null | tr -d '[:space:]')"
[[ -z "$DROPLET_ID" && -f "$STATE_DIR/probe.env" ]] && \
  DROPLET_ID="$(awk -F= '/^LN7_EXISTING_DROPLET_ID=/{print $2; exit}' "$STATE_DIR/probe.env" | tr -d '[:space:]')"

log "stale heartbeat age=${AGE_HB}s (limit=${STALE_S}s) pid=$PID droplet=${DROPLET_ID:-none} — kill"
echo "$((KILLS + 1))" >"$STATE_DIR/DRAIN_WATCHDOG_KILLS"

# Kill drain tree (continuous + ab drain wrappers)
pkill -f 'ln7_continuous_drain.sh' 2>/dev/null || true
pkill -f 'ln7_ab_qlora_drain.sh' 2>/dev/null || true
[[ -n "$PID" ]] && kill "$PID" 2>/dev/null || true
sleep 2
[[ -n "$PID" ]] && kill -9 "$PID" 2>/dev/null || true

if [[ -n "$DROPLET_ID" ]]; then
  bash "$REPO/scripts/ln7_destroy_cuda_droplet.sh" "$DROPLET_ID" || true
  # Destruction verification (orphan-cost hole)
  if doctl compute droplet get "$DROPLET_ID" >/dev/null 2>&1; then
    ln7_wd_alarm "burst_destroy_fail" "droplet_id=$DROPLET_ID still exists after delete"
    log "ALARM: droplet $DROPLET_ID still present after destroy"
  fi
fi

echo "fail $(date -u +%Y-%m-%dT%H%M%SZ) pid=$PID watchdog=stale_hb" >"$STATE_DIR/AB_FAIL"
rm -f "$DRAINING" "$PIDFILE" "$DRAIN_LOCK" "$DRAIN_HB" "$TTL_HB" \
  "$STATE_DIR/probe.env" "$STATE_DIR/droplet_handoff.env"
bash "$REPO/scripts/ln7_gpu_orphan_reaper.sh" || true
log "cleared — capacity watch may re-probe"
exit 0
