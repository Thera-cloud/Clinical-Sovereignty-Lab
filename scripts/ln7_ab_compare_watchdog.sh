#!/usr/bin/env bash
# BLUE bakeoff compare watchdog — heartbeat stall → restart; on stall-exhaustion or
# idle-after-success, auto-advances to the newest untested shadow revision so the
# promotion loop never permanently stalls on one bad/slow candidate.
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
BASELINE_REV="${LN7_AB_BASELINE_REV:-LN7-fast-baseline}"
GREEN_HOST="${LN7_GREEN_HOST:-root@68.183.168.75}"
TESTED_LOG="$STATE_DIR/BASELINE_TESTED"
mkdir -p "$STATE_DIR" "$(dirname "$LOG")"
touch "$TESTED_LOG"

log() { echo "[ab-watchdog] $(date -u +%Y-%m-%dT%H%M%SZ) $*" | tee -a "$LOG" >&2; }

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
    launch_compare "$BASELINE_REV" "$next"
  else
    log "AB_COMPARE present — idle (no new shadow revision to test yet)"
  fi
  exit 0
fi

# ── Case 2: no active compare and nothing ever ran — cold start ─────────────
if [[ ! -f "$STATE_DIR/COMPARE_LOCK" && ! -f "$STATE_DIR/COMPARE_HEARTBEAT" ]]; then
  rev_a_file="$(cat "$STATE_DIR/rev_a" 2>/dev/null || true)"
  rev_b_file="$(cat "$STATE_DIR/rev_b" 2>/dev/null || true)"
  if [[ -n "$rev_a_file" && -n "$rev_b_file" ]] && ! grep -qxF "$rev_b_file" "$TESTED_LOG" 2>/dev/null; then
    log "cold start — no active compare, launching pending target $rev_a_file vs $rev_b_file"
    launch_compare "$rev_a_file" "$rev_b_file"
    exit 0
  fi
  next="$(pick_next_candidate || true)"
  if [[ -n "$next" ]]; then
    log "cold start — no target set, picking newest untested candidate $next"
    launch_compare "$BASELINE_REV" "$next"
  fi
  exit 0
fi

HB="$STATE_DIR/COMPARE_HEARTBEAT"
DEPLOY_STALE_S="${LN7_COMPARE_DEPLOY_STALE_S:-720}"
PHASE=""
if [[ ! -f "$HB" ]]; then
  log "COMPARE_LOCK without heartbeat — treat as stale"
  age=$STALE_S
else
  # macOS stat
  mtime="$(stat -f %m "$HB" 2>/dev/null || stat -c %Y "$HB" 2>/dev/null || echo 0)"
  now="$(date +%s)"
  age=$(( now - mtime ))
  PHASE="$(awk -F= '/^phase=/{print $2; exit}' "$HB" | tr -d '[:space:]')"
fi

# PEFT deploy hung: tighter stale than bakeoff poll
EFFECTIVE_STALE="$STALE_S"
case "$PHASE" in
  deploy|deploy_*|peft|peft_*)
    EFFECTIVE_STALE="$DEPLOY_STALE_S"
    ;;
esac

if [[ "$age" -lt "$EFFECTIVE_STALE" ]]; then
  # Still fresh — ensure continuous worker stays paused while lock held
  if [[ -f "$STATE_DIR/COMPARE_LOCK" ]]; then
    launchctl bootout "gui/$(id -u)/com.sovereign.ln7-continuous-worker" 2>/dev/null || true
  fi
  exit 0
fi

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
  log "FAIL: cannot resolve rev_a/rev_b for restart — clearing stale lock"
  rm -f "$STATE_DIR/COMPARE_LOCK"
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
    launch_compare "$REV_A" "$next"
  else
    log "no further untested candidates — will retry same pair next tick once training produces more"
    echo "stale $(date -u +%Y-%m-%dT%H%M%SZ) restarts=$RESTARTS a=$REV_A b=$REV_B" >"$STATE_DIR/COMPARE_STALE"
  fi
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
