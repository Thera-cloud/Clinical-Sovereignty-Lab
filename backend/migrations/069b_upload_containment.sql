-- Migration 069: Upload Containment Pipeline
-- Adds logging table for content security scans

CREATE TABLE IF NOT EXISTS upload_containment_log (
    id            BIGSERIAL PRIMARY KEY,
    scan_id       VARCHAR(64) NOT NULL UNIQUE,
    user_id       VARCHAR(128),
    content_hash  VARCHAR(64) NOT NULL,
    scan_result   VARCHAR(20) NOT NULL,  -- CLEAN, FLAGGED, QUARANTINED
    threats_detected JSONB DEFAULT '[]'::jsonb,
    source        VARCHAR(40),           -- file_upload, pasted_text, transfer_crystal, etc.
    scanned_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_containment_user
    ON upload_containment_log (user_id, scanned_at DESC);

CREATE INDEX IF NOT EXISTS idx_containment_verdict
    ON upload_containment_log (scan_result, scanned_at DESC);

CREATE INDEX IF NOT EXISTS idx_containment_hash
    ON upload_containment_log (content_hash);
