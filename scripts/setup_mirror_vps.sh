#!/bin/bash
# =============================================================================
# CASTLE DEFENSE — Mirror VPS Deployment
# Layer 7: Deploys the House of Mirrors on the sacrificial VPN exit node.
#
# TWO PHASES (for safety):
#   Phase 1 (default): Installs WireGuard, firewall, honeypot on non-SSH ports.
#                      Keeps SSH on port 22 via public IP so you don't get locked out.
#   Phase 2 (lockdown): Moves SSH to port 2222 over WireGuard only,
#                        enables port 22 honeypot. Run ONLY after confirming
#                        WireGuard mesh works (ping 10.13.13.2 from this VPS).
#
# Usage:
#   scp wireguard/mirror-vps/wg0.conf root@165.227.19.117:/root/wg0.conf
#   scp scripts/setup_mirror_vps.sh root@165.227.19.117:/root/setup_mirror_vps.sh
#   ssh root@165.227.19.117 "bash /root/setup_mirror_vps.sh"
#
# After WireGuard mesh confirmed:
#   ssh root@165.227.19.117 "bash /root/setup_mirror_vps.sh lockdown"
# =============================================================================

set -euo pipefail

MIRROR_IP="$(curl -s4 ifconfig.me 2>/dev/null || echo 'unknown')"
LOG_DIR="/var/log/mirror_gateway"
MIRROR_DIR="/opt/mirror_gateway"

# ─── PHASE 2: LOCKDOWN ──────────────────────────────────────────────────────
if [ "${1:-}" = "lockdown" ]; then
    echo "============================================"
    echo "  Phase 2: SSH Lockdown + Port 22 Honeypot"
    echo "============================================"

    # Verify WireGuard is up and production is reachable
    if ! ping -c 2 -W 3 10.13.13.2 &>/dev/null; then
        echo "ERROR: Cannot reach production (10.13.13.2) over WireGuard."
        echo "Fix the WG mesh first. Do NOT lock down SSH without a working tunnel."
        exit 1
    fi
    echo "[OK] Production reachable over WireGuard (10.13.13.2)"

    # Move SSH to port 2222, WireGuard interface only
    if ! grep -q "^Port 2222" /etc/ssh/sshd_config; then
        # Remove default Port 22 if present
        sed -i 's/^#\?Port 22$//' /etc/ssh/sshd_config
        echo "" >> /etc/ssh/sshd_config
        echo "Port 2222" >> /etc/ssh/sshd_config
        echo "ListenAddress 10.13.13.3" >> /etc/ssh/sshd_config
    fi

    # Allow port 2222 from WG mesh
    ufw allow from 10.13.13.0/24 to any port 2222 proto tcp comment "Real SSH (WG only)" 2>/dev/null || true

    # Override the systemd socket (Ubuntu 24.04 uses socket-activated SSH)
    mkdir -p /etc/systemd/system/ssh.socket.d
    cat > /etc/systemd/system/ssh.socket.d/override.conf <<'SOCKET_OVERRIDE'
[Socket]
ListenStream=
ListenStream=10.13.13.3:2222
SOCKET_OVERRIDE
    systemctl daemon-reload
    systemctl restart ssh.socket
    systemctl restart ssh.service 2>/dev/null || true
    echo "[OK] SSH moved to port 2222 on 10.13.13.3"

    # Stop any existing honeypot, update it to include port 22, restart
    systemctl stop mirror-honeypot 2>/dev/null || true
    # Add port 22 to the honeypot config
    if [ -f "$MIRROR_DIR/honeypot.py" ]; then
        sed -i 's/SKIP_PORTS = {22}/SKIP_PORTS = set()/' "$MIRROR_DIR/honeypot.py" 2>/dev/null || true
    fi
    systemctl start mirror-honeypot

    echo ""
    echo "============================================"
    echo "  Lockdown complete!"
    echo "  SSH from now on: ssh -p 2222 root@10.13.13.3"
    echo "  Port 22 is now a honeypot."
    echo "============================================"
    exit 0
fi

# ─── PHASE 1: SAFE SETUP ────────────────────────────────────────────────────

echo "============================================"
echo "  Castle Defense — Mirror VPS Deployment"
echo "  Phase 1: Safe Setup (SSH stays on port 22)"
echo "  Public IP: $MIRROR_IP"
echo "============================================"
echo ""

# ── 1. System updates ──
echo "[1/7] Updating system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq wireguard python3 ufw fail2ban jq

# ── 2. WireGuard setup ──
echo "[2/7] Configuring WireGuard..."
WG_CONF="/root/wg0.conf"
if [ ! -f "$WG_CONF" ]; then
    echo "ERROR: $WG_CONF not found."
    echo "Upload with: scp wireguard/mirror-vps/wg0.conf root@$MIRROR_IP:/root/wg0.conf"
    exit 1
fi

cp "$WG_CONF" /etc/wireguard/wg0.conf
chmod 600 /etc/wireguard/wg0.conf

# Enable IP forwarding
sysctl -w net.ipv4.ip_forward=1
grep -q "net.ipv4.ip_forward=1" /etc/sysctl.conf || echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf

systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0 || systemctl restart wg-quick@wg0

echo "  WireGuard interface:"
wg show wg0 2>/dev/null | head -8 || echo "  (wg0 started — peers will connect once their side is configured)"

# ── 3. Firewall ──
echo "[3/7] Configuring firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "SSH (kept until lockdown)"
ufw allow 51820/udp comment "WireGuard"
ufw allow from 10.13.13.0/24 comment "WireGuard mesh"

# Honeypot ports (port 22 excluded — SSH is still there)
for port in 80 443 3306 5432 6379 8080; do
    ufw allow "$port"/tcp comment "Honeypot $port"
done

echo "y" | ufw enable
ufw status numbered

# ── 4. Logging ──
echo "[4/7] Setting up logging..."
mkdir -p "$LOG_DIR"
chmod 700 "$LOG_DIR"

cat > /etc/logrotate.d/mirror_gateway <<'LOGROTATE'
/var/log/mirror_gateway/*.log /var/log/mirror_gateway/*.jsonl {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
}
LOGROTATE

# ── 5. Deploy honeypot ──
echo "[5/7] Deploying honeypot service..."
mkdir -p "$MIRROR_DIR"

cat > "$MIRROR_DIR/honeypot.py" <<'HONEYPOT_PY'
"""
Mirror VPS Honeypot Service
Listens on common ports and presents fake banners.
Logs all connection attempts and tarpits attackers.
"""
import asyncio
import json
import logging
import os
import socket
import time
from datetime import datetime, timezone

LOG_DIR = "/var/log/mirror_gateway"
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(f"{LOG_DIR}/honeypot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("honeypot")

SERVICES = {
    22:   {"name": "ssh",        "banner": "SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.4\r\n"},
    80:   {"name": "http",       "banner": "HTTP/1.1 200 OK\r\nServer: Apache/2.4.54 (Ubuntu)\r\nContent-Type: text/html\r\n\r\n<html><head><title>Welcome</title></head><body><h1>It works!</h1></body></html>"},
    443:  {"name": "https",      "banner": "HTTP/1.1 400 Bad Request\r\nServer: nginx/1.22.1\r\n\r\n"},
    3306: {"name": "mysql",      "banner": "5.7.40-0ubuntu0.18.04.1"},
    5432: {"name": "postgresql", "banner": "PostgreSQL 15.4 on x86_64"},
    6379: {"name": "redis",      "banner": "-ERR max number of clients reached\r\n"},
    8080: {"name": "http-alt",   "banner": "HTTP/1.1 403 Forbidden\r\nServer: Jetty/9.4.51.v20230217\r\n\r\n"},
}

# Skip port 22 until lockdown phase moves SSH away
SKIP_PORTS = {22}

TARPIT_DELAY = 5.0
TARPIT_DRIP_BYTES = 16
TARPIT_DURATION = 120

async def handle_client(reader, writer, port, service_info):
    addr = writer.get_extra_info("peername")
    source_ip = addr[0] if addr else "unknown"
    logger.info("PROBE port=%d src=%s service=%s", port, source_ip, service_info["name"])

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_ip": source_ip,
        "port": port,
        "service": service_info["name"],
        "data_received": "",
    }

    try:
        writer.write(service_info["banner"].encode())
        await writer.drain()

        try:
            data = await asyncio.wait_for(reader.read(4096), timeout=10)
            record["data_received"] = data.decode("utf-8", errors="replace")[:1024]
        except (asyncio.TimeoutError, ConnectionError):
            pass

        # Tarpit: slowly drip data to waste attacker time
        noise = b"x" * TARPIT_DRIP_BYTES
        start = time.time()
        while time.time() - start < TARPIT_DURATION:
            try:
                writer.write(noise)
                await writer.drain()
                await asyncio.sleep(TARPIT_DELAY)
            except (ConnectionError, BrokenPipeError):
                break

    except Exception as e:
        record["error"] = str(e)
    finally:
        record["duration_sec"] = round(time.time() - time.mktime(
            datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")).timetuple()
        ), 1)
        with open(f"{LOG_DIR}/probes.jsonl", "a") as f:
            f.write(json.dumps(record) + "\n")

        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

async def start_honeypot(port, service_info):
    try:
        server = await asyncio.start_server(
            lambda r, w: handle_client(r, w, port, service_info),
            "0.0.0.0",
            port,
            reuse_address=True,
        )
        logger.info("Honeypot listening on :%d (%s)", port, service_info["name"])
        async with server:
            await server.serve_forever()
    except OSError as e:
        logger.error("Cannot bind port %d: %s", port, e)

async def main():
    logger.info("=== Mirror Gateway Honeypot starting (skip_ports=%s) ===", SKIP_PORTS)
    tasks = []
    for port, info in SERVICES.items():
        if port in SKIP_PORTS:
            logger.info("Skipping port %d (SSH still active)", port)
            continue
        tasks.append(start_honeypot(port, info))
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
HONEYPOT_PY

# ── 6. Systemd service ──
echo "[6/7] Creating systemd service..."
cat > /etc/systemd/system/mirror-honeypot.service <<SERVICE
[Unit]
Description=Castle Defense Mirror Gateway Honeypot
After=network.target wg-quick@wg0.service
Wants=wg-quick@wg0.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 $MIRROR_DIR/honeypot.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable mirror-honeypot
systemctl start mirror-honeypot

# ── 7. Verification ──
echo "[7/7] Verifying deployment..."
echo ""
echo "  WireGuard status:"
wg show wg0 2>/dev/null | head -10 || echo "    (waiting for peers)"
echo ""
echo "  Honeypot service:"
systemctl is-active mirror-honeypot && echo "    RUNNING" || echo "    NOT RUNNING — check: journalctl -u mirror-honeypot"
echo ""
echo "  Firewall:"
ufw status | head -20
echo ""

echo "============================================"
echo "  Phase 1 complete! SSH is still on port 22."
echo ""
echo "  Next steps:"
echo "    1. Set up WireGuard on production (68.183.168.75)"
echo "    2. Test: ping 10.13.13.2 from this VPS"
echo "    3. Once mesh works: bash /root/setup_mirror_vps.sh lockdown"
echo ""
echo "  Honeypot active on: 80, 443, 3306, 5432, 6379, 8080"
echo "  Logs: $LOG_DIR/probes.jsonl"
echo "============================================"
