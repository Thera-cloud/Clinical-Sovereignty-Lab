#!/usr/bin/env bash
# Install BLUE LaunchAgent: bakeoff compare heartbeat watchdog.
#
#   bash scripts/ln7_install_ab_compare_watchdog.sh
#   bash scripts/ln7_install_ab_compare_watchdog.sh --uninstall
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail
SRC_REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${LN7_SOVEREIGN_HOME:-$HOME/sovereign-ln7}"
LABEL="com.sovereign.ln7-ab-compare-watchdog"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
STATE_DIR="$HOME/.local/state/ln7_gpu_watch"
INTERVAL="${LN7_COMPARE_WATCHDOG_INTERVAL_S:-300}"
UID_NUM="$(id -u)"

uninstall() {
  launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "[ab-watchdog] unloaded $LABEL"
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

for f in ln7_ab_compare_watchdog.sh ln7_ab_bakeoff_compare.sh \
         ln7_deploy_peft_serve_orange.sh ln7_continuous_worker.sh; do
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
    <string>${DEST}/scripts/ln7_ab_compare_watchdog.sh</string>
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
  <string>${HOME}/Library/Logs/ln7_ab_compare_watchdog.out.log</string>
  <key>StandardErrorPath</key>
  <string>${HOME}/Library/Logs/ln7_ab_compare_watchdog.err.log</string>
</dict>
</plist>
EOF

launchctl bootstrap "gui/${UID_NUM}" "$PLIST" 2>/dev/null \
  || launchctl load "$PLIST"
echo "[ab-watchdog] installed $LABEL interval=${INTERVAL}s dest=$DEST"
echo "[ab-watchdog] stale=${LN7_COMPARE_HEARTBEAT_STALE_S:-900}s max_restarts=${LN7_COMPARE_WATCHDOG_MAX_RESTARTS:-2}"
launchctl print "gui/${UID_NUM}/${LABEL}" 2>/dev/null | head -8 || true
