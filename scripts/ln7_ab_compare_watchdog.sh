#!/usr/bin/env bash
# BLUE bakeoff compare watchdog — heartbeat stall → one restart; never activates.
# Install: bash scripts/ln7_install_ab_compare_watchdog.sh
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail
REPO="${LN7_SOVEREIGN_HOME:-$HOME/sovereign-ln7}"
STATE_DIR="${LN7_GPU_WATCH_STATE_DIR:-$HOME/.local/state/ln7_gpu_watch}"
LOG="${LN7_AB_COMPARE_WATCHDOG_LOG:-$HOME/Library/Logs/ln7_ab_compare_watchdog.log}"
STALE_S="${LN7_COMPARE_HEARTBEAT_STALE_S:-900}"
MAX_RESTARTS="${LN7_COMPARE_WATCHDOG_MAX_RESTARTS:-2}"
COMPARE_LABEL="${LN7_AB_COMPARE_LABEL:-ln7-ab-compare}"
COMPARE_SCRIPT="${REPO}/scripts/ln7_ab_bakeoff_compare.sh"
mkdir -p "$STATE_DIR" "$(dirname "$LOG")"

log() { echo "[ab-watchdog] $(date -u +%Y-%m-%dT%H%M%SZ) $*" | tee -a "$LOG" >&2; }

# Done successfully
if [[ -s "$STATE_DIR/AB_COMPARE" ]]; then
  log "AB_COMPARE present — idle"
  exit 0
fi

# No active compare
if [[ ! -f "$STATE_DIR/COMPARE_LOCK" && ! -f "$STATE_DIR/COMPARE_HEARTBEAT" ]]; then
  exit 0
fi

HB="$STATE_DIR/COMPARE_HEARTBEAT"
if [[ ! -f "$HB" ]]; then
  log "COMPARE_LOCK without heartbeat — treat as stale"
  age=$STALE_S
else
  # macOS stat
  mtime="$(stat -f %m "$HB" 2>/dev/null || stat -c %Y "$HB" 2>/dev/null || echo 0)"
  now="$(date +%s)"
  age=$(( now - mtime ))
fi

if [[ "$age" -lt "$STALE_S" ]]; then
  # Still fresh — ensure continuous worker stays paused while lock held
  if [[ -f "$STATE_DIR/COMPARE_LOCK" ]]; then
    launchctl bootout "gui/$(id -u)/com.sovereign.ln7-continuous-worker" 2>/dev/null || true
  fi
  exit 0
fi

log "stale heartbeat age=${age}s (limit=${STALE_S}s)"

# Parse revs from heartbeat or lock
REV_A=""
REV_B=""
if [[ -f "$HB" ]]; then
  REV_A="$(awk -F= '/^rev_a=/{print $2; exit}' "$HB")"
  REV_B="$(awk -F= '/^rev_b=/{print $2; exit}' "$HB")"
fi
if [[ -z "$REV_A" || -z "$REV_B" ]] && [[ -f "$STATE_DIR/COMPARE_LOCK" ]]; then
  REV_A="$(sed -n 's/.* a=\([^ ]*\).*/\1/p' "$STATE_DIR/COMPARE_LOCK" | head -1)"
  REV_B="$(sed -n 's/.* b=\([^ ]*\).*/\1/p' "$STATE_DIR/COMPARE_LOCK" | head -1)"
fi
if [[ -z "$REV_A" || -z "$REV_B" ]]; then
  for f in rev_a rev_b; do
    [[ -f "$STATE_DIR/$f" ]] || continue
  done
  REV_A="${REV_A:-$(cat "$STATE_DIR/rev_a" 2>/dev/null || true)}"
  REV_B="${REV_B:-$(cat "$STATE_DIR/rev_b" 2>/dev/null || true)}"
fi

if [[ -z "$REV_A" || -z "$REV_B" ]]; then
  log "FAIL: cannot resolve rev_a/rev_b for restart — clearing stale lock"
  rm -f "$STATE_DIR/COMPARE_LOCK"
  exit 1
fi

RESTARTS=0
[[ -f "$STATE_DIR/COMPARE_WATCHDOG_RESTARTS" ]] && RESTARTS="$(cat "$STATE_DIR/COMPARE_WATCHDOG_RESTARTS" | tr -d '[:space:]')"
RESTARTS="${RESTARTS:-0}"
if [[ "$RESTARTS" -ge "$MAX_RESTARTS" ]]; then
  log "FAIL: max restarts ($MAX_RESTARTS) reached — manual intervention required"
  echo "stale $(date -u +%Y-%m-%dT%H%M%SZ) restarts=$RESTARTS a=$REV_A b=$REV_B" >"$STATE_DIR/COMPARE_STALE"
  exit 2
fi

# Kill stuck compare + peft deploy children
log "restart $((RESTARTS+1))/$MAX_RESTARTS for $REV_A vs $REV_B"
pkill -f 'ln7_ab_bakeoff_compare.sh' 2>/dev/null || true
pkill -f 'ln7_deploy_peft_serve_orange.sh' 2>/dev/null || true
launchctl remove "$COMPARE_LABEL" 2>/dev/null || true
sleep 2

echo "$((RESTARTS + 1))" >"$STATE_DIR/COMPARE_WATCHDOG_RESTARTS"
echo "$REV_A" >"$STATE_DIR/rev_a"
echo "$REV_B" >"$STATE_DIR/rev_b"
rm -f "$STATE_DIR/COMPARE_STALE"

COMPARE_LOG="${LN7_AB_COMPARE_LOG:-$HOME/Library/Logs/ln7_ab_bakeoff_compare_rerun.log}"
: >>"$COMPARE_LOG"
log "launchctl submit $COMPARE_LABEL"
launchctl submit -l "$COMPARE_LABEL" -o "$COMPARE_LOG" -e "$COMPARE_LOG" -- \
  /bin/bash "$COMPARE_SCRIPT" "$REV_A" "$REV_B"
log "submitted"
exit 0
