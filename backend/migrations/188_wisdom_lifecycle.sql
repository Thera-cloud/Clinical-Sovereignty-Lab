-- =============================================================================
-- Migration 188: Wisdom lifecycle (extraction queue → absorption)
-- Extends wisdom_extractions (015) for WisdomLifecycleManager.
-- =============================================================================

ALTER TABLE wisdom_extractions
    ADD COLUMN IF NOT EXISTS domain VARCHAR(64) DEFAULT 'clinical';

ALTER TABLE wisdom_extractions
    ADD COLUMN IF NOT EXISTS confidence REAL DEFAULT 0.5;

ALTER TABLE wisdom_extractions
    ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'pending';

ALTER TABLE wisdom_extractions
    ADD COLUMN IF NOT EXISTS absorbed_at TIMESTAMPTZ;

ALTER TABLE wisdom_extractions
    ADD COLUMN IF NOT EXISTS absorbed_by VARCHAR(256);

ALTER TABLE wisdom_extractions
    ADD COLUMN IF NOT EXISTS crystal_id VARCHAR(128);

ALTER TABLE wisdom_extractions
    ADD COLUMN IF NOT EXISTS night_school_entry_id VARCHAR(128);

ALTER TABLE wisdom_extractions
    ADD COLUMN IF NOT EXISTS rejection_reason TEXT;

UPDATE wisdom_extractions
SET confidence = COALESCE(NULLIF(effectiveness_score, 0.0), confidence, 0.5);

UPDATE wisdom_extractions
SET status = 'absorbed'
WHERE approved IS TRUE;

ALTER TABLE wisdom_extractions
    ALTER COLUMN domain SET DEFAULT 'clinical';

ALTER TABLE wisdom_extractions
    ALTER COLUMN confidence SET DEFAULT 0.5;

ALTER TABLE wisdom_extractions
    ALTER COLUMN status SET DEFAULT 'pending';

ALTER TABLE wisdom_extractions
    DROP CONSTRAINT IF EXISTS wisdom_extractions_status_check;

ALTER TABLE wisdom_extractions
    ADD CONSTRAINT wisdom_extractions_status_check
    CHECK (status IN ('pending', 'absorbed', 'rejected', 'expired'));

CREATE INDEX IF NOT EXISTS idx_wisdom_extractions_status
    ON wisdom_extractions(status);

CREATE INDEX IF NOT EXISTS idx_wisdom_extractions_extracted_pending
    ON wisdom_extractions(extracted_at)
    WHERE status = 'pending';
