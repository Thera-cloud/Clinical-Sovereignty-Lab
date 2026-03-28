-- Migration 117: Backblaze B2 Heritage Vault Integration
-- Adds b2_ok column to heritage_vault_replication_log for penta-redundant tracking.

ALTER TABLE heritage_vault_replication_log
    ADD COLUMN IF NOT EXISTS b2_ok BOOLEAN DEFAULT FALSE;

-- Index for cold tier migration tracking
CREATE INDEX IF NOT EXISTS idx_skyeye_activity_cold_tier
    ON skyeye_activity (type, created_at)
    WHERE type = 'cold_tier_migration';
