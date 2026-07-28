#!/usr/bin/env bash
# BLUE-only: poll DigitalOcean GPU stock; on hit keep the probe droplet, detach A/B drain,
# unload LaunchAgent only after AB_OK. Failed drain clears DRAINING and keeps watching.
#
#   bash scripts/ln7_gpu_capacity_watch.sh              # one check
#   LN7_GPU_WATCH_LOOP=1 bash scripts/ln7_gpu_capacity_watch.sh
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
WORKER_LABEL="${LN7_CONTINUOUS_WORKER_LABEL:-com.sovereign.ln7-continuous-worker}"
STATE_DIR="${LN7_GPU_WATCH_STATE_DIR:-$HOME/.local/state/ln7_gpu_watch}"
LOG="${LN7_GPU_WATCH_LOG:-$HOME/Library/Logs/ln7-gpu-capacity-watch.log}"
DRAIN_LOG="${LN7_AB_DRAIN_LOG:-$HOME/Library/Logs/ln7_ab_qlora_drain.log}"
SRC_REPO="${LN7_SRC_REPO:-$HOME/Desktop/Clinical-Sovereignty-Lab-2}"
AB_OK="$STATE_DIR/AB_OK"
AB_FAIL="$STATE_DIR/AB_FAIL"
DRAINING="$STATE_DIR/DRAINING"
PROBE="$STATE_DIR/probe.env"
PIDFILE="$STATE_DIR/ab_drain.pid"
AUTH_FAILS="$STATE_DIR/doctl_auth_fails"
AUTH_BACKOFF_UNTIL="$STATE_DIR/doctl_auth_backoff_until"
DONE_FILE="$STATE_DIR/AVAILABLE" # legacy; AB_OK is authoritative
mkdir -p "$STATE_DIR" "$(dirname "$LOG")" "$(dirname "$DRAIN_LOG")"

ts() { date -u +%Y-%m-%dT%H%M%SZ; }
log() { echo "[gpu-watch] $(ts) $*" | tee -a "$LOG" >&2; }

sync_mirror() {
  [[ -d "$SRC_REPO/scripts" ]] || return 0
  [[ "$REPO" == "$SRC_REPO" ]] && return 0
  # Desktop TCC: LaunchAgent often cannot read ~/Desktop — skip quietly
  if ! test -r "$SRC_REPO/scripts/ln7_gpu_capacity_watch.sh" 2>/dev/null; then
    log "skip mirror sync — SRC_REPO not readable (TCC?): $SRC_REPO"
    return 0
  fi
  # Skip mid-drain (avoid breaking running scripts mid-parse)
  if [[ -f "$DRAINING" ]]; then
    local pid=""
    [[ -f "$PIDFILE" ]] && pid="$(tr -d '[:space:]' <"$PIDFILE" || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      log "skip mirror sync — drain running pid=$pid"
      return 0
    fi
  fi
  mkdir -p "$REPO/scripts" "$REPO/data" "$REPO/backend/scripts"
  for f in ln7_gpu_capacity_watch.sh ln7_ab_qlora_drain.sh ln7_ab_bakeoff_compare.sh \
           ln7_continuous_drain.sh ln7_provision_cuda_droplet.sh ln7_destroy_cuda_droplet.sh; do
    [[ -f "$SRC_REPO/scripts/$f" ]] && cp "$SRC_REPO/scripts/$f" "$REPO/scripts/$f" 2>/dev/null && chmod +x "$REPO/scripts/$f" || true
  done
  [[ -f "$SRC_REPO/backend/scripts/ln7_qlora_train.py" ]] \
    && cp "$SRC_REPO/backend/scripts/ln7_qlora_train.py" "$REPO/backend/scripts/ln7_qlora_train.py" 2>/dev/null || true
  [[ -f "$SRC_REPO/data/ln7_train.jsonl" ]] \
    && cp "$SRC_REPO/data/ln7_train.jsonl" "$REPO/data/ln7_train.jsonl" 2>/dev/null || true
  log "synced mirror from $SRC_REPO"
}

force_thin_env() {
  local n min
  min="${LN7_QLORA_MIN_ROWS:-50}"
  n="$(python3 - <<PY
import json,re
from pathlib import Path
stub=re.compile(r'^\[patch_hash=', re.I)
diff=re.compile(r'(?m)^(diff --git |--- |\+\+\+ |@@ )')
c=0
p=Path("$REPO/data/ln7_train.jsonl")
if p.is_file():
  for line in p.open():
    line=line.strip()
    if not line: continue
    r=json.loads(line)
    asst=""
    for m in r.get("messages") or []:
      if m.get("role")=="assistant": asst=m.get("content") or ""
    if asst and not stub.match(asst.strip()) and (diff.search(asst) or asst.count(chr(10)+'+')+asst.count(chr(10)+'-')>=2):
      c+=1
print(c)
PY
)"
  if [[ "${n:-0}" -lt "$min" ]]; then
    echo 1
  else
    echo 0
  fi
}

ssh_key_id() {
  if [[ -n "${DO_SSH_KEY_ID:-}" ]]; then
    echo "$DO_SSH_KEY_ID"
    return
  fi
  doctl compute ssh-key list --format ID --no-header 2>/dev/null | awk 'NR==1{print $1}'
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

unload_agent() {
  [[ "$UNLOAD" == "1" ]] || return 0
  local plist="$HOME/Library/LaunchAgents/${LABEL}.plist"
  log "unloading LaunchAgent $LABEL"
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null \
    || launchctl unload "$plist" 2>/dev/null \
    || true
}

auth_backoff_active() {
  [[ -f "$AUTH_BACKOFF_UNTIL" ]] || return 1
  local until now
  until="$(tr -d '[:space:]' <"$AUTH_BACKOFF_UNTIL" || echo 0)"
  now="$(date +%s)"
  [[ "${until:-0}" =~ ^[0-9]+$ ]] || return 1
  [[ "$now" -lt "$until" ]]
}

record_auth_fail() {
  local n until sleep_s
  n=0
  [[ -f "$AUTH_FAILS" ]] && n="$(tr -d '[:space:]' <"$AUTH_FAILS" || echo 0)"
  n=$(( ${n:-0} + 1 ))
  echo "$n" >"$AUTH_FAILS"
  sleep_s=$(( 60 * n ))
  [[ "$sleep_s" -gt 900 ]] && sleep_s=900
  until=$(( $(date +%s) + sleep_s ))
  echo "$until" >"$AUTH_BACKOFF_UNTIL"
  log "doctl auth fail #$n — backoff ${sleep_s}s"
  if [[ "$n" -ge 3 ]]; then
    osascript -e "display notification \"doctl auth Forbidden ×${n} — re-auth / token\" with title \"LN7 GPU capacity\"" 2>/dev/null || true
  fi
}

clear_auth_fail() {
  rm -f "$AUTH_FAILS" "$AUTH_BACKOFF_UNTIL"
}

# Reap dead drain / finalize success or retry window.
reconcile_drain_state() {
  if [[ -f "$AB_OK" ]]; then
    log "AB_OK present ($(cat "$AB_OK")) — watcher complete"
    echo "ab_ok $(cat "$AB_OK")" >"$DONE_FILE"
    unload_agent
    exit 0
  fi

  if [[ -f "$DRAINING" || -f "$PIDFILE" ]]; then
    local pid=""
    [[ -f "$PIDFILE" ]] && pid="$(tr -d '[:space:]' <"$PIDFILE" || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      log "A/B drain still running pid=$pid — skip probe"
      exit 0
    fi
    log "A/B drain dead without AB_OK — clearing DRAINING for re-probe"
    echo "fail $(ts) pid=${pid:-none}" >"$AB_FAIL"
    rm -f "$DRAINING" "$PIDFILE" "$DONE_FILE"
    # Keep probe.env if present (prefail keep) — do NOT mass-destroy
    if [[ ! -f "$PROBE" ]]; then
      doctl compute droplet list --tag-name ln7-gpu-probe --format ID --no-header 2>/dev/null \
        | while read -r did; do
            [[ -n "$did" ]] || continue
            log "destroy orphan probe $did"
            doctl compute droplet delete "$did" --force >/dev/null 2>&1 || true
          done
    else
      log "probe.env retained for retry — not destroying"
    fi
  fi
}

# Create probe and KEEP it (no delete) — hand off to drain to avoid TOCTOU.
probe_region_keep() {
  local region="$1"
  local key name out id ip i status
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
    --tag-names ln7-gpu-probe,ln7-train,ephemeral \
    --format ID --no-header 2>&1)"
  local rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    if echo "$out" | grep -qiE 'GPU limit|droplet limit'; then
      log "probe $SIZE@$region → GPU account limit"
      return 2
    fi
    if echo "$out" | grep -qiE 'not available|Size is not available'; then
      log "probe $SIZE@$region → not available"
      return 1
    fi
    if echo "$out" | grep -qiE 'Forbidden|Unauthorized|authentication'; then
      log "probe $SIZE@$region → doctl auth error: ${out//$'\n'/ }"
      record_auth_fail
      return 3
    fi
    log "probe $SIZE@$region → fail: ${out//$'\n'/ }"
    return 1
  fi
  clear_auth_fail
  id="$(echo "$out" | awk 'NF{print $1; exit}')"
  if [[ -z "$id" ]]; then
    log "probe $SIZE@$region → no droplet id in create output"
    return 1
  fi
  ip=""
  for i in $(seq 1 60); do
    status="$(doctl compute droplet get "$id" --format Status --no-header 2>/dev/null | tr -d '[:space:]' || true)"
    ip="$(doctl compute droplet get "$id" --format PublicIPv4 --no-header 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ -n "$ip" && "$ip" != "0.0.0.0" && "$status" == "active" ]]; then
      break
    fi
    sleep 5
  done
  if [[ -z "$ip" || "$ip" == "0.0.0.0" ]]; then
    log "probe $SIZE@$region → created id=$id but no public IP — destroying"
    doctl compute droplet delete "$id" --force >/dev/null 2>&1 || true
    return 1
  fi
  log "probe $SIZE@$region → KEPT id=$id ip=$ip"
  printf '%s\t%s\t%s\n' "$id" "$ip" "$region"
  return 0
}

detach_ab_drain() {
  local id="$1" ip="$2" region="$3"
  local runner="$STATE_DIR/run_ab_detached.sh"
  local thin
  thin="$(force_thin_env)"
  # Pause continuous worker so it cannot steal GPU quota
  if launchctl print "gui/$(id -u)/$WORKER_LABEL" >/dev/null 2>&1; then
    launchctl bootout "gui/$(id -u)/$WORKER_LABEL" 2>/dev/null || true
    echo "paused $(ts)" >"$STATE_DIR/WORKER_PAUSED"
    log "paused $WORKER_LABEL for A/B drain"
  fi
  cat >"$runner" <<EOF
#!/bin/bash
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export HOME="$HOME"
export LN7_GPU_REGION="$region"
export LN7_GPU_SIZE="$SIZE"
export LN7_QLORA_FORCE_THIN="$thin"
export LN7_QLORA_MIN_ROWS="${LN7_QLORA_MIN_ROWS:-50}"
export LN7_GPU_WATCH_REGIONS="$REGIONS"
export LN7_EXISTING_DROPLET_ID="$id"
export LN7_EXISTING_DROPLET_IP="$ip"
export LN7_EXISTING_DROPLET_REGION="$region"
export LN7_GPU_WATCH_STATE_DIR="$STATE_DIR"
export LN7_SRC_REPO="$SRC_REPO"
export LN7_KEEP_ON_PREFAIL=1
cd "$REPO"
echo "[ab-detached] \$(date -u +%Y-%m-%dT%H%M%SZ) start id=$id ip=$ip region=$region thin=$thin" >>"$DRAIN_LOG"
set +e
bash "$REPO/scripts/ln7_ab_qlora_drain.sh" >>"$DRAIN_LOG" 2>&1
rc=\$?
set -e
# Resume continuous worker if we paused it
if [[ -f "$STATE_DIR/WORKER_PAUSED" ]]; then
  plist="\$HOME/Library/LaunchAgents/$WORKER_LABEL.plist"
  if [[ -f "\$plist" ]]; then
    launchctl bootstrap "gui/\$(id -u)" "\$plist" 2>/dev/null || launchctl load "\$plist" 2>/dev/null || true
  fi
  rm -f "$STATE_DIR/WORKER_PAUSED"
fi
if [[ \$rc -eq 0 ]]; then
  # Prefer richer AB_OK from ln7_ab_qlora_drain.sh (includes rev ids)
  [[ -f "$AB_OK" ]] || echo "ok \$(date -u +%Y-%m-%dT%H%M%SZ)" >"$AB_OK"
  rm -f "$DRAINING" "$AB_FAIL"
  echo "[ab-detached] SUCCESS" >>"$DRAIN_LOG"
  launchctl bootout "gui/\$(id -u)/$LABEL" 2>/dev/null || true
else
  echo "fail rc=\$rc \$(date -u +%Y-%m-%dT%H%M%SZ)" >"$AB_FAIL"
  rm -f "$DRAINING" "$DONE_FILE" "$PIDFILE"
  echo "[ab-detached] FAIL rc=\$rc — watcher may retry probe.env" >>"$DRAIN_LOG"
  # Only destroy if no probe.env handoff (prefail keep writes it)
  if [[ ! -f "$PROBE" ]]; then
    doctl compute droplet delete "$id" --force >/dev/null 2>&1 || true
  fi
fi
exit \$rc
EOF
  chmod +x "$runner"

  /usr/bin/python3 - "$runner" "$PIDFILE" <<'PY'
import os, sys, subprocess, time
runner, pidfile = sys.argv[1], sys.argv[2]
if os.fork() > 0:
    time.sleep(0.2)
    sys.exit(0)
os.setsid()
if os.fork() > 0:
    sys.exit(0)
os.umask(0)
with open(os.devnull, "r") as devnull:
    os.dup2(devnull.fileno(), 0)
log = open(os.devnull, "a")
os.dup2(log.fileno(), 1)
os.dup2(log.fileno(), 2)
p = subprocess.Popen(["/bin/bash", runner], start_new_session=True)
with open(pidfile, "w") as f:
    f.write(str(p.pid))
sys.exit(0)
PY
}

on_probe_kept() {
  local id="$1" ip="$2" region="$3"
  {
    echo "LN7_EXISTING_DROPLET_ID=$id"
    echo "LN7_EXISTING_DROPLET_IP=$ip"
    echo "LN7_EXISTING_DROPLET_REGION=$region"
  } >"$PROBE"
  echo "${SIZE}@${region} kept $(ts) id=$id" >"$DONE_FILE"
  echo "draining $(ts) id=$id" >"$DRAINING"
  rm -f "$AB_FAIL" "$AB_OK"
  log "stock held id=$id ip=$ip region=$region"

  if [[ "$AUTO_DRAIN" != "1" ]]; then
    log "AUTO_DRAIN=0 — droplet KEPT; run manually with probe.env"
    osascript -e "display notification \"GPU kept @ ${region} — AUTO_DRAIN off\" with title \"LN7 GPU capacity\"" 2>/dev/null || true
    return 0
  fi

  osascript -e "display notification \"${SIZE} @ ${region} — detached A/B drain\" with title \"LN7 GPU capacity\"" 2>/dev/null || true
  log "detaching ln7_ab_qlora_drain.sh (log=$DRAIN_LOG)"
  detach_ab_drain "$id" "$ip" "$region"
  log "drain detached; agent stays until AB_OK (or re-probes after AB_FAIL)"
}

try_reuse_probe() {
  [[ -f "$PROBE" ]] || return 1
  # shellcheck disable=SC1090
  source "$PROBE"
  local id="${LN7_EXISTING_DROPLET_ID:-}" ip="${LN7_EXISTING_DROPLET_IP:-}" region="${LN7_EXISTING_DROPLET_REGION:-}"
  [[ -n "$id" && -n "$ip" ]] || return 1
  local st
  st="$(doctl compute droplet get "$id" --format Status --no-header 2>/dev/null | tr -d '[:space:]' || true)"
  if [[ "$st" != "active" ]]; then
    log "stale probe id=$id status=${st:-gone} — clearing"
    rm -f "$PROBE"
    return 1
  fi
  log "reusing kept probe id=$id ip=$ip"
  on_probe_kept "$id" "$ip" "${region:-$PREF}"
  return 0
}

one_check() {
  # macOS LaunchAgent has no util-linux flock — atomic mkdir lock instead
  local lockdir="$STATE_DIR/watch.lock.d"
  if ! mkdir "$lockdir" 2>/dev/null; then
    local holder=""
    [[ -f "$lockdir/pid" ]] && holder="$(tr -d '[:space:]' <"$lockdir/pid" || true)"
    if [[ -n "$holder" ]] && kill -0 "$holder" 2>/dev/null; then
      log "another watch check holds lock — skip (pid=$holder)"
      return 0
    fi
    log "breaking stale watch.lock.d (holder=${holder:-none})"
    rm -rf "$lockdir"
    mkdir "$lockdir" || { log "lock busy — skip"; return 0; }
  fi
  echo "$$" >"$lockdir/pid"
  trap 'rm -rf "$STATE_DIR/watch.lock.d"' EXIT

  sync_mirror
  reconcile_drain_state

  if [[ -f "$AB_OK" ]]; then
    exit 0
  fi

  if auth_backoff_active; then
    log "doctl auth backoff active — skip probe"
    return 1
  fi

  # Prefer retry of kept droplet over create (scarce stock)
  if try_reuse_probe; then
    return 0
  fi

  local r rc line id ip region
  log "check size=$SIZE prefer=$PREF"
  while read -r r; do
    [[ -z "$r" ]] && continue
    set +e
    line="$(probe_region_keep "$r")"
    rc=$?
    set -e
    if [[ $rc -eq 0 ]]; then
      id="$(echo "$line" | awk -F'\t' '{print $1}')"
      ip="$(echo "$line" | awk -F'\t' '{print $2}')"
      region="$(echo "$line" | awk -F'\t' '{print $3}')"
      on_probe_kept "$id" "$ip" "$region"
      return 0
    fi
    if [[ $rc -eq 2 ]]; then
      log "GPU account limit at $r — not starting drain"
      osascript -e "display notification \"GPU account limit — destroy idle ln7-train droplets\" with title \"LN7 GPU capacity\"" 2>/dev/null || true
      return 1
    fi
    if [[ $rc -eq 3 ]]; then
      return 1
    fi
  done < <(ordered_regions)
  log "still unavailable for $SIZE"
  return 1
}

if [[ "${LN7_GPU_WATCH_LOOP:-}" == "1" ]]; then
  while true; do
    one_check || true
    if [[ -f "$AB_OK" ]]; then
      exit 0
    fi
    sleep "$SLEEP"
  done
else
  one_check || exit 1
fi
