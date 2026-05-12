#!/usr/bin/env bash
# Resolve a bridge token on GREEN via exact username+role JSON match (no Redis substring grep).
# Usage:
#   ./scripts/ssh_green_resolve_bridge_token.sh CoachN COACH
#   GREEN_SSH='root@OTHER' ./scripts/ssh_green_resolve_bridge_token.sh DrNevedal1 ADMIN
# List every CoachN COACH session (sorted newest last_login first):
#   LIST_ALL=1 ./scripts/ssh_green_resolve_bridge_token.sh CoachN COACH
set -euo pipefail
HOST="${GREEN_SSH:-root@68.183.168.75}"
USER="${1:?username}"
ROLE="${2:?role}"
UA=$(printf '%q' "${USER}")
RA=$(printf '%q' "${ROLE}")
LIST_ARG=""
if [[ "${LIST_ALL:-}" == "1" ]]; then
  LIST_ARG=" --list-all"
fi
exec ssh -o BatchMode=yes "${HOST}" \
  "docker exec nate_backend python3 /app/scripts/redis_resolve_bridge_tokens.py --username ${UA} --role ${RA}${LIST_ARG}"
