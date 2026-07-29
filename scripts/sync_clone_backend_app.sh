#!/usr/bin/env bash
# QUANTUM-CRYSTAL-ARCH — Sync backend/app from GREEN primary → clone REST node.
# Clone has no git; LB REST can 404 until this runs after backend/app changes.
set -euo pipefail

PRIMARY="${PRIMARY_HOST:-68.183.168.75}"
CLONE="${CLONE_HOST:-159.65.108.25}"
REMOTE_ROOT="${REMOTE_ROOT:-/opt/clinical-sovereignty-lab}"

echo "[sync_clone] ${PRIMARY} → ${CLONE} (${REMOTE_ROOT}/backend/app)"
ssh "root@${PRIMARY}" \
  "cd '${REMOTE_ROOT}' && tar czf - --exclude='__pycache__' --exclude='*.pyc' backend/app" \
  | ssh "root@${CLONE}" \
  "cd '${REMOTE_ROOT}' && tar xzf - && docker restart nate_backend"

echo "[sync_clone] waiting for health…"
sleep 25
ssh "root@${CLONE}" 'curl -sf --max-time 8 http://127.0.0.1:8000/health && echo && docker logs nate_backend --since 60s 2>&1 | grep -E "STARTUP COMPLETE|NOMINAL|DEGRADED" | tail -3'
echo "[sync_clone] done"
