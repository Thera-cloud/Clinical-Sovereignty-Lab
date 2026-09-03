#!/usr/bin/env bash
# ORANGE LiveKit Egress + Redis + webhook. Room-composite MP4 → R2.
# Does NOT open Ollama :11434. Default is dry-run.
# QUANTUM-CRYSTAL-ARCH
#
#   ssh -J root@68.183.168.75 root@10.13.13.5 'bash -s' < scripts/orange/livekit_egress_bootstrap.sh
#   APPLY=1 ...
set -euo pipefail

APPLY="${APPLY:-0}"
WG_IP="${WG_IP:-10.13.13.5}"
KEY_FILE="${KEY_FILE:-/etc/sovereign/livekit.env}"
INSTALL_DIR="${INSTALL_DIR:-/opt/sovereign/livekit}"
CFG="${INSTALL_DIR}/livekit.yaml"
EGRESS_CFG="${INSTALL_DIR}/egress.yaml"
WEBHOOK_URL="${WEBHOOK_URL:-https://api.sovereignsanctuary.net/api/studio/livekit/events}"

echo "LiveKit egress bootstrap ${WG_IP} APPLY=${APPLY}"

if [[ "${APPLY}" != "1" ]]; then
  echo "Dry-run only. Re-run with APPLY=1 on ORANGE to install redis + egress."
  exit 0
fi

if [[ "$(hostname -I 2>/dev/null || true)" != *"${WG_IP}"* ]]; then
  echo "Refusing: this host does not own ${WG_IP}. Run on ORANGE." >&2
  exit 2
fi

if [[ ! -f "${KEY_FILE}" ]]; then
  echo "Missing ${KEY_FILE}. Run livekit_bootstrap.sh first." >&2
  exit 3
fi

# shellcheck disable=SC1090
source "${KEY_FILE}"
export LIVEKIT_API_KEY LIVEKIT_API_SECRET
export WEBHOOK_URL LK_CFG="${CFG}"
if [[ -z "${LIVEKIT_API_KEY:-}" || -z "${LIVEKIT_API_SECRET:-}" ]]; then
  echo "LIVEKIT_API_KEY/SECRET missing in ${KEY_FILE}" >&2
  exit 4
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq redis-server docker.io ca-certificates curl

mkdir -p /etc/redis
if [[ -f /etc/redis/redis.conf ]]; then
  sed -i 's/^bind .*/bind 127.0.0.1 -::1/' /etc/redis/redis.conf
  sed -i 's/^#\?supervised .*/supervised systemd/' /etc/redis/redis.conf
fi
systemctl enable --now redis-server
redis-cli ping | grep -q PONG

# Egress container runs as non-root; 0600 on the host bind-mount is EPERM.
OUT_DIR="${INSTALL_DIR}/out"
mkdir -p "${OUT_DIR}"
cat > "${OUT_DIR}/config.yaml" <<EOF
log_level: info
api_key: ${LIVEKIT_API_KEY}
api_secret: ${LIVEKIT_API_SECRET}
ws_url: ws://${WG_IP}:7880
insecure: true
redis:
  address: 127.0.0.1:6379
EOF
chmod 755 "${OUT_DIR}"
chmod 644 "${OUT_DIR}/config.yaml"
cp "${OUT_DIR}/config.yaml" "${EGRESS_CFG}"
chmod 600 "${EGRESS_CFG}"

python3 - <<'PY'
import os
from pathlib import Path
cfg = Path(os.environ.get("LK_CFG", "/opt/sovereign/livekit/livekit.yaml"))
key = os.environ["LIVEKIT_API_KEY"]
url = os.environ.get("WEBHOOK_URL", "https://api.sovereignsanctuary.net/api/studio/livekit/events")
text = cfg.read_text() if cfg.is_file() else ""
if "redis:" not in text:
    text += "\nredis:\n  address: 127.0.0.1:6379\n"
if "webhook:" not in text:
    text += f"\nwebhook:\n  api_key: {key}\n  urls:\n    - {url}\n"
cfg.write_text(text)
print("livekit.yaml redis+webhook present")
PY

systemctl enable --now docker
# Docker sets FORWARD DROP; keep WireGuard host traffic working.
iptables -C DOCKER-USER -i wg0 -j ACCEPT 2>/dev/null || iptables -I DOCKER-USER -i wg0 -j ACCEPT
iptables -C DOCKER-USER -o wg0 -j ACCEPT 2>/dev/null || iptables -I DOCKER-USER -o wg0 -j ACCEPT
cat > /etc/systemd/system/docker-wg-accept.service <<'UNIT'
[Unit]
Description=Accept WireGuard in DOCKER-USER
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'iptables -C DOCKER-USER -i wg0 -j ACCEPT 2>/dev/null || iptables -I DOCKER-USER -i wg0 -j ACCEPT; iptables -C DOCKER-USER -o wg0 -j ACCEPT 2>/dev/null || iptables -I DOCKER-USER -o wg0 -j ACCEPT'

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now docker-wg-accept
systemctl restart livekit-server
sleep 2
systemctl --no-pager --full status livekit-server | head -12

docker pull --platform linux/arm64 livekit/egress:latest
cat > /etc/systemd/system/livekit-egress.service <<EOF
[Unit]
Description=Sovereign Studio LiveKit Egress
After=docker.service redis-server.service livekit-server.service
Requires=docker.service redis-server.service

[Service]
Type=simple
Restart=on-failure
RestartSec=5
ExecStartPre=-/usr/bin/docker rm -f livekit-egress
ExecStart=/usr/bin/docker run --name livekit-egress --rm --network host --cap-add SYS_ADMIN --shm-size=2g \
  -e EGRESS_CONFIG_FILE=/out/config.yaml \
  -v ${OUT_DIR}:/out:ro \
  livekit/egress:latest
ExecStop=/usr/bin/docker stop -t 15 livekit-egress

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now livekit-egress
sleep 3
systemctl --no-pager --full status livekit-egress | head -16
echo "Egress up. Public health: https://api.sovereignsanctuary.net/api/studio/livekit/health"
