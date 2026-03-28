-- Migration 146: Code Cycle Detection Tables
-- Supports CodeCycleDetector: divergence tracking, pre-warm logging

-- Dual-brain divergence events (edge vs sovereign disagreements)
CREATE TABLE IF NOT EXISTS code_divergence_log (
    id              BIGSERIAL PRIMARY KEY,
    topic_hash      VARCHAR(16) NOT NULL,
    topic_label     VARCHAR(255) NOT NULL,
    query_text      TEXT,
    cosine_similarity FLOAT NOT NULL,
    edge_provider   VARCHAR(50) DEFAULT 'workers_ai',
    sovereign_provider VARCHAR(50) DEFAULT 'sovereign',
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_divergence_topic_hash
    ON code_divergence_log (topic_hash);
CREATE INDEX IF NOT EXISTS idx_divergence_detected_at
    ON code_divergence_log (detected_at);

-- Crystal pre-warm activity log
CREATE TABLE IF NOT EXISTS crystal_prewarm_log (
    id                  BIGSERIAL PRIMARY KEY,
    crystal_count       INT NOT NULL DEFAULT 0,
    source_divergence   INT NOT NULL DEFAULT 0,
    source_recurrence   INT NOT NULL DEFAULT 0,
    source_temporal     INT NOT NULL DEFAULT 0,
    manifest_key        VARCHAR(255),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prewarm_log_created_at
    ON crystal_prewarm_log (created_at);
