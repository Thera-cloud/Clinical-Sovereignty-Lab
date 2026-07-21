#!/usr/bin/env bash
# Flip agentic flags on staging_backend/bridge only (not production nate_*).
# Usage: bash scripts/staging_phase_flags.sh phase0|phase1|phase2|phase3|phase4|phase5a|phase5b|n3 on|off
#
# Preserves other STAGING_ENABLE_* values from .env so one phase flip does not
# clobber siblings (e.g. phase3 must not reset session negotiation).

set -euo pipefail

cd /opt/clinical-sovereignty-lab

PHASE="${1:-}"
STATE="${2:-}"

if [ -z "$PHASE" ] || [ -z "$STATE" ]; then
  echo "Usage: $0 <phase0|phase1|phase2|phase3|phase4|phase5a|phase5b|n3> <on|off>" >&2
  exit 1
fi

# Load existing STAGING_* from .env without clobbering already-exported vars
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  # Only pull STAGING_ENABLE_* lines
  eval "$(grep -E '^STAGING_ENABLE_[A-Z0-9_]+=' .env | sed 's/\r$//' || true)"
  set +a
fi

_env_or() {
  # $1=var name  $2=default
  local cur="${!1:-}"
  if [ -n "$cur" ]; then echo "$cur"; else echo "$2"; fi
}

export STAGING_ENABLE_PROACTIVE_TOUCH_POLICY="$(_env_or STAGING_ENABLE_PROACTIVE_TOUCH_POLICY false)"
export STAGING_ENABLE_PROACTIVE_COMMITMENTS="$(_env_or STAGING_ENABLE_PROACTIVE_COMMITMENTS false)"
export STAGING_ENABLE_NATE_TOOL_EXECUTOR="$(_env_or STAGING_ENABLE_NATE_TOOL_EXECUTOR false)"
export STAGING_ENABLE_THERAPEUTIC_PLANS="$(_env_or STAGING_ENABLE_THERAPEUTIC_PLANS false)"
export STAGING_ENABLE_NATE_SESSION_NEGOTIATION="$(_env_or STAGING_ENABLE_NATE_SESSION_NEGOTIATION false)"
export STAGING_ENABLE_SELF_MONITOR_AGENT="$(_env_or STAGING_ENABLE_SELF_MONITOR_AGENT false)"
export STAGING_ENABLE_SELF_MONITOR_COACH_ALERT="$(_env_or STAGING_ENABLE_SELF_MONITOR_COACH_ALERT false)"
export STAGING_ENABLE_SELF_MONITOR_TOUCH="$(_env_or STAGING_ENABLE_SELF_MONITOR_TOUCH false)"
export STAGING_ENABLE_SYMBOLIC_EXTRACTION="$(_env_or STAGING_ENABLE_SYMBOLIC_EXTRACTION false)"
export STAGING_ENABLE_SYMBOLIC_VERIFIER="$(_env_or STAGING_ENABLE_SYMBOLIC_VERIFIER false)"
export STAGING_ENABLE_FORWARD_REASONING="$(_env_or STAGING_ENABLE_FORWARD_REASONING false)"

_val() {
  if [ "$STATE" = "on" ]; then echo "true"; else echo "false"; fi
}

_persist() {
  # Write flipped key back to .env so next run preserves it
  local key="$1" val="$2"
  if grep -q "^${key}=" .env 2>/dev/null; then
    sed -i "s/^${key}=.*/${key}=${val}/" .env
  else
    echo "${key}=${val}" >> .env
  fi
}

case "$PHASE" in
  phase0)
    export STAGING_ENABLE_PROACTIVE_TOUCH_POLICY="$(_val)"
    _persist STAGING_ENABLE_PROACTIVE_TOUCH_POLICY "$STAGING_ENABLE_PROACTIVE_TOUCH_POLICY"
    ;;
  phase1)
    if [ "$STATE" = "on" ]; then
      export STAGING_ENABLE_PROACTIVE_TOUCH_POLICY=true
      _persist STAGING_ENABLE_PROACTIVE_TOUCH_POLICY true
    fi
    export STAGING_ENABLE_PROACTIVE_COMMITMENTS="$(_val)"
    _persist STAGING_ENABLE_PROACTIVE_COMMITMENTS "$STAGING_ENABLE_PROACTIVE_COMMITMENTS"
    ;;
  phase2)
    if [ "$STATE" = "on" ]; then
      export STAGING_ENABLE_PROACTIVE_TOUCH_POLICY=true
      export STAGING_ENABLE_PROACTIVE_COMMITMENTS=true
      _persist STAGING_ENABLE_PROACTIVE_TOUCH_POLICY true
      _persist STAGING_ENABLE_PROACTIVE_COMMITMENTS true
    fi
    export STAGING_ENABLE_NATE_TOOL_EXECUTOR="$(_val)"
    _persist STAGING_ENABLE_NATE_TOOL_EXECUTOR "$STAGING_ENABLE_NATE_TOOL_EXECUTOR"
    ;;
  phase3)
    export STAGING_ENABLE_THERAPEUTIC_PLANS="$(_val)"
    _persist STAGING_ENABLE_THERAPEUTIC_PLANS "$STAGING_ENABLE_THERAPEUTIC_PLANS"
    ;;
  n3)
    export STAGING_ENABLE_NATE_SESSION_NEGOTIATION="$(_val)"
    _persist STAGING_ENABLE_NATE_SESSION_NEGOTIATION "$STAGING_ENABLE_NATE_SESSION_NEGOTIATION"
    ;;
  phase4)
    # Coach-alert path only — never flip TOUCH via this phase helper
    export STAGING_ENABLE_SELF_MONITOR_TOUCH=false
    export STAGING_ENABLE_SELF_MONITOR_AGENT="$(_val)"
    export STAGING_ENABLE_SELF_MONITOR_COACH_ALERT="$(_val)"
    _persist STAGING_ENABLE_SELF_MONITOR_TOUCH false
    _persist STAGING_ENABLE_SELF_MONITOR_AGENT "$STAGING_ENABLE_SELF_MONITOR_AGENT"
    _persist STAGING_ENABLE_SELF_MONITOR_COACH_ALERT "$STAGING_ENABLE_SELF_MONITOR_COACH_ALERT"
    ;;
  phase5a)
    # Track C — symbolic extraction only (never verifier/forward/graph via this helper)
    if [ "$STATE" = "on" ]; then
      export STAGING_ENABLE_PROACTIVE_TOUCH_POLICY=true
      export STAGING_ENABLE_PROACTIVE_COMMITMENTS=true
      _persist STAGING_ENABLE_PROACTIVE_TOUCH_POLICY true
      _persist STAGING_ENABLE_PROACTIVE_COMMITMENTS true
    fi
    export STAGING_ENABLE_SYMBOLIC_EXTRACTION="$(_val)"
    export STAGING_ENABLE_SYMBOLIC_VERIFIER=false
    export STAGING_ENABLE_FORWARD_REASONING=false
    _persist STAGING_ENABLE_SYMBOLIC_EXTRACTION "$STAGING_ENABLE_SYMBOLIC_EXTRACTION"
    _persist STAGING_ENABLE_SYMBOLIC_VERIFIER false
    _persist STAGING_ENABLE_FORWARD_REASONING false
    ;;
  phase5b)
    # Track C — symbolic verifier (requires extraction on; never forward/graph via this helper)
    if [ "$STATE" = "on" ]; then
      export STAGING_ENABLE_PROACTIVE_TOUCH_POLICY=true
      export STAGING_ENABLE_PROACTIVE_COMMITMENTS=true
      export STAGING_ENABLE_SYMBOLIC_EXTRACTION=true
      _persist STAGING_ENABLE_PROACTIVE_TOUCH_POLICY true
      _persist STAGING_ENABLE_PROACTIVE_COMMITMENTS true
      _persist STAGING_ENABLE_SYMBOLIC_EXTRACTION true
    fi
    export STAGING_ENABLE_SYMBOLIC_VERIFIER="$(_val)"
    export STAGING_ENABLE_FORWARD_REASONING=false
    _persist STAGING_ENABLE_SYMBOLIC_VERIFIER "$STAGING_ENABLE_SYMBOLIC_VERIFIER"
    _persist STAGING_ENABLE_FORWARD_REASONING false
    ;;
  *)
    echo "Unknown phase: $PHASE" >&2
    exit 1
    ;;
esac

echo "[staging_flags] ${PHASE} ${STATE} — recreating staging_backend + staging_bridge"
docker compose -f docker-compose.prod.yml -f docker-compose.staging.yml up -d staging_backend staging_bridge

echo "[staging_flags] Waiting for staging_backend health (up to 90s)"
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8011/health >/dev/null 2>&1; then
    break
  fi
  sleep 3
done
docker exec nate_staging_backend printenv \
  ENABLE_PROACTIVE_TOUCH_POLICY ENABLE_PROACTIVE_COMMITMENTS ENABLE_NATE_TOOL_EXECUTOR \
  ENABLE_THERAPEUTIC_PLANS ENABLE_NATE_SESSION_NEGOTIATION \
  ENABLE_SELF_MONITOR_AGENT ENABLE_SELF_MONITOR_COACH_ALERT ENABLE_SELF_MONITOR_TOUCH \
  ENABLE_SYMBOLIC_EXTRACTION ENABLE_SYMBOLIC_VERIFIER ENABLE_FORWARD_REASONING \
  2>/dev/null || true
docker exec nate_staging_bridge printenv \
  ENABLE_NATE_TOOL_EXECUTOR ENABLE_THERAPEUTIC_PLANS ENABLE_NATE_SESSION_NEGOTIATION \
  ENABLE_SYMBOLIC_EXTRACTION ENABLE_SYMBOLIC_VERIFIER \
  2>/dev/null || true
curl -sf http://127.0.0.1:8011/health
echo ""
echo "[staging_flags] OK"
