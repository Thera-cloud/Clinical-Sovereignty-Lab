#!/usr/bin/env python3
"""One-shot: dump unsynced BLUE crystals as SQL for piping to production PostgreSQL.

Usage:
    python3 backend/sync_blue_now.py | ssh root@68.183.168.75 "docker exec -i nate_postgres psql -U nate_admin -d little_nate"

Then mark as synced:
    python3 backend/sync_blue_now.py --mark-synced
"""
import json
import sqlite3
import sys

DB_PATH = "backend/app/websocket/data/local_crystals.db"

def escape_sql(s: str) -> str:
    if s is None:
        return "NULL"
    return "'" + s.replace("'", "''").replace("\\", "\\\\") + "'"

def topics_to_pg_array(topics_json: str) -> str:
    try:
        items = json.loads(topics_json) if topics_json else []
    except (json.JSONDecodeError, TypeError):
        items = []
    if not items:
        return "ARRAY[]::TEXT[]"
    escaped = ", ".join(escape_sql(t) for t in items)
    return f"ARRAY[{escaped}]"

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if "--mark-synced" in sys.argv:
        cur = conn.execute("UPDATE crystals SET synced_to_production = 1 WHERE synced_to_production = 0")
        conn.commit()
        print(f"Marked {cur.rowcount} crystals as synced.", file=sys.stderr)
        return

    rows = conn.execute("""
        SELECT crystal_text, domain, scope, topics, source_count,
               confidence, content_hash, face_path
        FROM crystals WHERE synced_to_production = 0
        ORDER BY created_at ASC
    """).fetchall()

    if not rows:
        print("-- No unsynced crystals.", file=sys.stderr)
        return

    print(f"-- Syncing {len(rows)} BLUE crystals to production", file=sys.stderr)
    print("BEGIN;")
    for r in rows:
        fp = r["face_path"] or "bridge:mac-blue"
        print(f"""INSERT INTO nate_intelligence_crystals
  (crystal_text, domain, scope, topics, source_count, generation, confidence, content_hash, face_path)
VALUES (
  {escape_sql(r['crystal_text'])},
  {escape_sql(r['domain'])},
  {escape_sql(r['scope'])},
  {topics_to_pg_array(r['topics'])},
  {r['source_count']}, 0, {r['confidence']},
  {escape_sql(r['content_hash'])},
  {escape_sql(fp)}
) ON CONFLICT (content_hash) DO NOTHING;""")
    print("COMMIT;")
    print(f"-- Done. Run: python3 backend/sync_blue_now.py --mark-synced", file=sys.stderr)

if __name__ == "__main__":
    main()
