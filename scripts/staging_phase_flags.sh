#!/usr/bin/env bash
# Flip agentic flags on staging_backend only (not production nate_backend).
# Usage: bash scripts/staging_phase_flags.sh phase0 on|off
#        bash scripts/staging_phase_flags.sh phase1 on|off

set -euo pipefail

cd /opt/clinical-sovereignty-lab

PHASE="${1:-}"
STATE="${2:-}"

if [ -z "$PHASE" ] || [ -z "$STATE" ]; then
  echo "Usage: $0 <phase0|phase1> <on|off>" >&2
  exit 1
fi

export STAGING_ENABLE_PROACTIVE_TOUCH_POLICY="${STAGING_ENABLE_PROACTIVE_TOUCH_POLICY:-false}"
export STAGING_ENABLE_PROACTIVE_COMMITMENTS="${STAGING_ENABLE_PROACTIVE_COMMITMENTS:-false}"
export STAGING_ENABLE_NATE_TOOL_EXECUTOR="${STAGING_ENABLE_NATE_TOOL_EXECUTOR:-false}"
export STAGING_ENABLE_THERAPEUTIC_PLANS="${STAGING_ENABLE_THERAPEUTIC_PLANS:-false}"
export STAGING_ENABLE_SELF_MONITOR_AGENT="${STAGING_ENABLE_SELF_MONITOR_AGENT:-false}"
export STAGING_ENABLE_SELF_MONITOR_COACH_ALERT="${STAGING_ENABLE_SELF_MONITOR_COACH_ALERT:-false}"
export STAGING_ENABLE_SELF_MONITOR_TOUCH="${STAGING_ENABLE_SELF_MONITOR_TOUCH:-false}"
export STAGING_ENABLE_SYMBOLIC_EXTRACTION="${STAGING_ENABLE_SYMBOLIC_EXTRACTION:-false}"
export STAGING_ENABLE_SYMBOLIC_VERIFIER="${STAGING_ENABLE_SYMBOLIC_VERIFIER:-false}"
export STAGING_ENABLE_FORWARD_REASONING="${STAGING_ENABLE_FORWARD_REASONING:-false}"

_val() {
  if [ "$STATE" = "on" ]; then echo "true"; else echo "false"; fi
}

case "$PHASE" in
  phase0)
    export STAGING_ENABLE_PROACTIVE_TOUCH_POLICY="$(_val)"
    ;;
  phase1)
    if [ "$STATE" = "on" ]; then
      export STAGING_ENABLE_PROACTIVE_TOUCH_POLICY=true
    fi
    export STAGING_ENABLE_PROACTIVE_COMMITMENTS="$(_val)"
    ;;
  *)
    echo "Unknown phase: $PHASE" >&2
    exit 1
    ;;
esac

echo "[staging_flags] ${PHASE} ${STATE} — recreating staging_backend"
docker compose -f docker-compose.prod.yml -f docker-compose.staging.yml up -d staging_backend

sleep 12
docker exec nate_staging_backend printenv ENABLE_PROACTIVE_TOUCH_POLICY ENABLE_PROACTIVE_COMMITMENTS 2>/dev/null || true
curl -sf http://127.0.0.1:8001/health
echo ""
echo "[staging_flags] OK"
