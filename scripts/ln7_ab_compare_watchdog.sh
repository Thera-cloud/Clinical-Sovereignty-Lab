#!/usr/bin/env bash
# BLUE bakeoff compare watchdog — heartbeat stall → restart; on stall-exhaustion or
# idle-after-success, auto-advances to the newest untested shadow revision so the
# promotion loop never permanently stalls on one bad/slow candidate.
# Install: bash scripts/ln7_install_ab_compare_watchdog.sh
#
# F1 observability (2026-07-30): a watchdog that cannot see must freeze, not shoot.
# Death requires positive staleness (HB exists AND mtime > threshold). Absent /
# unreadable HB, state I/O failure, or operator pause → hold + alarm; never
# re-dispatch bakeoff/GPU work.
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
BASELINE_REV="${LN7_AB_BASELINE_REV:-LN7-fast-baseline}"
GREEN_HOST="${LN7_GREEN_HOST:-root@68.183.168.75}"
TESTED_LOG="$STATE_DIR/BASELINE_TESTED"
mkdir -p "$STATE_DIR" "$(dirname "$LOG")"
touch "$TESTED_LOG"

# shellcheck disable=SC1091
source "${REPO}/scripts/ln7_watchdog_observability.sh" 2>/dev/null \
  || source "$(cd "$(dirname "$0")" && pwd)/ln7_watchdog_observability.sh"

log() { echo "[ab-watchdog] $(date -u +%Y-%m-%dT%H%M%SZ) $*" | tee -a "$LOG" >&2; }

# ── Blind / operator hold — never re-dispatch ────────────────────────────────
if ! ln7_wd_probe_io; then
  log "BLIND: state I/O failed — freeze (no re-dispatch)"
  exit 0
fi
if ln7_wd_operator_paused; then
  log "WORKER_PAUSED present — freeze (operator hold)"
  exit 0
fi
if ln7_wd_compare_hold_lock; then
  log "COMPARE_LOCK hold marker — freeze (no re-dispatch)"
  exit 0
fi

# Newest shadow revision from GREEN's Postgres, excluding anything already tried
# against baseline (win/lose/inconclusive). Empty output = nothing new to test yet.
pick_next_candidate() {
  local excl=""
  if [[ -s "$TESTED_LOG" ]]; then
    excl="$(paste -sd, "$TESTED_LOG" | sed "s/,/','/g")"
  fi
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$GREEN_HOST" "EXCL='$excl' bash -s" <<'REMOTE' 2>/dev/null | tr -d '[:space:]'
SQL="SELECT revision_id FROM ln7_revisions WHERE status='shadow'"
if [[ -n "${EXCL:-}" ]]; then
  SQL="$SQL AND revision_id NOT IN ('$EXCL')"
fi
SQL="$SQL ORDER BY created_at DESC LIMIT 1;"
docker exec nate_postgres psql -U nate_admin -d little_nate -t -A -c "$SQL" 2>/dev/null
REMOTE
}

mark_tested() {
  local rev="$1"
  [[ -n "$rev" && "$rev" != "$BASELINE_REV" ]] || return 0
  grep -qxF "$rev" "$TESTED_LOG" 2>/dev/null || echo "$rev" >>"$TESTED_LOG"
}

launch_compare() {
  local a="$1" b="$2"
  # Re-check freeze gates immediately before money-touching dispatch
  if ln7_wd_operator_paused || ln7_wd_compare_hold_lock; then
    log "launch_compare aborted — pause/hold active"
    return 1
  fi
  if ! ln7_wd_probe_io; then
    log "launch_compare aborted — blind I/O"
    return 1
  fi
  echo "0" >"$STATE_DIR/COMPARE_WATCHDOG_RESTARTS"
  echo "$a" >"$STATE_DIR/rev_a"
  echo "$b" >"$STATE_DIR/rev_b"
  rm -f "$STATE_DIR/COMPARE_STALE"
  local out_log="${LN7_AB_COMPARE_LOG:-$HOME/Library/Logs/ln7_ab_bakeoff_compare_rerun.log}"
  : >>"$out_log"
  launchctl remove "$COMPARE_LABEL" 2>/dev/null || true
  sleep 1
  log "launchctl submit $COMPARE_LABEL for $a vs $b"
  launchctl submit -l "$COMPARE_LABEL" -o "$out_log" -e "$out_log" -- \
    /bin/bash "$COMPARE_SCRIPT" "$a" "$b"
  log "submitted"
}

# Archive a completed AB_COMPARE (same pattern the compare script's own archive uses)
archive_ab_compare() {
  local ts
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$STATE_DIR/archive"
  for f in AB_COMPARE rev_a rev_b; do
    [[ -f "$STATE_DIR/$f" ]] && cp "$STATE_DIR/$f" "$STATE_DIR/archive/${f}.${ts}" 2>/dev/null || true
  done
  rm -f "$STATE_DIR/AB_COMPARE"
}

# ── Case 1: last compare completed successfully ──────────────────────────────
if [[ -s "$STATE_DIR/AB_COMPARE" ]]; then
  winner_rev="$(python3 -c "import json,sys; d=json.load(open('$STATE_DIR/AB_COMPARE')); print(d.get('b',{}).get('revision_id',''))" 2>/dev/null || true)"
  mark_tested "$winner_rev"
  next="$(pick_next_candidate || true)"
  if [[ -n "$next" ]]; then
    log "AB_COMPARE complete for $winner_rev — advancing to next candidate $next"
    archive_ab_compare
    launch_compare "$BASELINE_REV" "$next" || true
  else
    log "AB_COMPARE present — idle (no new shadow revision to test yet)"
  fi
  exit 0
fi

# ── Case 2: no active compare — cold start only with explicit targets ────────
# Never treat "no heartbeat" as death. Cold start requires rev_a+rev_b files
# (or pick_next) AND no freeze markers — already checked above.
if [[ ! -f "$STATE_DIR/COMPARE_LOCK" && ! -f "$STATE_DIR/COMPARE_HEARTBEAT" ]]; then
  rev_a_file="$(cat "$STATE_DIR/rev_a" 2>/dev/null || true)"
  rev_b_file="$(cat "$STATE_DIR/rev_b" 2>/dev/null || true)"
  if [[ -n "$rev_a_file" && -n "$rev_b_file" ]] && ! grep -qxF "$rev_b_file" "$TESTED_LOG" 2>/dev/null; then
    log "cold start — no active compare, launching pending target $rev_a_file vs $rev_b_file"
    launch_compare "$rev_a_file" "$rev_b_file" || true
    exit 0
  fi
  next="$(pick_next_candidate || true)"
  if [[ -n "$next" ]]; then
    log "cold start — no target set, picking newest untested candidate $next"
    launch_compare "$BASELINE_REV" "$next" || true
  fi
  exit 0
fi

HB="$STATE_DIR/COMPARE_HEARTBEAT"
DEPLOY_STALE_S="${LN7_COMPARE_DEPLOY_STALE_S:-720}"
PHASE=""
age=""
hb_rc=0
age="$(ln7_wd_hb_age "$HB")" && hb_rc=0 || hb_rc=$?

if [[ "$hb_rc" -eq 1 ]]; then
  # Absent heartbeat while lock/activity claimed — FREEZE (was: treat as stale → shoot)
  ln7_wd_alarm "hb_absent" "COMPARE_LOCK_or_activity without COMPARE_HEARTBEAT"
  log "BLIND: heartbeat absent — freeze + alarm (no re-dispatch)"
  exit 0
fi
if [[ "$hb_rc" -eq 2 ]]; then
  ln7_wd_alarm "hb_unreadable" "COMPARE_HEARTBEAT exists but unreadable/stat_failed"
  log "BLIND: heartbeat unreadable — freeze + alarm (no re-dispatch)"
  exit 0
fi

PHASE="$(awk -F= '/^phase=/{print $2; exit}' "$HB" 2>/dev/null | tr -d '[:space:]' || true)"

# PEFT deploy hung: tighter stale than bakeoff poll
EFFECTIVE_STALE="$STALE_S"
case "$PHASE" in
  deploy|deploy_*|peft|peft_*)
    EFFECTIVE_STALE="$DEPLOY_STALE_S"
    ;;
  paused_p1*|paused_*|hold|freeze)
    # Operator/bleed-stop phases in HB body — freeze even if age would be "stale"
    ln7_wd_alarm "hb_hold_phase" "phase=$PHASE"
    log "hold phase=$PHASE — freeze (no re-dispatch)"
    exit 0
    ;;
esac

if [[ "$age" -lt "$EFFECTIVE_STALE" ]]; then
  # Still fresh — ensure continuous worker stays paused while lock held
  if [[ -f "$STATE_DIR/COMPARE_LOCK" ]]; then
    launchctl bootout "gui/$(id -u)/com.sovereign.ln7-continuous-worker" 2>/dev/null || true
  fi
  exit 0
fi

# Positive staleness only — heartbeat existed, readable, and past threshold
log "stale heartbeat age=${age}s (limit=${EFFECTIVE_STALE}s phase=${PHASE:-unknown})"

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
  REV_A="${REV_A:-$(cat "$STATE_DIR/rev_a" 2>/dev/null || true)}"
  REV_B="${REV_B:-$(cat "$STATE_DIR/rev_b" 2>/dev/null || true)}"
fi

if [[ -z "$REV_A" || -z "$REV_B" ]]; then
  ln7_wd_alarm "rev_unresolved" "stale_hb but cannot resolve rev_a/rev_b — freeze (do not clear lock blindly)"
  log "FAIL: cannot resolve rev_a/rev_b — freeze + alarm (lock retained)"
  exit 1
fi

RESTARTS=0
[[ -f "$STATE_DIR/COMPARE_WATCHDOG_RESTARTS" ]] && RESTARTS="$(cat "$STATE_DIR/COMPARE_WATCHDOG_RESTARTS" | tr -d '[:space:]')"
RESTARTS="${RESTARTS:-0}"

# Kill stuck compare + peft deploy SSH children (phase=deploy stall) — always,
# whether we're about to retry the same pair or advance to a new one.
pkill -f 'ln7_ab_bakeoff_compare.sh' 2>/dev/null || true
pkill -f 'ln7_deploy_peft_serve_orange.sh' 2>/dev/null || true
pkill -f 'ssh.*10\.13\.13\.5.*11435' 2>/dev/null || true
pkill -f 'ssh.*ln7.*peft' 2>/dev/null || true
launchctl remove "$COMPARE_LABEL" 2>/dev/null || true
sleep 2

if [[ "$RESTARTS" -ge "$MAX_RESTARTS" ]]; then
  # QUANTUM-CRYSTAL-ARCH — never stall forever on one candidate: mark it
  # inconclusive (deploy/infra kept failing) and advance to the next one.
  log "max restarts ($MAX_RESTARTS) reached for $REV_A vs $REV_B — marking inconclusive, advancing"
  mark_tested "$REV_B"
  rm -f "$STATE_DIR/COMPARE_LOCK" "$STATE_DIR/COMPARE_HEARTBEAT"
  next="$(pick_next_candidate || true)"
  if [[ -n "$next" ]]; then
    launch_compare "$REV_A" "$next" || true
  else
    log "no further untested candidates — will retry same pair next tick once training produces more"
    echo "stale $(date -u +%Y-%m-%dT%H%M%SZ) restarts=$RESTARTS a=$REV_A b=$REV_B" >"$STATE_DIR/COMPARE_STALE"
  fi
  exit 0
fi

if ln7_wd_operator_paused || ln7_wd_compare_hold_lock || ! ln7_wd_probe_io; then
  ln7_wd_alarm "restart_aborted_blind" "positive_stale but freeze gate tripped before re-dispatch"
  log "restart aborted — freeze gate (no re-dispatch)"
  exit 0
fi

log "restart $((RESTARTS+1))/$MAX_RESTARTS for $REV_A vs $REV_B phase=${PHASE:-unknown}"
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
