-- Crystal edges: persistent nearest-neighbor graph for constellation retrieval
-- Activates at 5,000+ crystal density for cross-crystal relationship mapping

CREATE TABLE IF NOT EXISTS crystal_edges (
    crystal_a_hash  VARCHAR(64) NOT NULL,
    crystal_b_hash  VARCHAR(64) NOT NULL,
    similarity      FLOAT NOT NULL,
    edge_type       VARCHAR(50) DEFAULT 'semantic_neighbor',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (crystal_a_hash, crystal_b_hash)
);

CREATE INDEX IF NOT EXISTS idx_crystal_edges_a ON crystal_edges(crystal_a_hash);
CREATE INDEX IF NOT EXISTS idx_crystal_edges_b ON crystal_edges(crystal_b_hash);
CREATE INDEX IF NOT EXISTS idx_crystal_edges_sim ON crystal_edges(similarity DESC);

-- Firehose ingestion tracking (mirrors ORANGE SQLite for GREEN-side visibility)
CREATE TABLE IF NOT EXISTS firehose_ingestion_log (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(200) NOT NULL,
    domain          VARCHAR(50) NOT NULL,
    fragments_in    INTEGER DEFAULT 0,
    crystals_out    INTEGER DEFAULT 0,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    status          VARCHAR(20) DEFAULT 'running',
    metadata        JSONB
);

CREATE INDEX IF NOT EXISTS idx_firehose_log_source ON firehose_ingestion_log(source);
