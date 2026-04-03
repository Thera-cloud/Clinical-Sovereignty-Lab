-- Migration 168: SSE IP Provenance tracking table
-- Records source document origin for every SSE Story Creation Generator pipeline run.

CREATE TABLE IF NOT EXISTS sse_ip_provenance (
    provenance_id       UUID PRIMARY KEY,
    filename            TEXT NOT NULL,
    uploader_id         TEXT NOT NULL,
    upload_timestamp    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    story_plot_id       TEXT,
    status              TEXT NOT NULL DEFAULT 'processing',
    source_hash         TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sse_ip_provenance_source_hash
    ON sse_ip_provenance (source_hash)
    WHERE status = 'complete';

CREATE INDEX IF NOT EXISTS idx_sse_ip_provenance_uploader
    ON sse_ip_provenance (uploader_id);
