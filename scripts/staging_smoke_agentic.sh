#!/usr/bin/env bash
# Smoke tests for staging agentic bake (run on GREEN).
# Usage: bash scripts/staging_smoke_agentic.sh [phase0|phase1|phase2|phase3|phase4]

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
echo ""

echo "[staging_smoke] phase0 seam tests (offline, in staging container)"
docker compose -f docker-compose.prod.yml -f docker-compose.staging.yml exec -T staging_backend \
  python -m pytest tests/test_proactive_touch_seams.py tests/test_touch_adaptation_asymmetry.py -q --tb=no

if [ "$PHASE" = "phase1" ] || [ "$PHASE" = "phase2" ] || [ "$PHASE" = "phase3" ] || [ "$PHASE" = "phase4" ]; then
  echo "[staging_smoke] phase1: commitments table + agent import"
  docker exec nate_postgres psql -U nate_admin -d little_nate_staging -tAc \
    "SELECT COUNT(*) FROM nate_commitments;"
  docker compose -f docker-compose.prod.yml -f docker-compose.staging.yml exec -T staging_backend \
    python -c "from app.services.nate_commitment_agent import NateCommitmentAgent, publish_commitment_touch_fanout; print('commitment_agent_import_ok')"
fi

if [ "$PHASE" = "phase2" ] || [ "$PHASE" = "phase3" ] || [ "$PHASE" = "phase4" ]; then
  echo "[staging_smoke] phase2: tool executor seams + booking persist"
  docker compose -f docker-compose.prod.yml -f docker-compose.staging.yml exec -T staging_backend \
    python -m pytest tests/test_nate_tool_executor_seams.py tests/test_session_booking_persist.py -q --tb=no
  docker exec nate_staging_bridge printenv ENABLE_NATE_TOOL_EXECUTOR 2>/dev/null || true
fi

if [ "$PHASE" = "phase3" ] || [ "$PHASE" = "phase4" ]; then
  echo "[staging_smoke] phase3: therapeutic plans table + divergence seams"
  docker exec nate_postgres psql -U nate_admin -d little_nate_staging -tAc \
    "SELECT COUNT(*) FROM nate_therapeutic_plans;"
  docker compose -f docker-compose.prod.yml -f docker-compose.staging.yml exec -T staging_backend \
    python -m pytest tests/test_therapeutic_plan_divergence.py -q --tb=no
  docker compose -f docker-compose.prod.yml -f docker-compose.staging.yml exec -T staging_backend \
    python -c "from app.services.nate_therapeutic_plan_service import schedule_plan_divergence_check; print('plan_divergence_import_ok')"
fi

if [ "$PHASE" = "phase4" ]; then
  echo "[staging_smoke] phase4: self-monitor import + flags (TOUCH must stay false)"
  docker compose -f docker-compose.prod.yml -f docker-compose.staging.yml exec -T staging_backend \
    python -c "from app.services.nate_self_monitor_agent import NateSelfMonitorAgent; print('self_monitor_import_ok')"
  TOUCH=$(docker exec nate_staging_backend printenv ENABLE_SELF_MONITOR_TOUCH 2>/dev/null || echo "")
  if [ "${TOUCH}" = "true" ]; then
    echo "[staging_smoke] FAIL: ENABLE_SELF_MONITOR_TOUCH must be false on staging smoke" >&2
    exit 1
  fi
fi

docker exec nate_staging_backend printenv \
  ENVIRONMENT ENABLE_PROACTIVE_TOUCH_POLICY ENABLE_PROACTIVE_COMMITMENTS \
  ENABLE_NATE_TOOL_EXECUTOR ENABLE_THERAPEUTIC_PLANS \
  ENABLE_SELF_MONITOR_AGENT ENABLE_SELF_MONITOR_COACH_ALERT ENABLE_SELF_MONITOR_TOUCH \
  2>/dev/null || true
echo "[staging_smoke] OK (${PHASE})"
