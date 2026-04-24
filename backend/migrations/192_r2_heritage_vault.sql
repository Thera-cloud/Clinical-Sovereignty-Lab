-- Migration 192: Cloudflare R2 Heritage Vault Integration
--
-- 1. Creates heritage_vault_replication_log if it has never been
--    materialised (the prior migrations 117 / multi_cloud_heritage_vault
--    referenced it without ever creating it, so it's been silently
--    no-op'ing in production).
-- 2. Adds r2_ok column for the new Cloudflare R2 leg of the
--    quad-redundant Heritage Vault (R2 + Azure + AWS + Local NAS).
-- 3. b2_ok stays for the cold-tier-agent's Backblaze migration target.

CREATE TABLE IF NOT EXISTS heritage_vault_replication_log (
    id            BIGSERIAL PRIMARY KEY,
    vault_key     TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    azure_ok      BOOLEAN DEFAULT FALSE,
    aws_ok        BOOLEAN DEFAULT FALSE,
    local_ok      BOOLEAN DEFAULT FALSE,
    durable       BOOLEAN DEFAULT FALSE,
    errors        JSONB DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_heritage_vault_key_created
    ON heritage_vault_replication_log (vault_key, created_at DESC);

ALTER TABLE heritage_vault_replication_log
    ADD COLUMN IF NOT EXISTS r2_ok BOOLEAN DEFAULT FALSE;

ALTER TABLE heritage_vault_replication_log
    ADD COLUMN IF NOT EXISTS b2_ok BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_heritage_vault_r2_ok
    ON heritage_vault_replication_log (r2_ok, created_at)
    WHERE r2_ok = TRUE;
