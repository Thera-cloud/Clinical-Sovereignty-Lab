#!/usr/bin/env bash
# ORANGE LiveKit bootstrap — WireGuard API + documented UDP media.
# Does NOT buy Twilio DIDs. Does NOT open Ollama :11434.
# QUANTUM-CRYSTAL-ARCH
#
# Run from GREEN (or BLUE via ProxyJump) ONLY after operator confirm:
#   ssh -J root@68.183.168.75 root@10.13.13.5 'bash -s' < scripts/orange/livekit_bootstrap.sh
#
# Default is dry-run. Pass APPLY=1 to write systemd unit + ufw rules.

set -euo pipefail

APPLY="${APPLY:-0}"
LK_VERSION="${LK_VERSION:-1.8.4}"
WG_IP="${WG_IP:-10.13.13.5}"
API_PORT="${API_PORT:-7880}"
RTC_PORT="${RTC_PORT:-7881}"
UDP_START="${UDP_START:-50000}"
UDP_END="${UDP_END:-60000}"
INSTALL_DIR="${INSTALL_DIR:-/opt/sovereign/livekit}"
KEY_FILE="${KEY_FILE:-/etc/sovereign/livekit.env}"

echo "LiveKit bootstrap target ${WG_IP}:${API_PORT} APPLY=${APPLY}"
echo "Ollama public :11434 stays closed. SIP uses TLS + Twilio allowlist after keys exist."

if [[ "${APPLY}" != "1" ]]; then
  echo "Dry-run only. Re-run with APPLY=1 on ORANGE to install."
  exit 0
fi

if [[ "$(hostname -I 2>/dev/null || true)" != *"${WG_IP}"* ]]; then
  echo "Refusing: this host does not own ${WG_IP}. Run on ORANGE." >&2
  exit 2
fi

mkdir -p "${INSTALL_DIR}" /etc/sovereign
if [[ ! -f "${KEY_FILE}" ]]; then
  umask 077
  API_KEY="lk_$(openssl rand -hex 8)"
  API_SECRET="$(openssl rand -hex 24)"
  cat > "${KEY_FILE}" <<EOF
LIVEKIT_API_KEY=${API_KEY}
LIVEKIT_API_SECRET=${API_SECRET}
LIVEKIT_BIND=${WG_IP}
LIVEKIT_PORT=${API_PORT}
EOF
  chmod 600 "${KEY_FILE}"
  echo "Wrote ${KEY_FILE} — copy KEY/SECRET to GREEN .env as LIVEKIT_API_KEY/SECRET"
  echo "Set GREEN LIVEKIT_URL=wss://api.sovereignsanctuary.net/livekit"
  echo "Set GREEN LIVEKIT_INTERNAL_URL=http://${WG_IP}:${API_PORT}"
fi

# shellcheck disable=SC1090
source "${KEY_FILE}"

ARCH="$(uname -m)"
case "${ARCH}" in
  aarch64|arm64) LK_ARCH="linux_arm64" ;;
  x86_64|amd64) LK_ARCH="linux_amd64" ;;
  *) echo "Unsupported arch ${ARCH}" >&2; exit 3 ;;
esac

BIN="${INSTALL_DIR}/livekit-server"
if [[ ! -x "${BIN}" ]]; then
  curl -fsSL "https://github.com/livekit/livekit/releases/download/v${LK_VERSION}/livekit_${LK_VERSION}_${LK_ARCH}.tar.gz" \
    | tar -xz -C "${INSTALL_DIR}" livekit-server
  chmod 755 "${BIN}"
fi

CFG="${INSTALL_DIR}/livekit.yaml"
cat > "${CFG}" <<EOF
port: ${API_PORT}
bind_addresses:
  - ${WG_IP}
rtc:
  tcp_port: ${RTC_PORT}
  port_range_start: ${UDP_START}
  port_range_end: ${UDP_END}
  use_external_ip: true
keys:
  ${LIVEKIT_API_KEY}: ${LIVEKIT_API_SECRET}
logging:
  level: info
EOF

cat > /etc/systemd/system/livekit-server.service <<EOF
[Unit]
Description=Sovereign Studio LiveKit
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=${KEY_FILE}
ExecStart=${BIN} --config ${CFG}
Restart=on-failure
RestartSec=3
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

if command -v ufw >/dev/null 2>&1; then
  ufw allow from 10.13.13.0/24 to any port "${API_PORT}" proto tcp
  ufw allow "${RTC_PORT}/tcp"
  ufw allow "${UDP_START}:${UDP_END}/udp"
  ufw deny 11434/tcp || true
fi

systemctl daemon-reload
systemctl enable --now livekit-server
systemctl --no-pager --full status livekit-server | head -20
echo "Health from GREEN: curl -s http://${WG_IP}:${API_PORT}/  (WG only)"
echo "Public health stays https://api.sovereignsanctuary.net/api/studio/livekit/health"
