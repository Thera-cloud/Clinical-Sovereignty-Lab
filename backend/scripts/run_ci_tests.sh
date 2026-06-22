#!/usr/bin/env bash
# CI gate: unit/smoke tests that pass without Postgres/Redis/Stripe.
# Integration suites (DB, live WS, billing E2E) run manually on staging/GREEN.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export ENVIRONMENT="${ENVIRONMENT:-test}"
export DATABASE_URL="${DATABASE_URL:-}"
export REDIS_URL="${REDIS_URL:-}"
export PYTHONPATH="${PYTHONPATH:-${ROOT}/backend}"

exec python3 -m pytest "${ROOT}/backend/tests/" -v --tb=short \
  --ignore="${ROOT}/backend/tests/test_integration.py" \
  --ignore="${ROOT}/backend/tests/test_stripe_billing_flows.py" \
  --ignore="${ROOT}/backend/tests/test_hive_defense.py" \
  --ignore="${ROOT}/backend/tests/test_wisdom_mesh.py" \
  --ignore="${ROOT}/backend/tests/test_family_engine.py" \
  --ignore="${ROOT}/backend/tests/test_drip_scheduler.py" \
  --ignore="${ROOT}/backend/tests/test_ai_modes.py" \
  --ignore="${ROOT}/backend/tests/test_lived_wisdom.py" \
  --ignore="${ROOT}/backend/tests/test_coach_handoff_acceptance.py" \
  --ignore="${ROOT}/backend/tests/test_campaign_fibre.py" \
  --ignore="${ROOT}/backend/tests/test_family_linkage.py" \
  --ignore="${ROOT}/backend/tests/test_family_sanctuary_lifecycle_plan.py" \
  --ignore="${ROOT}/backend/tests/test_hardening_scenarios.py" \
  --ignore="${ROOT}/backend/tests/test_quakete/test_trail_emission.py" \
  --ignore="${ROOT}/backend/tests/test_zefcp" \
  "$@"
