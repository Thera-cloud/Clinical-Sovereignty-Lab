-- Night School ingestion: durable store for merged wisdom learnings (JSON remains canonical for editor)
CREATE TABLE IF NOT EXISTS night_school_wisdom (
    id SERIAL PRIMARY KEY,
    entry_id VARCHAR(128) UNIQUE NOT NULL,
    category VARCHAR(128),
    content TEXT,
    source_tag VARCHAR(256),
    confidence REAL DEFAULT 0.5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_night_school_wisdom_created
    ON night_school_wisdom (created_at DESC);

COMMENT ON TABLE night_school_wisdom IS 'Append-only ingest rows from NightSchool._synthesize_learnings; entry_id ns_<learning_history_id>';
