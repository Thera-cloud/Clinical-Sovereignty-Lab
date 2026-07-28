#!/usr/bin/env bash
# Install BLUE LaunchAgent: poll DO GPU capacity; keep probe → detach A/B; unload on AB_OK.
# Scripts live under ~/sovereign-ln7 (Desktop TCC bypass).
#
#   bash scripts/ln7_install_gpu_capacity_watch.sh
#   bash scripts/ln7_install_gpu_capacity_watch.sh --uninstall
#   bash scripts/ln7_install_gpu_capacity_watch.sh --reset   # clear state + re-enable
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail
SRC_REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${LN7_SOVEREIGN_HOME:-$HOME/sovereign-ln7}"
LABEL="com.sovereign.ln7-gpu-capacity-watch"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
STATE_DIR="$HOME/.local/state/ln7_gpu_watch"
INTERVAL="${LN7_GPU_WATCH_INTERVAL_S:-900}"
UID_NUM="$(id -u)"
MIN_ROWS="${LN7_QLORA_MIN_ROWS:-50}"

uninstall() {
  launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "[gpu-watch] unloaded $LABEL"
}

if [[ "${1:-}" == "--uninstall" ]]; then
  uninstall
  exit 0
fi

if [[ "${1:-}" == "--reset" ]]; then
  rm -f "$STATE_DIR/AVAILABLE" "$STATE_DIR/AB_OK" "$STATE_DIR/AB_FAIL" \
        "$STATE_DIR/DRAINING" "$STATE_DIR/probe.env" "$STATE_DIR/ab_drain.pid" \
        "$STATE_DIR/run_ab_detached.sh" "$STATE_DIR/droplet_handoff.env" \
        "$STATE_DIR/AB_COMPARE" "$STATE_DIR/rev_a" "$STATE_DIR/rev_b" \
        "$STATE_DIR/doctl_auth_fails" "$STATE_DIR/doctl_auth_backoff_until" \
        "$STATE_DIR/WORKER_PAUSED" "$STATE_DIR/ttl_heartbeat" \
        "$STATE_DIR/watch.lock"
  rm -rf "$STATE_DIR/watch.lock.d"
  echo "[gpu-watch] cleared $STATE_DIR"
fi

mkdir -p "$DEST/scripts" "$DEST/data" "$DEST/backend/scripts" \
  "$HOME/Library/LaunchAgents" "$STATE_DIR" "$HOME/Library/Logs"

for f in ln7_gpu_capacity_watch.sh ln7_ab_qlora_drain.sh ln7_ab_bakeoff_compare.sh \
         ln7_continuous_drain.sh ln7_provision_cuda_droplet.sh ln7_destroy_cuda_droplet.sh; do
  if [[ -f "$SRC_REPO/scripts/$f" ]]; then
    cp "$SRC_REPO/scripts/$f" "$DEST/scripts/$f"
    chmod +x "$DEST/scripts/$f"
  fi
done
if [[ -f "$SRC_REPO/backend/scripts/ln7_qlora_train.py" ]]; then
  cp "$SRC_REPO/backend/scripts/ln7_qlora_train.py" "$DEST/backend/scripts/ln7_qlora_train.py"
  chmod +x "$DEST/backend/scripts/ln7_qlora_train.py"
fi
if [[ -f "$SRC_REPO/data/ln7_train.jsonl" ]]; then
  cp "$SRC_REPO/data/ln7_train.jsonl" "$DEST/data/ln7_train.jsonl"
fi

CLEAN_N="$(python3 - <<PY
import json,re
from pathlib import Path
stub=re.compile(r'^\[patch_hash=', re.I)
diff=re.compile(r'(?m)^(diff --git |--- |\+\+\+ |@@ )')
n=0
p=Path("$SRC_REPO/data/ln7_train.jsonl")
if p.is_file():
  for line in p.open():
    line=line.strip()
    if not line: continue
    r=json.loads(line)
    asst=""
    for m in r.get("messages") or []:
      if m.get("role")=="assistant": asst=m.get("content") or ""
    if asst and not stub.match(asst.strip()) and (diff.search(asst) or asst.count(chr(10)+'+')+asst.count(chr(10)+'-')>=2):
      n+=1
print(n)
PY
)"
# Only force-thin when set is thin; once ≥ min, leave unset (refuse thin forever).
FORCE_THIN_VAL=""
if [[ -n "${LN7_QLORA_FORCE_THIN:-}" ]]; then
  FORCE_THIN_VAL="$LN7_QLORA_FORCE_THIN"
elif [[ "${CLEAN_N:-0}" -lt "$MIN_ROWS" ]]; then
  FORCE_THIN_VAL="1"
fi
echo "[gpu-watch] clean_rows=$CLEAN_N min=$MIN_ROWS force_thin=${FORCE_THIN_VAL:-off}"

uninstall || true

# Build EnvironmentVariables dict (omit FORCE_THIN key when empty)
FORCE_THIN_XML=""
if [[ -n "$FORCE_THIN_VAL" ]]; then
  FORCE_THIN_XML="
    <key>LN7_QLORA_FORCE_THIN</key>
    <string>${FORCE_THIN_VAL}</string>"
fi

cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${DEST}/scripts/ln7_gpu_capacity_watch.sh</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>HOME</key>
    <string>${HOME}</string>
    <key>LN7_GPU_REGION</key>
    <string>${LN7_GPU_REGION:-tor1}</string>
    <key>LN7_GPU_SIZE</key>
    <string>${LN7_GPU_SIZE:-gpu-4000adax1-20gb}</string>
    <key>LN7_GPU_WATCH_AUTO_DRAIN</key>
    <string>${LN7_GPU_WATCH_AUTO_DRAIN:-1}</string>
    <key>LN7_GPU_WATCH_UNLOAD</key>
    <string>1</string>
    <key>LN7_QLORA_MIN_ROWS</key>
    <string>${MIN_ROWS}</string>
    <key>LN7_SRC_REPO</key>
    <string>${DEST}</string>${FORCE_THIN_XML}
  </dict>
  <key>WorkingDirectory</key>
  <string>${DEST}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>${INTERVAL}</integer>
  <key>StandardOutPath</key>
  <string>${HOME}/Library/Logs/ln7-gpu-capacity-watch.out.log</string>
  <key>StandardErrorPath</key>
  <string>${HOME}/Library/Logs/ln7-gpu-capacity-watch.err.log</string>
</dict>
</plist>
EOF

launchctl bootstrap "gui/${UID_NUM}" "$PLIST" 2>/dev/null \
  || launchctl load "$PLIST"

echo "[gpu-watch] installed $LABEL interval=${INTERVAL}s dest=$DEST"
echo "[gpu-watch] logs: ~/Library/Logs/ln7-gpu-capacity-watch*.log  ~/Library/Logs/ln7_ab_qlora_drain.log"
echo "[gpu-watch] success gate: $STATE_DIR/AB_OK  compare: $STATE_DIR/AB_COMPARE"
# RunAtLoad already fires — do not also one-shot (double-probe race).
# Manual: bash ~/sovereign-ln7/scripts/ln7_gpu_capacity_watch.sh
echo "[gpu-watch] RunAtLoad will probe; skip duplicate one-shot"
