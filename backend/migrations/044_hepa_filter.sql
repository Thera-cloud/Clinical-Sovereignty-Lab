-- Migration 044: HEPA Filter (Hive Defense v4.3)
-- Heritage & Emotional Protection Architecture: 7 protections

-- Staged deletions (Cooling Breath)
CREATE TABLE IF NOT EXISTS staged_deletions (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT NOT NULL,
    data_type           TEXT NOT NULL,     -- session, crystal, vault_entry, account, family_data
    data_id             TEXT NOT NULL,
    cooling_period_hours INT NOT NULL,
    requested_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executes_at         TIMESTAMPTZ NOT NULL,
    checkin_24h         BOOLEAN DEFAULT FALSE,
    checkin_midpoint    BOOLEAN DEFAULT FALSE,
    checkin_final       BOOLEAN DEFAULT FALSE,
    cancelled           BOOLEAN DEFAULT FALSE,
    cancelled_at        TIMESTAMPTZ,
    executed            BOOLEAN DEFAULT FALSE,
    executed_at         TIMESTAMPTZ,
    grief_flag          BOOLEAN DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_staged_deletions_user ON staged_deletions (user_id, executed, cancelled);
CREATE INDEX IF NOT EXISTS idx_staged_deletions_executes ON staged_deletions (executes_at) WHERE NOT executed AND NOT cancelled;

-- Heritage Vault records (100-year immutable storage)
CREATE TABLE IF NOT EXISTS heritage_vault_records (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT NOT NULL,
    vault_type          TEXT NOT NULL,     -- session, crystal, wisdom, family_narrative
    content_hash        TEXT NOT NULL,
    encrypted_content   BYTEA,
    storage_tier        TEXT DEFAULT 'local',  -- local, azure_blob, aws_s3
    retention_years     INT DEFAULT 100,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accessed_at         TIMESTAMPTZ,
    access_count        INT DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_heritage_vault_user ON heritage_vault_records (user_id);
CREATE INDEX IF NOT EXISTS idx_heritage_vault_type ON heritage_vault_records (vault_type);

-- Legacy wishes (death notification handling)
CREATE TABLE IF NOT EXISTS legacy_wishes (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT UNIQUE NOT NULL,
    wish_type           TEXT NOT NULL DEFAULT 'max_protection',  -- max_protection, selective_share, full_delete
    designated_contacts JSONB DEFAULT '[]',
    specific_instructions TEXT,
    last_updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated           BOOLEAN DEFAULT FALSE,
    activated_at        TIMESTAMPTZ,
    activated_by        TEXT
);
CREATE INDEX IF NOT EXISTS idx_legacy_wishes_user ON legacy_wishes (user_id);

-- Cooling check-ins
CREATE TABLE IF NOT EXISTS cooling_checkins (
    id                  BIGSERIAL PRIMARY KEY,
    deletion_id         BIGINT NOT NULL REFERENCES staged_deletions(id),
    checkin_type        TEXT NOT NULL,  -- 24h, midpoint, final
    user_response       TEXT,           -- confirm, cancel, modify
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cooling_checkins_deletion ON cooling_checkins (deletion_id);

-- Grief detection signals
CREATE TABLE IF NOT EXISTS grief_signals (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT NOT NULL,
    signal_type         TEXT NOT NULL,  -- post_me2me_deletion, anniversary, bulk_pattern, nocturnal
    confidence          REAL NOT NULL DEFAULT 0.0,
    details             JSONB,
    intervention_type   TEXT,           -- gentle_checkin, delay_deletion, escalate_to_coach
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_grief_signals_user ON grief_signals (user_id, created_at);
