#!/bin/bash
# =============================================================================
# CASTLE DEFENSE — WireGuard Mesh Setup
# Layer 1: Sets up WireGuard VPN mesh between MacBook, Production, and Mirror VPS
#
# Usage:
#   ./scripts/setup_wireguard_mesh.sh generate-keys
#   ./scripts/setup_wireguard_mesh.sh install-macbook
#   ./scripts/setup_wireguard_mesh.sh install-production
#   ./scripts/setup_wireguard_mesh.sh install-mirror
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
WG_DIR="$PROJECT_DIR/wireguard"

case "$1" in
    generate-keys)
        echo "=== Generating WireGuard key pairs ==="
        echo ""

        for node in macbook production mirror-vps; do
            echo "--- $node ---"
            mkdir -p "$WG_DIR/$node"
            wg genkey | tee "$WG_DIR/$node/privatekey" | wg pubkey > "$WG_DIR/$node/publickey"
            echo "  Private key: $(cat "$WG_DIR/$node/privatekey")"
            echo "  Public key:  $(cat "$WG_DIR/$node/publickey")"
            chmod 600 "$WG_DIR/$node/privatekey"
            echo ""
        done

        echo "=== Keys generated. Now update wg0.conf files with these keys. ==="
        echo ""
        echo "Replace in macbook/wg0.conf:"
        echo "  <MACBOOK_PRIVATE_KEY>     = $(cat "$WG_DIR/macbook/privatekey")"
        echo "  <PRODUCTION_PUBLIC_KEY>    = $(cat "$WG_DIR/production/publickey")"
        echo "  <MIRROR_PUBLIC_KEY>        = $(cat "$WG_DIR/mirror-vps/publickey")"
        echo ""
        echo "Replace in production/wg0.conf:"
        echo "  <PRODUCTION_PRIVATE_KEY>   = $(cat "$WG_DIR/production/privatekey")"
        echo "  <MACBOOK_PUBLIC_KEY>        = $(cat "$WG_DIR/macbook/publickey")"
        echo "  <MIRROR_PUBLIC_KEY>        = $(cat "$WG_DIR/mirror-vps/publickey")"
        echo ""
        echo "Replace in mirror-vps/wg0.conf:"
        echo "  <MIRROR_PRIVATE_KEY>       = $(cat "$WG_DIR/mirror-vps/privatekey")"
        echo "  <MACBOOK_PUBLIC_KEY>        = $(cat "$WG_DIR/macbook/publickey")"
        echo "  <PRODUCTION_PUBLIC_KEY>    = $(cat "$WG_DIR/production/publickey")"
        ;;

    install-macbook)
        echo "=== Installing WireGuard on MacBook ==="
        brew install wireguard-tools 2>/dev/null || echo "wireguard-tools already installed"
        sudo cp "$WG_DIR/macbook/wg0.conf" /etc/wireguard/wg0.conf
        sudo chmod 600 /etc/wireguard/wg0.conf
        echo "Start with: sudo wg-quick up wg0"
        echo "Auto-start: sudo launchctl load /Library/LaunchDaemons/com.wireguard.wg0.plist"
        ;;

    install-production)
        echo "=== Installing WireGuard on Production Server ==="
        echo "Run on 68.183.168.75:"
        echo "  apt install -y wireguard"
        echo "  cp wireguard/production/wg0.conf /etc/wireguard/wg0.conf"
        echo "  chmod 600 /etc/wireguard/wg0.conf"
        echo "  systemctl enable wg-quick@wg0"
        echo "  systemctl start wg-quick@wg0"
        echo ""
        echo "Then lock down SSH to VPN only:"
        echo "  echo 'ListenAddress 10.13.13.2' >> /etc/ssh/sshd_config"
        echo "  systemctl restart sshd"
        ;;

    install-mirror)
        echo "=== Installing WireGuard on Mirror VPS ==="
        echo "Run on Mirror VPS:"
        echo "  apt install -y wireguard"
        echo "  sysctl -w net.ipv4.ip_forward=1"
        echo "  echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf"
        echo "  cp wireguard/mirror-vps/wg0.conf /etc/wireguard/wg0.conf"
        echo "  chmod 600 /etc/wireguard/wg0.conf"
        echo "  systemctl enable wg-quick@wg0"
        echo "  systemctl start wg-quick@wg0"
        ;;

    status)
        echo "=== WireGuard Status ==="
        sudo wg show 2>/dev/null || echo "WireGuard not running on this machine"
        ;;

    *)
        echo "Usage: $0 {generate-keys|install-macbook|install-production|install-mirror|status}"
        exit 1
        ;;
esac
