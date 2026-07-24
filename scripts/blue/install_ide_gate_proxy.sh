#!/usr/bin/env bash
# Cut over BLUE: code-server :8082, ide-gate proxy :8080 (Twin Engine already → 8080).
set -euo pipefail

REPO="${REPO:-$HOME/Desktop/Clinical-Sovereignty-Lab-2}"
PROXY="$REPO/scripts/blue/ide_gate_proxy.py"
ENV_DIR="$HOME/.config/sovereign-ide"
ENV_FILE="$ENV_DIR/env"
PLIST="$HOME/Library/LaunchAgents/com.sovereignsanctuary.ide-gate.plist"
CS_CFG="$HOME/.config/code-server/config.yaml"
GREEN="${GREEN_HOST:-root@68.183.168.75}"

mkdir -p "$ENV_DIR"
chmod 700 "$ENV_DIR"

if [[ ! -s "$ENV_FILE" ]] || ! grep -q '^IDE_GATE_SECRET=' "$ENV_FILE" 2>/dev/null; then
  echo "[ide-gate] syncing IDE_GATE_SECRET from GREEN (value not printed)…"
  ssh "$GREEN" 'grep "^IDE_GATE_SECRET=" /opt/clinical-sovereignty-lab/.env | head -1' >"$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

if ! grep -q '^IDE_GATE_SECRET=.\+' "$ENV_FILE"; then
  echo "[ide-gate] ERROR: IDE_GATE_SECRET missing in $ENV_FILE" >&2
  exit 1
fi
echo "[ide-gate] secret file ok ($(wc -c <"$ENV_FILE") bytes)"

# Move code-server off 8080
if [[ -f "$CS_CFG" ]]; then
  if grep -q 'bind-addr: 127.0.0.1:8080' "$CS_CFG"; then
    sed -i.bak 's/bind-addr: 127.0.0.1:8080/bind-addr: 127.0.0.1:8082/' "$CS_CFG"
    echo "[ide-gate] code-server config → 127.0.0.1:8082"
  fi
fi

cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.sovereignsanctuary.ide-gate</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$PROXY</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>IDE_PROXY_PORT</key>
    <string>8080</string>
    <key>IDE_UPSTREAM</key>
    <string>http://127.0.0.1:8082</string>
  </dict>
  <key>EnvironmentFiles</key>
  <array>
    <string>$ENV_FILE</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$HOME/Library/Logs/sovereign-ide-gate.log</string>
  <key>StandardErrorPath</key>
  <string>$HOME/Library/Logs/sovereign-ide-gate.log</string>
  <key>WorkingDirectory</key>
  <string>$REPO</string>
</dict>
</plist>
EOF

# launchd EnvironmentFiles needs macOS 13+; also export via wrapper for safety
# Copy proxy out of Desktop (LaunchAgent TCC cannot read Desktop/)
cp "$PROXY" "$ENV_DIR/ide_gate_proxy.py"
chmod 700 "$ENV_DIR/ide_gate_proxy.py"

WRAPPER="$ENV_DIR/run.sh"
cat >"$WRAPPER" <<'WRAP'
#!/usr/bin/env bash
set -euo pipefail
ENV_FILE="${HOME}/.config/sovereign-ide/env"
# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a
export IDE_PROXY_PORT="${IDE_PROXY_PORT:-8080}"
export IDE_UPSTREAM="${IDE_UPSTREAM:-http://127.0.0.1:8082}"
exec /usr/bin/python3 "${HOME}/.config/sovereign-ide/ide_gate_proxy.py"
WRAP
chmod 700 "$WRAPPER"

# Prefer wrapper (reliable secret load)
cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.sovereignsanctuary.ide-gate</string>
  <key>ProgramArguments</key>
  <array>
    <string>$WRAPPER</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$HOME/Library/Logs/sovereign-ide-gate.log</string>
  <key>StandardErrorPath</key>
  <string>$HOME/Library/Logs/sovereign-ide-gate.log</string>
</dict>
</plist>
EOF

echo "[ide-gate] restarting code-server on :8082…"
launchctl bootout "gui/$(id -u)/homebrew.mxcl.code-server" 2>/dev/null || true
launchctl unload "$HOME/Library/LaunchAgents/homebrew.mxcl.code-server.plist" 2>/dev/null || true
sleep 1
launchctl load "$HOME/Library/LaunchAgents/homebrew.mxcl.code-server.plist" 2>/dev/null || \
  brew services restart code-server 2>/dev/null || \
  /usr/local/opt/code-server/bin/code-server >/dev/null 2>&1 &

sleep 2
if ! lsof -nP -iTCP:8082 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[ide-gate] WARN: nothing on 8082 yet — starting code-server manually"
  /usr/local/opt/code-server/bin/code-server >/tmp/code-server-ide.log 2>&1 &
  sleep 2
fi

echo "[ide-gate] loading proxy LaunchAgent…"
launchctl bootout "gui/$(id -u)/com.sovereignsanctuary.ide-gate" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load -w "$PLIST"
sleep 1

echo "[ide-gate] listeners:"
lsof -nP -iTCP:8080,8082 -sTCP:LISTEN 2>/dev/null || true

echo "[ide-gate] local probe (no cookie → expect 401):"
curl -s -o /dev/null -w "http=%{http_code}\n" http://127.0.0.1:8080/ || true
curl -s http://127.0.0.1:8080/__ide_gate_health || true
echo
echo "[ide-gate] done. Public ide.* still needs CF bot pass; origin now requires YubiKey cookie."
