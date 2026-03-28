#!/bin/bash
# ──────────────────────────────────────────────────────────────
# Crystal Factory Installer
#
# Usage:
#   On Hetzner:       ./install-crystal-factory.sh hetzner
#   On DigitalOcean:  ./install-crystal-factory.sh digitalocean
#
# Prerequisites:
#   - Python 3.10+ installed
#   - PostgreSQL reachable from this server
#   - WireGuard tunnel active (Hetzner → DigitalOcean)
# ──────────────────────────────────────────────────────────────

set -euo pipefail

ROLE="${1:-}"
INSTALL_DIR="/opt/crystal-factory"

if [[ "$ROLE" != "hetzner" && "$ROLE" != "digitalocean" ]]; then
    echo "Usage: $0 <hetzner|digitalocean>"
    exit 1
fi

echo "╔══════════════════════════════════════════════╗"
echo "║   Crystal Factory Installer — $ROLE"
echo "╚══════════════════════════════════════════════╝"

# ── 1. Create install directory ──
echo "[1/6] Creating $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

# ── 2. Copy factory script ──
echo "[2/6] Copying crystal_factory.py..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$SCRIPT_DIR/../crystal_factory.py" "$INSTALL_DIR/crystal_factory.py"

# ── 3. Create virtualenv + install dependencies ──
echo "[3/6] Setting up Python virtualenv..."
if [[ ! -d "$INSTALL_DIR/venv" ]]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet asyncpg aiohttp

# ── 4. Copy .env template + secure permissions ──
echo "[4/6] Setting up .env..."
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    cp "$SCRIPT_DIR/../.env.crystal-${ROLE}" "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    chown root:root "$INSTALL_DIR/.env"
    echo "  ⚠  EDIT $INSTALL_DIR/.env — set PRODUCTION_DB_URL password + GROK_API_KEY"
else
    echo "  .env already exists, skipping (won't overwrite)"
    chmod 600 "$INSTALL_DIR/.env"
    chown root:root "$INSTALL_DIR/.env"
fi

# ── 5. Install systemd service ──
echo "[5/6] Installing systemd service..."
cp "$SCRIPT_DIR/crystal-factory-${ROLE}.service" \
   /etc/systemd/system/crystal-factory.service
systemctl daemon-reload

# ── 6. Connectivity pre-check ──
echo "[6/6] Checking connectivity..."

DB_URL=$(grep PRODUCTION_DB_URL "$INSTALL_DIR/.env" | cut -d= -f2-)
if [[ "$DB_URL" == *"CHANGE_ME"* ]]; then
    echo ""
    echo "  ┌─────────────────────────────────────────────┐"
    echo "  │  ⚠  Database password not set!              │"
    echo "  │                                             │"
    echo "  │  Edit $INSTALL_DIR/.env and replace         │"
    echo "  │  CHANGE_ME with the actual password.        │"
    echo "  │                                             │"
    echo "  │  Then run:                                  │"
    echo "  │    systemctl enable crystal-factory          │"
    echo "  │    systemctl start crystal-factory           │"
    echo "  │    journalctl -u crystal-factory -f          │"
    echo "  └─────────────────────────────────────────────┘"
    exit 0
fi

echo ""
echo "  Testing PostgreSQL connectivity..."
if "$INSTALL_DIR/venv/bin/python3" -c "
import asyncio, asyncpg, os
async def test():
    pool = await asyncpg.create_pool('$DB_URL', min_size=1, max_size=1)
    row = await pool.fetchval('SELECT COUNT(*) FROM nate_intelligence_crystals')
    print(f'  ✅ Connected — {row} existing crystals')
    await pool.close()
asyncio.run(test())
" 2>/dev/null; then
    echo ""
    echo "  Starting Crystal Factory..."
    systemctl enable crystal-factory
    systemctl start crystal-factory
    echo ""
    echo "  ╔══════════════════════════════════════════════╗"
    echo "  ║   Crystal Factory ONLINE                     ║"
    echo "  ║                                              ║"
    echo "  ║   Monitor: journalctl -u crystal-factory -f  ║"
    echo "  ║   Status:  systemctl status crystal-factory  ║"
    echo "  ║   Stop:    systemctl stop crystal-factory    ║"
    echo "  ╚══════════════════════════════════════════════╝"
else
    echo ""
    echo "  ⚠  PostgreSQL connection failed."
    echo "  Check .env and WireGuard connectivity."
    echo "  Once fixed: systemctl start crystal-factory"
fi
