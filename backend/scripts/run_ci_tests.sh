#!/usr/bin/env bash
# CI gate: unit/smoke tests that pass without Postgres/Redis/Stripe.
# Integration suites (DB, live WS, billing E2E) run manually on staging/GREEN.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export ENVIRONMENT="${ENVIRONMENT:-test}"
export DATABASE_URL="${DATABASE_URL:-}"
export REDIS_URL="${REDIS_URL:-}"
export PYTHONPATH="${PYTHONPATH:-${ROOT}/backend}"

# QUANTUM-CRYSTAL-ARCH — Sovereign Standard CI decorator / docstring gate
# Load gate via file path (not app.services package) to avoid nevedal/numpy
# Accelerate SIGFPE on some macOS hosts during package __init__ import.
python3 -c "
from pathlib import Path
import importlib.util
import sys
root = Path(r'''${ROOT}/backend''')
gate_path = root / 'app' / 'services' / 'sovereign_standard_gate.py'
spec = importlib.util.spec_from_file_location('sovereign_standard_gate', gate_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
if not mod.ci_gate_pass(root):
    print('SOVEREIGN STANDARD GATE FAILED — therapeutic modules missing governance markers')
    sys.exit(1)
print('Sovereign Standard gate: PASS')
"

# QUANTUM-CRYSTAL-ARCH — Principal-Review gold learning gate (offline harness)
python3 "${ROOT}/backend/scripts/verify_gold_learning_gate.py" --offline

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
