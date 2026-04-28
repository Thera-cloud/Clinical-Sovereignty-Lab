#!/usr/bin/env bash
# pgbouncer-48h-monitor.sh
#
# Captures pgbouncer + postgres + docker container metrics every 6h for 48h,
# then removes its own cron entry. Designed to be run from cron and once
# manually at install time to seed the start timestamp + baseline capture.
#
# Window: 48 hours from first run (recorded in $START_FILE).
# User spec said "Wednesday 9pm ET" but Wed 9pm ET = ~72h from a Sun 9:58pm ET
# install — the body of the spec said "48 hours", so this script honors 48h
# explicitly. Update DURATION_SECONDS below if the window ever needs to grow.
#
# Cron line installed alongside this script:
#   0 */6 * * * /opt/clinical-sovereignty-lab/scripts/pgbouncer-48h-monitor.sh
#
# Output: appended to $LOG. Each capture is wrapped in a header banner for
# easy grep-based slicing after the window closes.

set -uo pipefail

LOG=/opt/clinical-sovereignty-lab/logs/pgbouncer-48h-monitor.log
START_FILE=/opt/clinical-sovereignty-lab/logs/.pgbouncer-monitor-start
DURATION_SECONDS=$((48 * 3600))
ENV_FILE=/opt/clinical-sovereignty-lab/.env
SCRIPT_PATH=/opt/clinical-sovereignty-lab/scripts/pgbouncer-48h-monitor.sh
CRON_PATTERN='pgbouncer-48h-monitor.sh'

mkdir -p "$(dirname "$LOG")"

# Seed start timestamp on the first run so cron-only restarts don't reset the window.
if [ ! -f "$START_FILE" ]; then
    date -u +%s > "$START_FILE"
fi

START_TS=$(cat "$START_FILE")
NOW_TS=$(date -u +%s)
ELAPSED=$((NOW_TS - START_TS))

# Pull postgres password from the prod env file (same source the containers use).
if [ -r "$ENV_FILE" ]; then
    PGPASSWORD=$(grep '^POSTGRES_PASSWORD=' "$ENV_FILE" | head -1 | cut -d= -f2-)
    export PGPASSWORD
else
    echo "[!] $ENV_FILE not readable; pgbouncer/postgres queries will fail" >> "$LOG"
fi

{
    echo "================================================================"
    echo "Capture: $(date -u '+%Y-%m-%dT%H:%M:%SZ')  (UTC)"
    echo "         $(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z')"
    printf "Elapsed since window start: %dh %dm\n" $((ELAPSED / 3600)) $(((ELAPSED % 3600) / 60))
    echo "================================================================"

    echo
    echo "--- 1. pgbouncer SHOW STATS / SHOW POOLS (admin DB) ---"
    docker exec -e PGPASSWORD="$PGPASSWORD" nate_pgbouncer \
        psql -h 127.0.0.1 -p 6432 -U nate_admin -d pgbouncer \
        -c "SHOW STATS;" -c "SHOW POOLS;" 2>&1 \
        || echo "[!] pgbouncer query failed"

    echo
    echo "--- 2. postgres pg_stat_activity (by state) ---"
    docker exec -e PGPASSWORD="$PGPASSWORD" nate_postgres \
        psql -U nate_admin -d little_nate \
        -c "SELECT count(*) AS conns, state FROM pg_stat_activity GROUP BY state ORDER BY conns DESC;" 2>&1 \
        || echo "[!] postgres query failed"

    echo
    echo "--- 3. docker stats (no-stream) ---"
    docker stats --no-stream \
        --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}" \
        nate_pgbouncer nate_postgres nate_backend nate_bridge 2>&1 \
        || echo "[!] docker stats failed"

    echo
} >> "$LOG" 2>&1

# Self-terminate once the 48h window has elapsed.
if [ "$ELAPSED" -ge "$DURATION_SECONDS" ]; then
    {
        echo "================================================================"
        echo "TERMINATION: $(date -u '+%Y-%m-%dT%H:%M:%SZ') — 48h window complete."
        echo "Removing cron entry matching: $CRON_PATTERN"
        echo "================================================================"
    } >> "$LOG"
    ( crontab -l 2>/dev/null | grep -v "$CRON_PATTERN" ) | crontab -
    rm -f "$START_FILE"
fi
