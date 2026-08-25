-- Workbook auto-learn index (coaching tools, not therapy)
CREATE TABLE IF NOT EXISTS workbook_ingest_index (
    rel_path TEXT PRIMARY KEY,
    content_sha256 CHAR(64) NOT NULL,
    file_mtime TIMESTAMPTZ,
    bytes BIGINT,
    last_learned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    crystals_created INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'learned',
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_workbook_ingest_learned
    ON workbook_ingest_index (last_learned_at DESC);
