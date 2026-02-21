#!/bin/bash
# =============================================================================
# CASTLE DEFENSE — Sandbox VPS Deployment
# Layer 6: Provisions the isolated detonation sandbox on a dedicated VPS.
#
# Target: 178.128.178.15 (WireGuard 10.13.13.4)
# OS: Ubuntu 22.04+ / Debian 12+
#
# PREREQUISITES:
#   1. SSH access to 178.128.178.15 as root
#   2. WireGuard config ready at wireguard/sandbox-vps/wg0.conf
#
# USAGE (from your local machine):
#   # 1. Copy WireGuard config to the VPS
#   scp wireguard/sandbox-vps/wg0.conf root@178.128.178.15:/root/wg0.conf
#
#   # 2. Copy this script
#   scp scripts/setup_sandbox_vps.sh root@178.128.178.15:/root/setup_sandbox_vps.sh
#
#   # 3. Copy sandbox code files
#   scp backend/app/services/security/sandbox_api.py root@178.128.178.15:/root/sandbox_api.py
#   scp backend/app/services/security/detonation_chamber.py root@178.128.178.15:/root/detonation_chamber.py
#   scp backend/app/services/security/phishing_link_hunter.py root@178.128.178.15:/root/phishing_link_hunter.py
#   scp backend/app/services/security/phishing_detector.py root@178.128.178.15:/root/phishing_detector.py
#
#   # 4. SSH in and run
#   ssh root@178.128.178.15 "bash /root/setup_sandbox_vps.sh"
#
#   # 5. Verify from production server
#   ssh root@68.183.168.75 "curl -s http://10.13.13.4:9090/health"
# =============================================================================

set -euo pipefail

SANDBOX_DIR="/opt/sandbox"
WG_CONF="/etc/wireguard/wg0.conf"
BIND_IP="10.13.13.4"
BIND_PORT="9090"

echo "============================================"
echo "  Castle Defense — Sandbox VPS Deployment"
echo "  Layer 6: Detonation Chamber"
echo "============================================"
echo ""

# ─── PHASE 1: SYSTEM PACKAGES ───────────────────────────────────────────────

echo "[1/7] Installing system packages..."

apt-get update
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    wget \
    libmagic1 \
    tesseract-ocr \
    fonts-unifont \
    iproute2 \
    iptables \
    wireguard \
    ufw

echo "[1/7] System packages installed."

# ─── PHASE 2: PYTHON ENVIRONMENT ────────────────────────────────────────────

echo "[2/7] Setting up Python virtual environment..."

mkdir -p "$SANDBOX_DIR"
python3 -m venv "$SANDBOX_DIR/venv"
source "$SANDBOX_DIR/venv/bin/activate"

pip install --no-cache-dir \
    fastapi~=0.115.0 \
    "uvicorn[standard]~=0.27.0" \
    aiohttp~=3.9.1 \
    playwright~=1.49.0 \
    pytesseract~=0.3.13 \
    Pillow~=10.4.0 \
    python-magic~=0.4.27 \
    python-whois~=0.9.4 \
    dnspython~=2.4.0

echo "[2/7] Python packages installed."

# ─── PHASE 3: PLAYWRIGHT + CHROMIUM ─────────────────────────────────────────

echo "[3/7] Installing Playwright Chromium..."

playwright install chromium
playwright install-deps chromium

echo "[3/7] Playwright + Chromium installed."

# ─── PHASE 4: DEPLOY SANDBOX CODE ───────────────────────────────────────────

echo "[4/7] Deploying sandbox code..."

for f in sandbox_api.py detonation_chamber.py phishing_link_hunter.py phishing_detector.py; do
    if [ -f "/root/$f" ]; then
        cp "/root/$f" "$SANDBOX_DIR/$f"
        echo "  Deployed $f"
    else
        echo "  WARNING: /root/$f not found — copy it to the VPS first"
    fi
done

mkdir -p /tmp/screenshots
chown -R root:root "$SANDBOX_DIR"

echo "[4/7] Sandbox code deployed to $SANDBOX_DIR."

# ─── PHASE 5: WIREGUARD ─────────────────────────────────────────────────────

echo "[5/7] Configuring WireGuard..."

if [ -f "/root/wg0.conf" ]; then
    cp /root/wg0.conf "$WG_CONF"
    chmod 600 "$WG_CONF"

    systemctl enable wg-quick@wg0
    systemctl restart wg-quick@wg0

    sleep 2
    if ip addr show wg0 &>/dev/null; then
        echo "  WireGuard interface wg0 is UP"
        echo "  Local VPN IP: $(ip -4 addr show wg0 | grep -oP 'inet \K[\d.]+')"
    else
        echo "  WARNING: wg0 did not come up — check /root/wg0.conf"
    fi
else
    echo "  WARNING: /root/wg0.conf not found"
    echo "  Copy it with: scp wireguard/sandbox-vps/wg0.conf root@178.128.178.15:/root/wg0.conf"
fi

echo "[5/7] WireGuard configured."

# ─── PHASE 6: FIREWALL + IPTABLES ───────────────────────────────────────────

echo "[6/7] Configuring firewall and iptables..."

# UFW: allow SSH + WireGuard inbound, deny everything else
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "SSH"
ufw allow 51820/udp comment "WireGuard"
ufw --force enable

# iptables: sandbox API only listens on WireGuard interface
# Block access to sandbox port from the public internet
iptables -A INPUT -i wg0 -p tcp --dport "$BIND_PORT" -j ACCEPT
iptables -A INPUT -p tcp --dport "$BIND_PORT" -j DROP

# Save iptables rules so they persist across reboots
mkdir -p /etc/iptables
iptables-save > /etc/iptables/rules.v4

echo "[6/7] Firewall configured (SSH + WireGuard inbound; sandbox API only via WireGuard)."

# ─── PHASE 7: SYSTEMD SERVICE ───────────────────────────────────────────────

echo "[7/7] Creating systemd service..."

cat > /etc/systemd/system/sandbox-api.service << 'UNIT'
[Unit]
Description=Little Nate Detonation Sandbox API (Layer 6)
After=network.target wg-quick@wg0.service
Wants=wg-quick@wg0.service

[Service]
Type=exec
WorkingDirectory=/opt/sandbox
ExecStart=/opt/sandbox/venv/bin/python3 -m uvicorn sandbox_api:app --host 10.13.13.4 --port 9090
Restart=always
RestartSec=5
Environment=SANDBOX_MODE=true

# Resource limits
LimitNOFILE=4096
LimitNPROC=512

# Security hardening
ProtectSystem=strict
ReadWritePaths=/opt/sandbox /tmp/screenshots /tmp
PrivateTmp=true
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable sandbox-api.service
systemctl restart sandbox-api.service

sleep 3
if systemctl is-active --quiet sandbox-api.service; then
    echo "  sandbox-api.service is RUNNING"
else
    echo "  WARNING: sandbox-api.service failed to start"
    echo "  Check logs: journalctl -u sandbox-api -n 30 --no-pager"
fi

echo "[7/7] Systemd service created and started."

# ─── SUMMARY ────────────────────────────────────────────────────────────────

echo ""
echo "============================================"
echo "  Sandbox VPS Deployment Complete"
echo "============================================"
echo ""
echo "  VPS Public IP:  178.128.178.15"
echo "  WireGuard IP:   $BIND_IP"
echo "  Sandbox API:    http://$BIND_IP:$BIND_PORT"
echo "  Sandbox Dir:    $SANDBOX_DIR"
echo ""
echo "  Next steps:"
echo "    1. Verify WireGuard: ping 10.13.13.2 (production)"
echo "    2. From production:  curl http://$BIND_IP:$BIND_PORT/health"
echo "    3. Update production SANDBOX_URL to http://$BIND_IP:$BIND_PORT"
echo ""
echo "  To update sandbox code later:"
echo "    scp <file> root@178.128.178.15:/opt/sandbox/<file>"
echo "    ssh root@178.128.178.15 systemctl restart sandbox-api"
echo ""
