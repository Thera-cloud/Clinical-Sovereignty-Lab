-- Migration 192: Cloudflare R2 Heritage Vault Integration
-- Adds r2_ok column to heritage_vault_replication_log so the
-- MultiCloudHeritageVault can record per-backend status for the
-- new R2 leg (4 cloud backends + B2 cold tier = penta-redundant).

ALTER TABLE IF EXISTS heritage_vault_replication_log
    ADD COLUMN IF NOT EXISTS r2_ok BOOLEAN DEFAULT FALSE;

-- Index to quickly find vault keys that landed on R2 (used by the
-- cold-tier-agent for "should I migrate this to B2 yet?" checks).
CREATE INDEX IF NOT EXISTS idx_heritage_vault_r2_ok
    ON heritage_vault_replication_log (r2_ok, created_at)
    WHERE r2_ok = TRUE;
