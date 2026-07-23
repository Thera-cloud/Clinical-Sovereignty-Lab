#!/usr/bin/env bash
# Install/pin code-server on BLUE (Mac) for Sovereign IDE.
# Binds 127.0.0.1:8080 — public access only via Twin Engine → ide.sovereignsanctuary.net
set -euo pipefail

CODE_SERVER_VERSION="${CODE_SERVER_VERSION:-4.96.4}"
WORKSPACE="${WORKSPACE:-$HOME/Desktop/Clinical-Sovereignty-Lab-2}"
CONFIG_DIR="${HOME}/.config/code-server"
DATA_DIR="${HOME}/.local/share/code-server"

echo "==> Installing code-server ${CODE_SERVER_VERSION}"
if command -v brew >/dev/null 2>&1; then
  brew list code-server >/dev/null 2>&1 || brew install code-server
else
  curl -fsSL https://code-server.dev/install.sh | sh -s -- --version "${CODE_SERVER_VERSION}"
fi

mkdir -p "${CONFIG_DIR}" "${DATA_DIR}"
cat > "${CONFIG_DIR}/config.yaml" <<EOF
bind-addr: 127.0.0.1:8080
auth: none
cert: false
disable-telemetry: true
EOF

echo "==> Config written to ${CONFIG_DIR}/config.yaml"
echo "==> Start: code-server '${WORKSPACE}'"
echo "==> Tunnel: map ide.sovereignsanctuary.net → http://127.0.0.1:8080 (Twin Engine)"
echo "==> Auth: Cloudflare Access + Command gateway dashboard/ide.html (YubiKey)"
echo "==> Optional LaunchDaemon: scripts/blue/com.sovereign.code-server.plist"
