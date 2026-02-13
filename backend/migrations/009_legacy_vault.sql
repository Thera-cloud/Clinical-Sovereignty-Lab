-- =============================================================================
-- Migration 009: Legacy Vault — Transgenerational Pattern Storage
-- Sovereign Swarm Intelligence Framework — Phase 4B
-- =============================================================================

-- ─── Legacy Vault Consent ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legacy_vault_consent (
    user_id         UUID NOT NULL REFERENCES users(id),
    family_id       UUID NOT NULL REFERENCES families(id),
    consented       BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, family_id)
);

CREATE INDEX IF NOT EXISTS idx_vault_consent_family ON legacy_vault_consent(family_id);


-- ─── Legacy Vault Entries ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legacy_vault_entries (
    id              SERIAL PRIMARY KEY,
    entry_id        UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    entry_type      VARCHAR(64) NOT NULL,
    family_id       UUID NOT NULL REFERENCES families(id),
    data            JSONB NOT NULL,
    blob_ref        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vault_entry_type ON legacy_vault_entries(entry_type, family_id);
CREATE INDEX IF NOT EXISTS idx_vault_family ON legacy_vault_entries(family_id);
CREATE INDEX IF NOT EXISTS idx_vault_created ON legacy_vault_entries(created_at DESC);


-- ─── Human-Swarm Teams (Phase 6A) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS swarm_teams (
    id              SERIAL PRIMARY KEY,
    team_id         UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    team_name       VARCHAR(128) NOT NULL,
    human_id        VARCHAR(64) NOT NULL,
    human_role      VARCHAR(64) NOT NULL,
    fibre_ids       UUID[] DEFAULT '{}',
    active          BOOLEAN DEFAULT TRUE,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_teams_human ON swarm_teams(human_id);
CREATE INDEX IF NOT EXISTS idx_teams_active ON swarm_teams(active) WHERE active = TRUE;


-- ─── Fibre Templates (Phase 6B) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fibre_templates (
    id              SERIAL PRIMARY KEY,
    template_name   VARCHAR(128) NOT NULL UNIQUE,
    fibre_type      VARCHAR(32) NOT NULL,
    config          JSONB NOT NULL,
    description     TEXT DEFAULT '',
    usage_count     INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
