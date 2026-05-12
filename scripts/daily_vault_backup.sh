#!/usr/bin/env bash
set -euo pipefail
ts=$(date -u +%Y%m%d_%H%M%S)
cd /opt/clinical-sovereignty-lab
mkdir -p backups/vaults
tar -czf backups/vaults/vault_backup_${ts}.tar.gz data/bridge/Vaults data/backend/Vaults 2>/dev/null
# Retain 30 days
find backups/vaults -name 'vault_backup_*.tar.gz' -mtime +30 -delete
# Heartbeat for monitoring
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) OK" > backups/vaults/.last_backup_heartbeat
