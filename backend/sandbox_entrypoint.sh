#!/bin/bash
# =============================================================================
# DETONATION SANDBOX ENTRYPOINT
# Layer 6: Configures network isolation and starts the sandbox API.
#
# - Routes all traffic through WireGuard gateway (if available)
# - Blocks connections to RFC 1918 private ranges
# - Sets ulimits for process/memory safety
# =============================================================================

set -e

echo "[SANDBOX] Configuring network isolation..."

# Block connections to internal/private networks (prevent lateral movement)
if command -v iptables &> /dev/null; then
    # Block RFC 1918 private ranges
    iptables -A OUTPUT -d 10.0.0.0/8 -j DROP 2>/dev/null || true
    iptables -A OUTPUT -d 172.16.0.0/12 -j DROP 2>/dev/null || true
    iptables -A OUTPUT -d 192.168.0.0/16 -j DROP 2>/dev/null || true

    # Allow WireGuard gateway (if configured)
    if [ -n "$WIREGUARD_GATEWAY" ]; then
        iptables -I OUTPUT -d "$WIREGUARD_GATEWAY" -j ACCEPT 2>/dev/null || true
        echo "[SANDBOX] WireGuard gateway: $WIREGUARD_GATEWAY"
    fi

    # Allow DNS
    iptables -I OUTPUT -p udp --dport 53 -j ACCEPT 2>/dev/null || true
    iptables -I OUTPUT -p tcp --dport 53 -j ACCEPT 2>/dev/null || true

    # Allow localhost
    iptables -I OUTPUT -d 127.0.0.0/8 -j ACCEPT 2>/dev/null || true

    # Allow hunt_command network (internal Docker API bridge to backend)
    iptables -I OUTPUT -d 172.30.0.0/24 -j ACCEPT 2>/dev/null || true

    echo "[SANDBOX] RFC 1918 blocked, DNS + hunt_command allowed"
else
    echo "[SANDBOX] iptables not available, skipping network isolation"
fi

# Route through WireGuard if gateway is set
if [ -n "$WIREGUARD_GATEWAY" ]; then
    ip route del default 2>/dev/null || true
    ip route add default via "$WIREGUARD_GATEWAY" 2>/dev/null || true
    echo "[SANDBOX] Default route set to WireGuard: $WIREGUARD_GATEWAY"
fi

# Set resource limits
ulimit -n 1024 2>/dev/null || true    # Max open files
ulimit -u 256 2>/dev/null || true     # Max processes
ulimit -v 1048576 2>/dev/null || true # Max virtual memory (1GB)

echo "[SANDBOX] Resource limits configured"
echo "[SANDBOX] Starting sandbox API on :9090..."

# Start the sandbox API
exec python3 -m uvicorn sandbox_api:app --host 0.0.0.0 --port 9090
