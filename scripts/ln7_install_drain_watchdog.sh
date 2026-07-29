#!/usr/bin/env bash
# Install BLUE LaunchAgent: drain/train + orphan reaper watchdog.
#
#   bash scripts/ln7_install_drain_watchdog.sh
#   bash scripts/ln7_install_drain_watchdog.sh --uninstall
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail
SRC_REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${LN7_SOVEREIGN_HOME:-$HOME/sovereign-ln7}"
LABEL="com.sovereign.ln7-drain-watchdog"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
STATE_DIR="$HOME/.local/state/ln7_gpu_watch"
INTERVAL="${LN7_DRAIN_WATCHDOG_INTERVAL_S:-300}"
UID_NUM="$(id -u)"

uninstall() {
  launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "[drain-watchdog] unloaded $LABEL"
}

if [[ "${1:-}" == "--uninstall" ]]; then
  uninstall
  exit 0
fi

mkdir -p "$DEST/scripts" "$HOME/Library/LaunchAgents" "$STATE_DIR" "$HOME/Library/Logs"

_safe_cp() {
  local src="$1" dst="$2"
  [[ -f "$src" ]] || return 0
  [[ "$(cd "$(dirname "$src")" && pwd)/$(basename "$src")" == \
     "$(cd "$(dirname "$dst")" 2>/dev/null && pwd)/$(basename "$dst")" ]] && return 0
  cp -f "$src" "$dst" 2>/dev/null || true
  chmod +x "$dst" 2>/dev/null || true
}

for f in ln7_drain_watchdog.sh ln7_gpu_orphan_reaper.sh ln7_destroy_cuda_droplet.sh \
         ln7_continuous_drain.sh ln7_ab_qlora_drain.sh; do
  _safe_cp "$SRC_REPO/scripts/$f" "$DEST/scripts/$f"
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
    <string>${DEST}/scripts/ln7_drain_watchdog.sh</string>
  </array>
  <key>StartInterval</key>
  <integer>${INTERVAL}</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>WorkingDirectory</key>
  <string>${DEST}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>LN7_SOVEREIGN_HOME</key>
    <string>${DEST}</string>
    <key>LN7_GPU_WATCH_STATE_DIR</key>
    <string>${STATE_DIR}</string>
    <key>PATH</key>
    <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StandardOutPath</key>
  <string>${HOME}/Library/Logs/ln7_drain_watchdog.out.log</string>
  <key>StandardErrorPath</key>
  <string>${HOME}/Library/Logs/ln7_drain_watchdog.err.log</string>
</dict>
</plist>
EOF

launchctl bootstrap "gui/${UID_NUM}" "$PLIST" 2>/dev/null \
  || launchctl load "$PLIST"
echo "[drain-watchdog] installed $LABEL interval=${INTERVAL}s dest=$DEST"
echo "[drain-watchdog] stale=${LN7_DRAIN_HEARTBEAT_STALE_S:-1800}s orphan_ttl=${LN7_ORPHAN_TTL_S:-7200}s"
launchctl print "gui/${UID_NUM}/${LABEL}" 2>/dev/null | head -8 || true
