#!/usr/bin/env bash
# Always-on LN7 drain worker (BLUE). Polls GREEN queue; runs TOR drain when jobs wait.
# Promote stays manual (ENABLE_LN7_AUTO_PROMOTE=false).
#
#   bash scripts/ln7_continuous_worker.sh          # one cycle
#   LN7_WORKER_LOOP=1 bash scripts/ln7_continuous_worker.sh   # forever
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
GREEN="${LN7_GREEN_HOST:-root@68.183.168.75}"
SLEEP="${LN7_WORKER_SLEEP_S:-300}"
REGION="${LN7_GPU_REGION:-tor1}"
export LN7_GPU_REGION="$REGION"

queued() {
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$GREEN" \
    "docker exec nate_postgres psql -U nate_admin -d little_nate -tAc \
     \"SELECT count(*) FROM ln7_train_jobs WHERE status IN ('queued','claimed')\"" \
    | tr -d '[:space:]'
}

one_cycle() {
  n="$(queued || echo 0)"
  echo "[worker] $(date -u +%Y-%m-%dT%H%M%SZ) queued=$n region=$REGION"
  if [[ "${n:-0}" =~ ^[0-9]+$ ]] && [[ "$n" -ge 1 ]]; then
    echo "[worker] draining via ln7_continuous_drain.sh"
    LN7_GPU_REGION="$REGION" bash "$REPO/scripts/ln7_continuous_drain.sh" || {
      echo "[worker] drain failed (will retry next cycle)"
      return 1
    }
  else
    echo "[worker] idle"
  fi
}

if [[ "${LN7_WORKER_LOOP:-}" == "1" ]]; then
  while true; do
    one_cycle || true
    sleep "$SLEEP"
  done
else
  one_cycle
fi
