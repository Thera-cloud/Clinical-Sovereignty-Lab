"""
Firehose Progress Tracker — SQLite-backed resumable state for harvest scripts.

Every harvest script calls tracker.mark_done(source, item_id) after processing.
On restart, tracker.is_done(source, item_id) returns True for already-processed items.
Also tracks aggregate statistics per source for monitoring.
"""

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "firehose_progress.db")


class ProgressTracker:
    """SQLite-backed progress tracker for firehose harvest scripts."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS progress (
                source      TEXT NOT NULL,
                item_id     TEXT NOT NULL,
                domain      TEXT,
                status      TEXT DEFAULT 'done',
                created_at  TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (source, item_id)
            );

            CREATE TABLE IF NOT EXISTS source_stats (
                source          TEXT PRIMARY KEY,
                total_processed INTEGER DEFAULT 0,
                total_passed    INTEGER DEFAULT 0,
                total_failed    INTEGER DEFAULT 0,
                last_item_id    TEXT,
                last_updated    TEXT DEFAULT (datetime('now')),
                metadata        TEXT
            );

            CREATE TABLE IF NOT EXISTS firehose_status (
                key     TEXT PRIMARY KEY,
                value   TEXT,
                updated TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_progress_source ON progress(source);
        """)
        self._conn.commit()

    def is_done(self, source: str, item_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM progress WHERE source = ? AND item_id = ?",
            (source, item_id),
        ).fetchone()
        return row is not None

    def mark_done(self, source: str, item_id: str, domain: str = None,
                  passed: bool = True):
        self._conn.execute(
            "INSERT OR IGNORE INTO progress (source, item_id, domain) VALUES (?, ?, ?)",
            (source, item_id, domain),
        )
        col = "total_passed" if passed else "total_failed"
        self._conn.execute(f"""
            INSERT INTO source_stats (source, total_processed, {col}, last_item_id, last_updated)
            VALUES (?, 1, 1, ?, datetime('now'))
            ON CONFLICT(source) DO UPDATE SET
                total_processed = total_processed + 1,
                {col} = {col} + 1,
                last_item_id = excluded.last_item_id,
                last_updated = datetime('now')
        """, (source, item_id))
        self._conn.commit()

    def mark_batch_done(self, source: str, item_ids: List[str],
                        domain: str = None):
        for iid in item_ids:
            self._conn.execute(
                "INSERT OR IGNORE INTO progress (source, item_id, domain) VALUES (?, ?, ?)",
                (source, iid, domain),
            )
        self._conn.execute("""
            INSERT INTO source_stats (source, total_processed, total_passed, last_item_id, last_updated)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(source) DO UPDATE SET
                total_processed = total_processed + ?,
                total_passed = total_passed + ?,
                last_item_id = excluded.last_item_id,
                last_updated = datetime('now')
        """, (source, len(item_ids), len(item_ids), item_ids[-1] if item_ids else "",
              len(item_ids), len(item_ids)))
        self._conn.commit()

    def get_done_count(self, source: str) -> int:
        row = self._conn.execute(
            "SELECT total_processed FROM source_stats WHERE source = ?",
            (source,),
        ).fetchone()
        return row[0] if row else 0

    def get_stats(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT source, total_processed, total_passed, total_failed, "
            "last_item_id, last_updated FROM source_stats ORDER BY source"
        ).fetchall()
        return [
            {"source": r[0], "processed": r[1], "passed": r[2],
             "failed": r[3], "last_item": r[4], "updated": r[5]}
            for r in rows
        ]

    def set_status(self, key: str, value: str):
        self._conn.execute(
            "INSERT OR REPLACE INTO firehose_status (key, value, updated) "
            "VALUES (?, ?, datetime('now'))",
            (key, value),
        )
        self._conn.commit()

    def get_status(self, key: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM firehose_status WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def write_status_json(self, path: str = "/var/log/firehose_status.json"):
        stats = self.get_stats()
        total = sum(s["processed"] for s in stats)
        passed = sum(s["passed"] for s in stats)
        status = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_fragments_processed": total,
            "total_fragments_passed": passed,
            "sources": stats,
            "current_phase": self.get_status("current_phase") or "idle",
            "current_source": self.get_status("current_source") or "none",
        }
        try:
            with open(path, "w") as f:
                json.dump(status, f, indent=2)
        except PermissionError:
            pass

    def close(self):
        self._conn.close()
