#!/bin/bash
# =============================================================================
# Sovereign Sanctuary — Daily Encrypted Backup to 100GB Volume
# Backs up: PostgreSQL, Redis, Vaults, sessions, user registry, analytics
# Retention: 14 daily backups, 8 weekly backups
# All backups encrypted with AES-256-CBC via BACKUP_ENCRYPTION_KEY
# =============================================================================

set -euo pipefail

BACKUP_ROOT=/mnt/volume_sfo2_01/backups
DAILY_DIR=$BACKUP_ROOT/daily
WEEKLY_DIR=$BACKUP_ROOT/weekly
PG_DIR=$BACKUP_ROOT/postgres
REDIS_DIR=$BACKUP_ROOT/redis
DATA_DIR=/opt/clinical-sovereignty-lab/data
ENV_FILE=/opt/clinical-sovereignty-lab/.env
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DAY_OF_WEEK=$(date +%u)

BACKUP_KEY=$(grep '^BACKUP_ENCRYPTION_KEY=' "$ENV_FILE" | cut -d= -f2)
if [ -z "$BACKUP_KEY" ]; then
    echo "[$(date)] FATAL: BACKUP_ENCRYPTION_KEY not set in .env — aborting"
    exit 1
fi

encrypt_file() {
    local src="$1"
    local dst="${src}.enc"
    openssl enc -aes-256-cbc -salt -pbkdf2 -iter 100000 \
        -in "$src" -out "$dst" -pass "pass:${BACKUP_KEY}"
    rm -f "$src"
    echo "$dst"
}

echo "[$(date)] Starting Sovereign encrypted backup..."

# ── PostgreSQL full dump ──
echo "  [1/4] PostgreSQL dump..."
docker exec nate_postgres pg_dump -U nate_admin -d little_nate --format=custom \
    > "$PG_DIR/little_nate_$TIMESTAMP.dump" 2>/dev/null
RAW_SIZE=$(du -sh "$PG_DIR/little_nate_$TIMESTAMP.dump" | cut -f1)
ENC_PATH=$(encrypt_file "$PG_DIR/little_nate_$TIMESTAMP.dump")
echo "    -> raw $RAW_SIZE, encrypted $(du -sh "$ENC_PATH" | cut -f1)"

# ── Redis RDB snapshot ──
echo "  [2/4] Redis snapshot..."
REDIS_PW=$(grep '^REDIS_PASSWORD=' "$ENV_FILE" | cut -d= -f2)
docker exec nate_redis redis-cli -a "$REDIS_PW" --no-auth-warning BGSAVE >/dev/null 2>&1
sleep 2
docker cp nate_redis:/data/dump.rdb "$REDIS_DIR/redis_$TIMESTAMP.rdb" 2>/dev/null || true
if [ -f "$REDIS_DIR/redis_$TIMESTAMP.rdb" ]; then
    ENC_PATH=$(encrypt_file "$REDIS_DIR/redis_$TIMESTAMP.rdb")
    echo "    -> encrypted $(du -sh "$ENC_PATH" | cut -f1)"
else
    echo "    -> skipped (no RDB file)"
fi

# ── Application data (Vaults, sessions, analytics, user registry) ──
echo "  [3/4] Application data..."
tar czf "$DAILY_DIR/app_data_$TIMESTAMP.tar.gz" \
    -C "$DATA_DIR/bridge" \
    Vaults/ \
    analytics.json \
    sessions.json \
    user_registry.json \
    family_sanctuaries.json \
    crisis_log.json \
    coach_live_sessions.json \
    coach_compensation_ledger.json \
    email_log.json \
    sms_log.json \
    2>/dev/null
RAW_SIZE=$(du -sh "$DAILY_DIR/app_data_$TIMESTAMP.tar.gz" | cut -f1)
ENC_PATH=$(encrypt_file "$DAILY_DIR/app_data_$TIMESTAMP.tar.gz")
echo "    -> raw $RAW_SIZE, encrypted $(du -sh "$ENC_PATH" | cut -f1)"

# ── Weekly copy (Sundays) ──
if [ "$DAY_OF_WEEK" = "7" ]; then
    echo "  [4/4] Weekly snapshot (Sunday)..."
    cp "$DAILY_DIR/app_data_$TIMESTAMP.tar.gz.enc" "$WEEKLY_DIR/weekly_$TIMESTAMP.tar.gz.enc"
    cp "$PG_DIR/little_nate_$TIMESTAMP.dump.enc" "$WEEKLY_DIR/pg_weekly_$TIMESTAMP.dump.enc"
else
    echo "  [4/4] Skipping weekly (not Sunday)"
fi

# ── Retention cleanup ──
echo "  Cleaning old backups..."
find "$DAILY_DIR" -name '*.tar.gz.enc' -mtime +14 -delete 2>/dev/null || true
find "$DAILY_DIR" -name '*.tar.gz' -mtime +14 -delete 2>/dev/null || true
find "$PG_DIR" -name '*.dump.enc' -mtime +14 -delete 2>/dev/null || true
find "$PG_DIR" -name '*.dump' -mtime +14 -delete 2>/dev/null || true
find "$REDIS_DIR" -name '*.rdb.enc' -mtime +14 -delete 2>/dev/null || true
find "$REDIS_DIR" -name '*.rdb' -mtime +14 -delete 2>/dev/null || true
find "$WEEKLY_DIR" -name '*' -type f -mtime +56 -delete 2>/dev/null || true

TOTAL_USED=$(du -sh "$BACKUP_ROOT" | cut -f1)
VOLUME_FREE=$(df -h /mnt/volume_sfo2_01 | tail -1 | awk '{print $4}')
echo "[$(date)] Backup complete. Backup total: $TOTAL_USED, Volume free: $VOLUME_FREE"
