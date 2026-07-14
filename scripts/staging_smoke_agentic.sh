#!/usr/bin/env bash
# Smoke tests for staging agentic bake (run on GREEN).
# Usage: bash scripts/staging_smoke_agentic.sh [phase0|phase1]

set -euo pipefail

cd /opt/clinical-sovereignty-lab
PHASE="${1:-phase0}"

echo "[staging_smoke] health (retry up to 60s)"
for i in $(seq 1 20); do
  if curl -sf http://127.0.0.1:8011/health >/dev/null 2>&1; then
    break
  fi
  sleep 3
done
curl -sf http://127.0.0.1:8011/health

echo "[staging_smoke] seam tests (offline, in staging container)"
docker compose -f docker-compose.prod.yml -f docker-compose.staging.yml exec -T staging_backend \
  python -m pytest tests/test_proactive_touch_seams.py tests/test_touch_adaptation_asymmetry.py -q --tb=no

if [ "$PHASE" = "phase1" ]; then
  docker exec nate_postgres psql -U nate_admin -d little_nate_staging -tAc \
    "SELECT COUNT(*) FROM nate_commitments;"
  docker compose -f docker-compose.prod.yml -f docker-compose.staging.yml exec -T staging_backend \
    python -c "from app.services.nate_commitment_agent import NateCommitmentAgent; print('commitment_agent_import_ok')"
fi

docker exec nate_staging_backend printenv ENVIRONMENT ENABLE_PROACTIVE_TOUCH_POLICY ENABLE_PROACTIVE_COMMITMENTS 2>/dev/null
echo "[staging_smoke] OK"
