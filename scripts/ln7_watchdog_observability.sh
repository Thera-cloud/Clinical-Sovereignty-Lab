#!/usr/bin/env bash
# Shared observability for LN7 watchdogs.
# Principle (F1 / RED fail-safe on the observability layer):
#   A watchdog that cannot see must freeze, not shoot.
# Positive evidence of death = heartbeat file EXISTS and mtime older than threshold.
# Absent / unreadable heartbeat, or I/O failure on own state files → hold + alarm;
# never re-dispatch anything that costs money (GPU provision, bakeoff re-fire).
#
# Source:  # shellcheck disable=SC1091
#   source "$REPO/scripts/ln7_watchdog_observability.sh"
#
# # QUANTUM-CRYSTAL-ARCH
# shellcheck shell=bash

: "${LN7_GPU_WATCH_STATE_DIR:=$HOME/.local/state/ln7_gpu_watch}"

ln7_wd_state_dir() {
  echo "${LN7_GPU_WATCH_STATE_DIR}"
}

# Write alarm marker (best-effort). Never throws — callers freeze regardless.
ln7_wd_alarm() {
  local kind="${1:?kind}"
  shift || true
  local state detail ts
  state="$(ln7_wd_state_dir)"
  mkdir -p "$state" 2>/dev/null || true
  ts="$(date -u +%Y-%m-%dT%H%M%SZ)"
  detail="$*"
  {
    echo "ts=$ts"
    echo "kind=$kind"
    echo "detail=${detail}"
    echo "host=$(hostname 2>/dev/null || echo unknown)"
    echo "pid=$$"
  } >"$state/WATCHDOG_BLIND_ALARM" 2>/dev/null || true
  # Append-only trail
  {
    echo "$ts kind=$kind ${detail}"
  } >>"$state/WATCHDOG_BLIND_ALARM.jsonl" 2>/dev/null || true
}

# Probe write/read on state dir. Return 0 = can see; 1 = blind (I/O fail).
ln7_wd_probe_io() {
  local state probe
  state="$(ln7_wd_state_dir)"
  if ! mkdir -p "$state" 2>/dev/null; then
    ln7_wd_alarm "state_io_fail" "mkdir_failed path=$state"
    return 1
  fi
  probe="$state/.wd_io_probe.$$"
  if ! printf 'ok %s\n' "$(date -u +%Y-%m-%dT%H%M%SZ)" >"$probe" 2>/dev/null; then
    ln7_wd_alarm "state_io_fail" "write_failed path=$probe"
    return 1
  fi
  if ! [[ -r "$probe" ]] || ! grep -q '^ok ' "$probe" 2>/dev/null; then
    ln7_wd_alarm "state_io_fail" "read_failed path=$probe"
    rm -f "$probe" 2>/dev/null || true
    return 1
  fi
  rm -f "$probe" 2>/dev/null || true
  return 0
}

# Heartbeat age in seconds on stdout when file exists and is readable.
# Return codes:
#   0 — age printed (positive evidence path may apply)
#   1 — absent (no file)
#   2 — unreadable / stat failed
ln7_wd_hb_age() {
  local hb="${1:?heartbeat_path}"
  if [[ ! -e "$hb" ]]; then
    return 1
  fi
  if [[ ! -r "$hb" ]]; then
    return 2
  fi
  local mtime now
  mtime="$(stat -f %m "$hb" 2>/dev/null || stat -c %Y "$hb" 2>/dev/null || true)"
  if [[ -z "$mtime" || "$mtime" == "0" ]]; then
    return 2
  fi
  now="$(date +%s)"
  age=$((now - mtime))
  # Future mtime (clock skew / bad touch) is not evidence of death — treat as fresh.
  if [[ "$age" -lt 0 ]]; then
    age=0
  fi
  echo "$age"
  return 0
}

# True if path looks like an intentional human/operator pause (never auto-clear).
ln7_wd_operator_paused() {
  local state
  state="$(ln7_wd_state_dir)"
  [[ -f "$state/WORKER_PAUSED" ]] || return 1
  # Any WORKER_PAUSED file = freeze re-dispatch (capacity/compare must not shoot)
  return 0
}

# True if COMPARE_LOCK marks an intentional hold (paused_by_*, hold, freeze).
ln7_wd_compare_hold_lock() {
  local lock
  lock="$(ln7_wd_state_dir)/COMPARE_LOCK"
  [[ -f "$lock" ]] || return 1
  if grep -qiE 'paused_by_|hold|freeze|bleed_stop|p1_single' "$lock" 2>/dev/null; then
    return 0
  fi
  return 1
}
