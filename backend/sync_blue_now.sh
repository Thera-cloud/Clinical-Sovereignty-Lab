#!/bin/bash
# One-shot: push all unsynced BLUE crystals from local SQLite to production PostgreSQL.
# Run from Mac: ./backend/sync_blue_now.sh
# Requires: SSH access to 68.183.168.75

set -e
cd "$(dirname "$0")/.."

SQLITE_DB="backend/app/websocket/data/nate_crystals_blue.db"
if [ ! -f "$SQLITE_DB" ]; then
  echo "No local SQLite crystal store found at $SQLITE_DB"
  exit 1
fi

COUNT=$(sqlite3 "$SQLITE_DB" "SELECT COUNT(*) FROM crystals WHERE synced_to_production = 0")
echo "Found $COUNT unsynced BLUE crystals"
if [ "$COUNT" -eq 0 ]; then
  echo "Nothing to sync."
  exit 0
fi

# Generate SQL INSERT statements
SQL=$(sqlite3 "$SQLITE_DB" "
SELECT 'INSERT INTO nate_intelligence_crystals (crystal_text, domain, scope, topics, source_count, generation, confidence, content_hash, face_path) VALUES ('
  || '''' || REPLACE(crystal_text, '''', '''''') || ''', '
  || '''' || domain || ''', '
  || '''' || scope || ''', '
  || 'ARRAY[' || CASE WHEN topics IS NOT NULL AND topics != '[]' THEN
    REPLACE(REPLACE(REPLACE(topics, '[', ''), ']', ''), '\"', '''')
  ELSE '' END || '], '
  || source_count || ', 0, '
  || confidence || ', '
  || '''' || content_hash || ''', '
  || '''' || COALESCE(face_path, 'bridge:mac-blue') || ''''
  || ') ON CONFLICT (content_hash) DO NOTHING;'
FROM crystals WHERE synced_to_production = 0;
")

echo "Pushing $COUNT crystals to production PostgreSQL..."
echo "$SQL" | ssh root@68.183.168.75 "docker exec -i nate_postgres psql -U nate_admin -d little_nate"

if [ $? -eq 0 ]; then
  echo "Marking crystals as synced locally..."
  sqlite3 "$SQLITE_DB" "UPDATE crystals SET synced_to_production = 1 WHERE synced_to_production = 0"
  echo "Done! $COUNT crystals synced."
else
  echo "Push failed — crystals NOT marked as synced."
  exit 1
fi
