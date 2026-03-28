#!/bin/bash
# install.sh — Install or upgrade the nate-mac-agent LaunchAgent.
# Handles both fresh install AND upgrade (unload, copy, reload).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_LABEL="net.sovereignsanctuary.nate-mac-agent"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

echo "=== nate-mac-agent installer ==="
echo "Script dir: $SCRIPT_DIR"
echo "Plist target: $PLIST_PATH"

# Upgrade path: unload if already installed
if launchctl list 2>/dev/null | grep -q "$PLIST_LABEL"; then
    echo "Upgrading: unloading existing agent..."
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    sleep 2
fi

# Ensure LaunchAgents directory exists
mkdir -p "$HOME/Library/LaunchAgents"

# Install/overwrite plist
cp "$SCRIPT_DIR/nate-mac-agent.plist" "$PLIST_PATH"
chmod 644 "$PLIST_PATH"
echo "Plist installed at $PLIST_PATH"

# Install/upgrade dependencies
echo "Installing Python dependencies..."
pip3 install -r "$SCRIPT_DIR/requirements.txt" --upgrade --quiet

# Ensure data directory exists
mkdir -p "$SCRIPT_DIR/../../data"

# Load (start)
launchctl load "$PLIST_PATH"
echo ""
echo "Agent loaded. Verify with:"
echo "  launchctl list | grep $PLIST_LABEL"
echo "  curl http://localhost:9900/health"
echo ""
echo "To uninstall:"
echo "  launchctl unload $PLIST_PATH"
echo "  rm $PLIST_PATH"
