#!/bin/bash
# socket_churn_watch.sh — detect WebSocket eviction storms per user.
# Run on GREEN: bash /opt/clinical-sovereignty-lab/backend/scripts/socket_churn_watch.sh [WINDOW_MINUTES] [THRESHOLD]
# Defaults: 60 min window, alert if >10 evictions per user in that window.
# Exit codes: 0 = no churn, 2 = threshold breached (cron-friendly).

set -euo pipefail

WINDOW_MIN="${1:-60}"
THRESHOLD="${2:-10}"
SINCE="${WINDOW_MIN}m"

EVICT_LINES=$(docker logs nate_bridge --since "${SINCE}" 2>&1 | grep -E '\[SOCKET EVICT\] uid=' || true)

if [ -z "${EVICT_LINES}" ]; then
  echo "OK: no SOCKET EVICT events in last ${WINDOW_MIN} min."
  exit 0
fi

# Tally per-uid eviction counts.
TALLY=$(printf '%s\n' "${EVICT_LINES}" \
  | sed -nE 's/.*\[SOCKET EVICT\] uid=([A-Za-z0-9_-]+).*/\1/p' \
  | sort | uniq -c | sort -rn)

BREACHED=$(printf '%s\n' "${TALLY}" | awk -v t="${THRESHOLD}" '$1 >= t {print}')

echo "=== Socket churn report (last ${WINDOW_MIN} min, threshold ${THRESHOLD}) ==="
printf '%s\n' "${TALLY}"
echo

if [ -n "${BREACHED}" ]; then
  echo "!!! CHURN THRESHOLD BREACHED !!!"
  printf '%s\n' "${BREACHED}"
  exit 2
fi

echo "OK: no user exceeded ${THRESHOLD} evictions."
exit 0
