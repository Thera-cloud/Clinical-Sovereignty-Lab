-- Migration 271: LN-Observer forensic pixel archive key
-- Additive: storage_key for R2/local JPEG of the paired frame.

ALTER TABLE ln_observer_forensic_events
    ADD COLUMN IF NOT EXISTS storage_key TEXT;

CREATE INDEX IF NOT EXISTS idx_lnobs_forensic_storage
    ON ln_observer_forensic_events (storage_key)
    WHERE storage_key IS NOT NULL;
