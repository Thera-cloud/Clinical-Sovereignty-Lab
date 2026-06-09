#!/usr/bin/env bash
# Sync outdated client/coach consent (no enrollment impact). Run from Mac repo root.
set -euo pipefail
HOST="${GREEN_HOST:-root@68.183.168.75}"
REPO="${GREEN_REPO:-/opt/clinical-sovereignty-lab}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

scp "$ROOT/backend/scripts/consent_outdated_resync.py" \
  "$HOST:$REPO/backend/scripts/"

ssh "$HOST" "cd $REPO && \
  docker compose -f docker-compose.prod.yml exec -T backend \
    python /app/scripts/consent_outdated_resync.py --dry-run && \
  docker compose -f docker-compose.prod.yml exec -T backend \
    python /app/scripts/consent_outdated_resync.py && \
  bash scripts/safe_deploy.sh bridge"
