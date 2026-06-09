#!/usr/bin/env bash
# Phase E on GREEN — sync script + run inside nate_backend (pending commit until pushed).
set -euo pipefail
HOST=root@68.183.168.75
REPO=/opt/clinical-sovereignty-lab
LOCAL="$(cd "$(dirname "$0")/.." && pwd)"

scp "$LOCAL/backend/scripts/phase_e_pilot5_enable.py" \
    "$LOCAL/backend/scripts/phase_e_pilot5_enable.sql" \
    "$HOST:$REPO/backend/scripts/"

ssh "$HOST" "cd $REPO && \
  docker compose -f docker-compose.prod.yml exec -T backend \
    python /app/scripts/phase_e_pilot5_enable.py --dry-run && \
  docker compose -f docker-compose.prod.yml exec -T backend \
    python /app/scripts/phase_e_pilot5_enable.py"
