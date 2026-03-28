#!/bin/bash
# =============================================================================
# Sovereign Sanctuary — Backup Decryption Helper
# Usage: ./decrypt_backup.sh <encrypted_file> [output_file]
# =============================================================================

set -euo pipefail

ENV_FILE=/opt/clinical-sovereignty-lab/.env

if [ $# -lt 1 ]; then
    echo "Usage: $0 <encrypted_file.enc> [output_file]"
    echo ""
    echo "If output_file is not specified, strips the .enc extension."
    echo ""
    echo "Examples:"
    echo "  $0 /mnt/volume_sfo2_01/backups/postgres/little_nate_20260306.dump.enc"
    echo "  $0 /mnt/volume_sfo2_01/backups/daily/app_data_20260306.tar.gz.enc /tmp/restore.tar.gz"
    exit 1
fi

ENCRYPTED="$1"
OUTPUT="${2:-${ENCRYPTED%.enc}}"

if [ ! -f "$ENCRYPTED" ]; then
    echo "ERROR: File not found: $ENCRYPTED"
    exit 1
fi

BACKUP_KEY=$(grep '^BACKUP_ENCRYPTION_KEY=' "$ENV_FILE" | cut -d= -f2)
if [ -z "$BACKUP_KEY" ]; then
    echo "ERROR: BACKUP_ENCRYPTION_KEY not set in $ENV_FILE"
    exit 1
fi

echo "Decrypting: $ENCRYPTED"
echo "Output:     $OUTPUT"

openssl enc -aes-256-cbc -d -salt -pbkdf2 -iter 100000 \
    -in "$ENCRYPTED" -out "$OUTPUT" -pass "pass:${BACKUP_KEY}"

echo "Decrypted successfully ($(du -sh "$OUTPUT" | cut -f1))"
echo ""
echo "Restore commands:"
if [[ "$OUTPUT" == *.dump ]]; then
    echo "  pg_restore -U nate_admin -d little_nate $OUTPUT"
elif [[ "$OUTPUT" == *.tar.gz ]]; then
    echo "  tar xzf $OUTPUT -C /target/directory/"
elif [[ "$OUTPUT" == *.rdb ]]; then
    echo "  cp $OUTPUT /var/lib/docker/volumes/redis_data/_data/dump.rdb"
    echo "  docker restart nate_redis"
fi
