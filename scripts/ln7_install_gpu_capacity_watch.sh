#!/usr/bin/env bash
# Install BLUE LaunchAgent: poll DO GPU capacity; self-stop + optional A/B drain on hit.
# Scripts live under ~/sovereign-ln7 (Desktop TCC bypass — same as continuous worker).
#
#   bash scripts/ln7_install_gpu_capacity_watch.sh
#   bash scripts/ln7_install_gpu_capacity_watch.sh --uninstall
#   bash scripts/ln7_install_gpu_capacity_watch.sh --reset   # clear AVAILABLE + re-enable
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
  rm -f "$STATE_DIR/AVAILABLE" "$STATE_DIR/ab_drain.pid"
  echo "[gpu-watch] cleared $STATE_DIR"
fi

mkdir -p "$DEST/scripts" "$DEST/data" "$HOME/Library/LaunchAgents" "$STATE_DIR" "$HOME/Library/Logs"

for f in ln7_gpu_capacity_watch.sh ln7_ab_qlora_drain.sh ln7_continuous_drain.sh \
         ln7_provision_cuda_droplet.sh ln7_destroy_cuda_droplet.sh; do
  if [[ -f "$SRC_REPO/scripts/$f" ]]; then
    cp "$SRC_REPO/scripts/$f" "$DEST/scripts/$f"
    chmod +x "$DEST/scripts/$f"
  fi
done

uninstall || true

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
    <key>LN7_QLORA_FORCE_THIN</key>
    <string>${LN7_QLORA_FORCE_THIN:-1}</string>
    <key>LN7_QLORA_MIN_ROWS</key>
    <string>${LN7_QLORA_MIN_ROWS:-50}</string>
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
echo "[gpu-watch] logs: ~/Library/Logs/ln7-gpu-capacity-watch*.log"
echo "[gpu-watch] state: $STATE_DIR/AVAILABLE (created on hit)"
echo "[gpu-watch] one-shot now:"
bash "$DEST/scripts/ln7_gpu_capacity_watch.sh" || true
