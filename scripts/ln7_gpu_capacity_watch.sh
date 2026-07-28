#!/usr/bin/env bash
# BLUE-only: poll DigitalOcean GPU stock; self-stop when a size/region accepts create.
# Uses a create→delete probe (doctl "available" is unreliable when regions are empty).
#
#   bash scripts/ln7_gpu_capacity_watch.sh              # one check
#   LN7_GPU_WATCH_LOOP=1 bash scripts/ln7_gpu_capacity_watch.sh
#
# Env:
#   LN7_GPU_SIZE          default gpu-4000adax1-20gb
#   LN7_GPU_REGION        preferred region (tried first)
#   LN7_GPU_WATCH_REGIONS space-separated fallbacks (default: tor1 nyc1 nyc3 atl1 sfo3 fra1)
#   LN7_GPU_WATCH_SLEEP_S loop sleep (default 900)
#   LN7_GPU_WATCH_AUTO_DRAIN 1=start ln7_ab_qlora_drain.sh on hit (default 1)
#   LN7_QLORA_FORCE_THIN  passed through to drain (default 1 while train set thin)
#   LN7_GPU_WATCH_UNLOAD  1=bootout LaunchAgent on hit (default 1)
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SIZE="${LN7_GPU_SIZE:-gpu-4000adax1-20gb}"
PREF="${LN7_GPU_REGION:-tor1}"
REGIONS="${LN7_GPU_WATCH_REGIONS:-tor1 nyc1 nyc3 atl1 sfo3 fra1}"
SLEEP="${LN7_GPU_WATCH_SLEEP_S:-900}"
AUTO_DRAIN="${LN7_GPU_WATCH_AUTO_DRAIN:-1}"
UNLOAD="${LN7_GPU_WATCH_UNLOAD:-1}"
LABEL="${LN7_GPU_WATCH_LABEL:-com.sovereign.ln7-gpu-capacity-watch}"
STATE_DIR="${LN7_GPU_WATCH_STATE_DIR:-$HOME/.local/state/ln7_gpu_watch}"
LOG="${LN7_GPU_WATCH_LOG:-$HOME/Library/Logs/ln7-gpu-capacity-watch.log}"
DONE_FILE="$STATE_DIR/AVAILABLE"
mkdir -p "$STATE_DIR" "$(dirname "$LOG")"

ts() { date -u +%Y-%m-%dT%H%M%SZ; }
log() { echo "[gpu-watch] $(ts) $*" | tee -a "$LOG"; }

if [[ -f "$DONE_FILE" && "${LN7_GPU_WATCH_IGNORE_DONE:-}" != "1" ]]; then
  log "already available ($(cat "$DONE_FILE")) — exiting (set LN7_GPU_WATCH_IGNORE_DONE=1 to re-probe)"
  exit 0
fi

ssh_key_id() {
  if [[ -n "${DO_SSH_KEY_ID:-}" ]]; then
    echo "$DO_SSH_KEY_ID"
    return
  fi
  doctl compute ssh-key list --format ID --no-header 2>/dev/null | awk 'NR==1{print $1}'
}

# Returns 0 if DO accepted create in region (droplet deleted immediately).
# Returns 1 if size not available / other create failure.
# Returns 2 if account GPU limit exceeded (capacity exists but slot full).
probe_region() {
  local region="$1"
  local key name out id
  key="$(ssh_key_id)"
  if [[ -z "$key" ]]; then
    log "ERROR: no DO SSH key — set DO_SSH_KEY_ID"
    return 1
  fi
  name="ln7-gpu-probe-$(date -u +%Y%m%d%H%M%S)-$RANDOM"
  set +e
  out="$(doctl compute droplet create "$name" \
    --size "$SIZE" \
    --image gpu-h100x1-base \
    --region "$region" \
    --ssh-keys "$key" \
    --tag-names ln7-gpu-probe \
    --format ID --no-header 2>&1)"
  local rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    if echo "$out" | grep -qiE 'GPU limit|droplet limit'; then
      log "probe $SIZE@$region → GPU account limit (stock may exist)"
      return 2
    fi
    if echo "$out" | grep -qiE 'not available|Size is not available'; then
      log "probe $SIZE@$region → not available"
      return 1
    fi
    log "probe $SIZE@$region → fail: ${out//$'\n'/ }"
    return 1
  fi
  id="$(echo "$out" | awk 'NF{print $1; exit}')"
  if [[ -n "$id" ]]; then
    doctl compute droplet delete "$id" --force >/dev/null 2>&1 || true
    # also delete by name if ID parse failed mid-create
  else
    doctl compute droplet list --tag-name ln7-gpu-probe --format ID --no-header 2>/dev/null \
      | while read -r did; do [[ -n "$did" ]] && doctl compute droplet delete "$did" --force >/dev/null 2>&1 || true; done
  fi
  log "probe $SIZE@$region → ACCEPTED (probe droplet deleted)"
  return 0
}

ordered_regions() {
  local seen="|" r
  echo "$PREF"
  seen="|$PREF|"
  for r in $REGIONS; do
    [[ "$seen" == *"|$r|"* ]] && continue
    echo "$r"
    seen="${seen}${r}|"
  done
}

on_available() {
  local region="$1" reason="${2:-probe_ok}"
  echo "${SIZE}@${region} ${reason} $(ts)" >"$DONE_FILE"
  log "AVAILABLE $SIZE@$region ($reason) — writing $DONE_FILE"
  osascript -e "display notification \"${SIZE} @ ${region} — starting A/B drain\" with title \"LN7 GPU capacity\"" 2>/dev/null || true

  if [[ "$AUTO_DRAIN" == "1" ]]; then
    local drain_log="$HOME/Library/Logs/ln7_ab_qlora_drain.log"
    log "starting ln7_ab_qlora_drain.sh (log=$drain_log)"
    (
      cd "$REPO"
      export LN7_GPU_REGION="$region"
      export LN7_GPU_SIZE="$SIZE"
      export LN7_QLORA_FORCE_THIN="${LN7_QLORA_FORCE_THIN:-1}"
      export LN7_QLORA_MIN_ROWS="${LN7_QLORA_MIN_ROWS:-50}"
      nohup bash "$REPO/scripts/ln7_ab_qlora_drain.sh" >>"$drain_log" 2>&1 &
      echo $! >"$STATE_DIR/ab_drain.pid"
    )
  else
    log "AUTO_DRAIN=0 — notify only; run: LN7_GPU_REGION=$region LN7_QLORA_FORCE_THIN=1 bash $REPO/scripts/ln7_ab_qlora_drain.sh"
  fi

  if [[ "$UNLOAD" == "1" ]]; then
    local plist="$HOME/Library/LaunchAgents/${LABEL}.plist"
    log "unloading LaunchAgent $LABEL"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null \
      || launchctl unload "$plist" 2>/dev/null \
      || true
    # keep plist on disk for reinstall; watcher will no-op via DONE_FILE
  fi
}

one_check() {
  local r rc
  log "check size=$SIZE prefer=$PREF"
  while read -r r; do
    [[ -z "$r" ]] && continue
    set +e
    probe_region "$r"
    rc=$?
    set -e
    if [[ $rc -eq 0 ]]; then
      on_available "$r" probe_ok
      return 0
    fi
    if [[ $rc -eq 2 ]]; then
      # Account already at GPU quota — do NOT treat as free capacity / do not auto-drain.
      log "GPU account limit at $r — not marking available (destroy idle ln7-train droplets or raise limit)"
      osascript -e "display notification \"GPU account limit — check existing ln7-train droplets\" with title \"LN7 GPU capacity\"" 2>/dev/null || true
      return 1
    fi
  done < <(ordered_regions)
  log "still unavailable for $SIZE"
  return 1
}

if [[ "${LN7_GPU_WATCH_LOOP:-}" == "1" ]]; then
  while true; do
    if one_check; then
      exit 0
    fi
    sleep "$SLEEP"
  done
else
  one_check || exit 1
fi
