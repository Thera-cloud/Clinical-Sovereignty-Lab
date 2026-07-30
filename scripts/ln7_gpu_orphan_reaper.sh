#!/usr/bin/env bash
# Destroy unknown DO GPU droplets tagged ln7-train / ln7-gpu-probe past TTL.
# Protects IDs in probe.env / handoff / fresh DRAIN_HEARTBEAT.
#
#   bash scripts/ln7_gpu_orphan_reaper.sh
#   LN7_ORPHAN_TTL_S=7200 LN7_ORPHAN_DRY_RUN=1 bash scripts/ln7_gpu_orphan_reaper.sh
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail
REPO="${LN7_SOVEREIGN_HOME:-$(cd "$(dirname "$0")/.." && pwd)}"
STATE_DIR="${LN7_GPU_WATCH_STATE_DIR:-$HOME/.local/state/ln7_gpu_watch}"
LOG="${LN7_ORPHAN_REAPER_LOG:-$HOME/Library/Logs/ln7_gpu_orphan_reaper.log}"
TTL_S="${LN7_ORPHAN_TTL_S:-7200}"
DRY="${LN7_ORPHAN_DRY_RUN:-0}"
mkdir -p "$STATE_DIR" "$(dirname "$LOG")"

log() { echo "[orphan-reaper] $(date -u +%Y-%m-%dT%H%M%SZ) $*" | tee -a "$LOG" >&2; }

if ! command -v doctl >/dev/null 2>&1; then
  log "skip: doctl missing"
  exit 0
fi

PROTECT_IDS=" "
protect_id() {
  local id="${1:-}"
  [[ -n "$id" && "$id" =~ ^[0-9]+$ ]] || return 0
  case " $PROTECT_IDS " in
    *" $id "*) ;;
    *) PROTECT_IDS="${PROTECT_IDS}${id} " ;;
  esac
}

is_protected() {
  case " $PROTECT_IDS " in
    *" $1 "*) return 0 ;;
    *) return 1 ;;
  esac
}

PROBE_PROTECT_MAX_S="${LN7_PROBE_PROTECT_MAX_S:-7200}"
HB_FRESH_S="${LN7_DRAIN_HEARTBEAT_STALE_S:-1800}"
now="$(date +%s)"
hb_fresh=0
if [[ -f "$STATE_DIR/DRAIN_HEARTBEAT" ]]; then
  hb_mtime="$(stat -f %m "$STATE_DIR/DRAIN_HEARTBEAT" 2>/dev/null \
    || stat -c %Y "$STATE_DIR/DRAIN_HEARTBEAT" 2>/dev/null || echo 0)"
  if [[ $((now - hb_mtime)) -lt "$HB_FRESH_S" ]]; then
    hb_fresh=1
    protect_id "$(awk -F= '/^droplet_id=/{print $2; exit}' "$STATE_DIR/DRAIN_HEARTBEAT" | tr -d '[:space:]')"
  fi
fi

# QUANTUM-CRYSTAL-ARCH — aged probe.env without fresh drain heartbeat is NOT protected forever
for f in "$STATE_DIR/probe.env" "$STATE_DIR/droplet_handoff.env"; do
  [[ -f "$f" ]] || continue
  f_mtime="$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null || echo 0)"
  age=$((now - f_mtime))
  if [[ "$age" -ge "$PROBE_PROTECT_MAX_S" && "$hb_fresh" != "1" ]]; then
    log "stale ${f##*/} age=${age}s >= ${PROBE_PROTECT_MAX_S}s + no fresh DRAIN_HEARTBEAT — not protecting"
    continue
  fi
  protect_id "$(awk -F= '/^LN7_EXISTING_DROPLET_ID=/{print $2; exit}' "$f" | tr -d '[:space:]')"
done

reap_tag() {
  local tag="$1"
  local line id name created age created_epoch
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    id="$(echo "$line" | awk '{print $1}')"
    name="$(echo "$line" | awk '{print $2}')"
    created="$(echo "$line" | awk '{print $3}')"
    [[ -n "$id" && "$id" =~ ^[0-9]+$ ]] || continue
    if is_protected "$id"; then
      log "protect $id ($name) tag=$tag"
      continue
    fi
    created_clean="${created%%.*}"
    created_clean="${created_clean%Z}Z"
    created_epoch="$(date -j -f '%Y-%m-%dT%H:%M:%SZ' "$created_clean" +%s 2>/dev/null \
      || date -d "${created}" +%s 2>/dev/null || echo 0)"
    now="$(date +%s)"
    age=$((now - created_epoch))
    if [[ "$created_epoch" -eq 0 || "$age" -lt "$TTL_S" ]]; then
      log "young/unknown-age skip $id age=${age}s ttl=${TTL_S}s ($name)"
      continue
    fi
    if [[ "$DRY" == "1" ]]; then
      log "DRY destroy $id age=${age}s tag=$tag name=$name"
      continue
    fi
    log "destroy orphan $id age=${age}s tag=$tag name=$name"
    bash "$REPO/scripts/ln7_destroy_cuda_droplet.sh" "$id" 2>>"$LOG" || \
      doctl compute droplet delete "$id" --force >/dev/null 2>&1 || true
    # Destruction verification (orphan-cost hole) — silence ≠ gone
    sleep 2
    if doctl compute droplet get "$id" >/dev/null 2>&1; then
      log "ALARM burst_destroy_fail: droplet $id still exists after delete"
      mkdir -p "$STATE_DIR"
      echo "ts=$(date -u +%Y-%m-%dT%H%M%SZ) kind=burst_destroy_fail droplet_id=$id" \
        >>"$STATE_DIR/WATCHDOG_BLIND_ALARM.jsonl" 2>/dev/null || true
      echo "ts=$(date -u +%Y-%m-%dT%H%M%SZ)"$'\n'"kind=burst_destroy_fail"$'\n'"detail=droplet_id=$id" \
        >"$STATE_DIR/WATCHDOG_BLIND_ALARM" 2>/dev/null || true
    else
      log "destroy verified gone id=$id"
    fi
  done < <(doctl compute droplet list --tag-name "$tag" \
    --format ID,Name,CreatedAt --no-header 2>/dev/null || true)
}

reap_tag "ln7-train"
reap_tag "ln7-gpu-probe"
log "done protect=${PROTECT_IDS:-none} ttl=${TTL_S}s dry=$DRY"
exit 0
